import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import AsyncSessionLocal, create_tables, engine
from core.encryption import initialize_encryption
from core.middleware import ExfiltrationGuard, RateLimitMiddleware, SecurityHeadersMiddleware
from routers import admin, auth, catalog, narration, pod, transcripts, tutor, voice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
      1. Create database tables (idempotent — safe on every boot)
      2. Load or generate device_salt and DATA_KEY from the DB
         PBKDF2 key derivation runs in a thread pool so the event loop
         is not blocked during the ~1.5 s CPU-bound operation.
    Shutdown:
      3. Dispose the connection pool cleanly.
    """
    try:
        await create_tables()
        async with AsyncSessionLocal() as db:
            await initialize_encryption(settings.master_secret, db)
        log.info("Encryption initialised ✓")
    except RuntimeError as exc:
        log.critical("FATAL: %s", exc)
        sys.exit(1)

    yield

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
# Outermost → SecurityHeaders → ExfiltrationGuard → RateLimit → CORS → routes

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
app.include_router(tutor.router)
app.include_router(narration.router)
app.include_router(transcripts.router)
app.include_router(voice.router)
app.include_router(admin.router)
app.include_router(pod.router)
app.include_router(catalog.router)


@app.get("/health")
async def health():
    """Public health check — no sensitive information returned."""
    return {"status": "ok"}
