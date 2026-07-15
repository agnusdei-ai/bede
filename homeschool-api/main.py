import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from core import constitution
from core.config import settings
from core.database import AsyncSessionLocal, create_tables, engine
from core.encryption import initialize_encryption
from core.middleware import ExfiltrationGuard, RateLimitMiddleware, SecurityHeadersMiddleware
from routers import admin, auth, catalog, diagnostic, feedback, mfa, narration, pod, sandbox, transcripts, tutor, voice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


async def _warm_voice_models():
    """
    Pre-load the local voice models (Resemblyzer speaker verification,
    Whisper fallback STT) in a background thread so the first child of the
    day doesn't pay the multi-second model-load latency at login or first mic
    use. Purely best-effort: each loader logs-and-degrades on its own when a
    package/model isn't installed, and all of them stay lazy anyway — this
    task just fires them early, off the event loop, without delaying boot.
    """
    from services import transcription, voice_auth, voice_synthesis

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, voice_auth.preload)
        await loop.run_in_executor(None, transcription.preload)
        await voice_synthesis.preload()
        log.info("Voice model warm-up finished")
    except Exception:
        log.warning("Voice model warm-up failed — models will load lazily on first use", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
      1. Verify Bede's constitution (tamper-evident, digest-pinned — see
         core/constitution.py) BEFORE anything else, including database
         initialization. Already checked once at import time as a
         module-level side effect; re-checked explicitly here so the
         ordering guarantee doesn't depend on which module happened to
         import core.constitution first.
      2. Create database tables (idempotent — safe on every boot)
      3. Load or generate device_salt and DATA_KEY from the DB
         PBKDF2 key derivation runs in a thread pool so the event loop
         is not blocked during the ~1.5 s CPU-bound operation.
      4. Kick off the voice-model warm-up in the background (non-blocking).
    Shutdown:
      5. Dispose the connection pool cleanly.
    """
    try:
        constitution.get_constitution()
        log.info("Constitution verified ✓")
        await create_tables()
        async with AsyncSessionLocal() as db:
            await initialize_encryption(settings.master_secret, db)
        log.info("Encryption initialised ✓")
    except RuntimeError as exc:
        log.critical("FATAL: %s", exc)
        sys.exit(1)

    warmup_task = asyncio.create_task(_warm_voice_models())

    yield

    warmup_task.cancel()

    await engine.dispose()
    log.info("Database connections closed")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Bede Homeschool Tutor API",
    description="Secure agentic AI tutor — Classical + Socratic method",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs"        if settings.api_docs_enabled else None,
    redoc_url="/redoc"      if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

# ── Middleware (applied in reverse declaration order) ─────────────────────────
# Outermost → GZip → SecurityHeaders → ExfiltrationGuard → RateLimit → CORS → routes
#
# GZip is outermost so it compresses the final response body after
# ExfiltrationGuard has already scanned/rebuilt it. Starlette's GZipMiddleware
# auto-excludes text/event-stream by content-type, so /tutor/chat's SSE stream
# passes through uncompressed and unbuffered, same as before.

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ExfiltrationGuard)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(mfa.router)
app.include_router(tutor.router)
app.include_router(narration.router)
app.include_router(transcripts.router)
app.include_router(voice.router)
app.include_router(admin.router)
app.include_router(pod.router)
app.include_router(catalog.router)
app.include_router(sandbox.router)
app.include_router(feedback.router)
app.include_router(diagnostic.router)


@app.get("/health")
async def health():
    """Public health check — no sensitive information returned."""
    return {"status": "ok"}
