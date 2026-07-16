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


_DATA_PURGE_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours


async def _periodic_data_purge():
    """
    Runs the demo's own retention policy (services/interaction_signals.py's
    _RETENTION_DAYS-day-old DemoInteractionSignal rows) automatically for the
    life of this process, instead of relying on a human remembering to run
    scripts/export_interaction_signals.py — see docs/DATA_RETENTION.md for
    the full retention policy this is one piece of. A real family's own
    data (StudentConfig, VoiceProfile, narration history, etc.) is
    deliberately NOT swept here — that data is retained until the parent
    explicitly deletes it (routers/pod.py's DELETE /pod/configs/{student}),
    never on a timer, since a family may use the same student profile for
    years. Self-contained and best-effort: one failed sweep logs a warning
    and tries again next interval rather than crashing the whole process.
    """
    from services.interaction_signals import purge_old_signals

    while True:
        await asyncio.sleep(_DATA_PURGE_INTERVAL_SECONDS)
        try:
            deleted = await purge_old_signals()
            if deleted:
                log.info("Periodic data purge: removed %d expired demo interaction-signal row(s)", deleted)
        except Exception:
            log.warning("Periodic data purge failed — will retry next interval", exc_info=True)


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
      5. Start the periodic data-retention purge loop (non-blocking) — see
         docs/DATA_RETENTION.md.
    Shutdown:
      6. Dispose the database connection pool cleanly.
      7. Close the pooled httpx clients (OpenAI TTS, Resend) cleanly.
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
    purge_task = asyncio.create_task(_periodic_data_purge())

    yield

    warmup_task.cancel()
    purge_task.cancel()

    await engine.dispose()
    log.info("Database connections closed")

    from services import email_service, voice_synthesis
    await voice_synthesis.aclose_http_client()
    await email_service.aclose_http_client()
    log.info("Pooled HTTP clients closed")


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
