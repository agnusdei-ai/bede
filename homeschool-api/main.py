import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core import constitution, elevation, identity, license_state, parent_credential, provider_state
from core.config import settings
from core.database import AsyncSessionLocal, LicenseConfig, create_tables, engine
from core.encryption import initialize_encryption
from core.middleware import ExfiltrationGuard, LicenseGateMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from routers import admin, auth, catalog, diagnostic, feedback, mfa, narration, pod, recovery, sandbox, transcripts, tutor, voice

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

    Two skips here, and together they are what keeps torch out of this
    process entirely — which is the only thing that actually moves the
    memory number.

    Resemblyzer speaker verification is skipped on a demo deployment
    (settings.is_demo_deployment): core/deps.py's require_parent and
    require_real_user both reject the "demo_code" role outright, and
    /voice/enroll, /voice/verify, and /voice/override are the ONLY callers
    of services/voice_auth.py's encoder — so on that deployment shape the
    model is structurally unreachable by any request that can ever occur.

    Whisper is skipped whenever speech-to-text isn't running in this process
    at all (services/transcription.py's uses_local_model — see
    settings.transcription_provider). That skip is the load-bearing one.
    Measured directly, skipping resemblyzer ALONE only trimmed ~30MB of live
    RSS (642MB vs 674MB, both fully warmed): the dominant cost is PyTorch at
    ~480MB just to import, and ctranslate2 (faster-whisper's backend) pulls
    torch in itself whenever torch is present in the environment, so as long
    as the local Whisper model was still being loaded, torch loaded too and
    the process stayed over Render's free-tier 512MB web-service limit. It
    was OOM-killed there for real (see docs/DEMO_HOSTING.md's memory
    section), and because services/streaming_transcription.py holds its
    sessions in memory in a single process, every restart took every
    in-flight child's voice turn down with it.

    A family's self-hosted instance sets neither DEMO_PIN nor
    TRANSCRIPTION_PROVIDER, so both models still preload exactly as before
    and real voice biometric child authentication is untouched.
    """
    from services import transcription, voice_auth, voice_synthesis

    loop = asyncio.get_running_loop()
    try:
        if not settings.is_demo_deployment:
            await loop.run_in_executor(None, voice_auth.preload)
        if transcription.uses_local_model():
            await loop.run_in_executor(None, transcription.preload)
        else:
            log.info(
                "Speech-to-text runs on the '%s' backend — skipping the local Whisper warm-up",
                settings.transcription_provider,
            )
        await voice_synthesis.preload()
        log.info("Voice model warm-up finished")
    except Exception:
        log.warning("Voice model warm-up failed — models will load lazily on first use", exc_info=True)


_DATA_PURGE_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours


def _log_security_posture() -> None:
    """One line per posture setting, every boot.

    These are the settings whose wrong value is invisible: a step-up that is
    configured off looks exactly like one that is on until somebody attempts
    a privileged action, and a legacy-token grace that nobody ever turned off
    looks exactly like one that was never needed. Neither fails, neither
    logs, and neither shows up in a test. The only thing that surfaces them
    is saying so at startup — GET /admin/status reports the same facts for
    anyone who would rather query than read logs.

    Warnings, not errors: every one of these has a legitimate reason to be
    in its weaker state (a deployment driving the API directly, with no
    frontend to prompt; the upgrade was an hour ago; this is a family
    instance with no demo role). Refusing to boot over a defensible choice
    is how operators learn to work around startup checks.
    """
    if settings.elevation_enforced:
        log.info("Privileged access: step-up ENFORCED (%d min)", settings.elevation_ttl_minutes)
    else:
        log.warning(
            "Privileged access: step-up NOT enforced — a parent session holds "
            "management-plane rights for its full lifetime. This is off by "
            "explicit configuration (the default is enforced); set "
            "ELEVATION_ENFORCED=true to turn it back on. See docs/SECURITY.md."
        )

    if settings.legacy_token_grace:
        log.warning(
            "Auth: LEGACY_TOKEN_GRACE is on — JWTs issued before identity domains "
            "existed are still accepted. Needed only for the first deploy after "
            "upgrading; set LEGACY_TOKEN_GRACE=false once every pre-upgrade token "
            "has expired (8h max)."
        )

    # Only meaningful where the demo role is actually reachable. On a family
    # instance there is no demo token to isolate, so saying anything would be
    # noise an operator learns to skip past.
    if settings.demo_pin:
        if identity.demo_key_is_independent():
            log.info("Identity domains: demo signing key is INDEPENDENT of SECRET_KEY ✓")
        else:
            log.warning(
                "Identity domains: demo signing key is DERIVED from SECRET_KEY. Tokens are "
                "still domain-separated (a demo token cannot be replayed as a parent token), "
                "but a SECRET_KEY compromise yields both. Set DEMO_SECRET_KEY on an "
                "internet-facing demo instance."
            )


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

        # Expired privileged-access grants (core/elevation.py). Hygiene, not
        # a security control — is_elevated() checks the timestamp, so an
        # expired row is already inert. Without this the table grows by one
        # row per elevation forever on an appliance nobody prunes. Kept in
        # its own try so a failure here can't stop the retention sweep above,
        # which is the one with an actual policy behind it.
        try:
            async with AsyncSessionLocal() as db:
                await elevation.purge_expired(db)
        except Exception:
            log.warning("Elevation purge failed — will retry next interval", exc_info=True)


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
      4. Resolve the effective license (core/license_state.py): a valid
         license stored in the DB (applied from the parent UI) wins over
         the env LICENSE_KEY. An unlicensed production instance boots into
         a gated "license required" mode (LicenseGateMiddleware) instead
         of refusing to start — the parent renews in-app, no .env edit.
      5. Sync core/parent_credential.py's in-process credentials_version
         cache from the DB — same DB-wins-over-env precedent as licensing,
         applied to PARENT_PASSWORD (core/deps.py checks this cache on
         every parent/parent_pending request, not the DB directly).
      5b. Sync core/provider_state.py's in-process AI-provider-primary
          cache from the DB — same precedent again, applied to WHICH
          configured adapter serves as primary (services/adapters/router.py
          consults this cache on every tutoring turn).
      6. Kick off the voice-model warm-up in the background (non-blocking).
      7. Start the periodic data-retention purge loop (non-blocking) — see
         docs/DATA_RETENTION.md.
    Shutdown:
      8. Dispose the database connection pool cleanly.
      9. Close the pooled httpx clients (OpenAI TTS, Resend) cleanly.
    """
    try:
        constitution.get_constitution()
        log.info("Constitution verified ✓")
        await create_tables()
        async with AsyncSessionLocal() as db:
            await initialize_encryption(settings.master_secret, db)
        log.info("Encryption initialised ✓")
        async with AsyncSessionLocal() as db:
            db_license = await db.get(LicenseConfig, "license")
        license_state.refresh(
            settings.license_key,
            db_license.license_text if db_license else None,
            required=settings.is_production and not settings.is_demo_deployment,
        )
        async with AsyncSessionLocal() as db:
            await parent_credential.refresh_from_db(db)
        async with AsyncSessionLocal() as db:
            await provider_state.refresh_from_db(db)
    # SQLAlchemyError/OSError alongside RuntimeError because the steps above
    # are mostly DATABASE steps, and a database that cannot be reached raises
    # neither a RuntimeError nor anything else this once caught: create_tables()
    # surfaces asyncpg's failure as sqlalchemy.exc.OperationalError, and a DNS
    # failure on the DB host can arrive as a bare socket.gaierror (OSError).
    # Both escaped this handler entirely, so the one boot failure most likely
    # to happen in production — "Postgres is unreachable" — produced an
    # unhandled traceback out of the lifespan instead of the single, greppable
    # "FATAL:" line this block exists to give an operator. Diagnosing a live
    # outage on 2026-08-04 is what surfaced it.
    except (RuntimeError, SQLAlchemyError, OSError) as exc:
        log.critical("FATAL: %s: %s", type(exc).__name__, exc)
        sys.exit(1)

    _log_security_posture()

    warmup_task = asyncio.create_task(_warm_voice_models())
    purge_task = asyncio.create_task(_periodic_data_purge())
    # Bounds how long a running replica can keep honouring a token that a
    # SIBLING replica already invalidated by a password change or recovery.
    # A no-op cost on a single-instance deployment (which is what both
    # supported topologies are today) and the thing that stops "change your
    # password to end a takeover" from being quietly false under
    # replication — see core/parent_credential.py and
    # docs/DEPLOYMENT_TOPOLOGY.md.
    credentials_refresh_task = asyncio.create_task(parent_credential.periodic_refresh())

    yield

    warmup_task.cancel()
    purge_task.cancel()
    credentials_refresh_task.cancel()

    await engine.dispose()
    log.info("Database connections closed")

    from services import email_service, transcription, voice_synthesis
    await voice_synthesis.aclose_http_client()
    await transcription.aclose_http_client()
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

# ── Middleware ──────────────────────────────────────────────────────────────
# Starlette builds the ASGI stack from `app.user_middleware` by wrapping
# outward: `add_middleware` inserts each new entry at the FRONT of that list
# (see Starlette's `Starlette.add_middleware`), and `build_middleware_stack`
# then wraps the router in `reversed(user_middleware)` order. Net effect:
# the LAST `add_middleware()` call becomes the OUTERMOST layer — first to
# see the request, LAST to touch the response before it leaves the process.
#
# Declared here so the *last* call is GZip, making it genuinely outermost:
#   request  →  GZip → LicenseGate → CORS → RateLimit → ExfiltrationGuard → SecurityHeaders  → routes
#   response ←  GZip ← LicenseGate ← CORS ← RateLimit ← ExfiltrationGuard ← SecurityHeaders  ← routes
#
# ExfiltrationGuard must inspect the PLAINTEXT response body — the whole
# point of _BLOCKED_PATTERNS is scanning for leaked key material — so it has
# to run before GZip compresses anything. An earlier ordering had GZip added
# FIRST, which (by the same front-insert/reversed-wrap rule) made GZip the
# INNERMOST layer instead of the outermost one: it compressed the response
# before ExfiltrationGuard ever saw it, so every _BLOCKED_PATTERNS check
# silently stopped matching on any response >= minimum_size sent with
# `Accept-Encoding: gzip` (i.e. every browser) — the guard was scanning gzip
# magic bytes, not the JSON it was written to inspect. See
# tests/test_middleware.py's test_exfiltration_guard_still_scans_a_gzip_
# eligible_response_in_the_assembled_stack for the regression coverage; that
# test builds the real multi-middleware stack specifically because the
# per-middleware unit tests above it can't see an ordering bug like this one.
#
# GZipMiddleware auto-excludes text/event-stream by content-type, so
# /tutor/chat's SSE stream passes through uncompressed and unbuffered
# regardless of where GZip sits in the stack.

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
# When an unlicensed production instance is in "license required" mode,
# only login/MFA and the license endpoints pass; everything else gets a
# clear 403. Added before GZip (so still wrapped BY GZip, i.e. compressed
# on the way out) and after CORS (so a gated response still carries CORS
# headers) — unchanged from the original relative ordering of these two.
app.add_middleware(LicenseGateMiddleware)
# Added LAST: outermost layer, compresses only after every other middleware
# — including ExfiltrationGuard's scan — has already run. See the ordering
# note above.
app.add_middleware(GZipMiddleware, minimum_size=500)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(mfa.router)
app.include_router(recovery.router)
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


# Bounds the probe itself. Without a timeout, a connection that hangs rather
# than refusing (a half-open socket, a saturated network path) would hang the
# health check too, and the platform would read "no response" — which is the
# right verdict, but reached by stalling a worker rather than by answering.
_HEALTH_DB_TIMEOUT_SECONDS = 3.0


@app.get("/health")
async def health(response: Response):
    """Readiness check — whether this instance can actually serve, not just
    whether the process is running. No sensitive information returned.

    Deliberately NOT an unconditional `{"status": "ok"}` any more. This is
    the path `render.yaml`'s `healthCheckPath` points at, and a health check
    that cannot fail reports a dead service as healthy. Every real endpoint
    here needs the database — there is no in-memory fallback, see
    core/database.py — so an instance that cannot reach Postgres cannot
    serve a single request. The old version returned 200 anyway: the
    platform dashboard stayed green, nothing alerted, and a live outage on
    2026-08-04 was diagnosed for an hour with "Deployed ✓" on screen the
    whole time, which is precisely the evidence that ruled the database out
    early and wrongly.

    The tradeoff is stated rather than hidden. Returning 503 while the
    database is unreachable means the platform may restart this instance or
    stop routing to it, and if the fault is at the database end a restart
    will not fix it. That is intended. A service that can answer nothing
    should fail visibly rather than sit green absorbing requests it can only
    drop — the failure mode this exists to close is the silent one, and
    trading it for a loud one is the whole point.
    """
    try:
        async with asyncio.timeout(_HEALTH_DB_TIMEOUT_SECONDS):
            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))
    except Exception as exc:
        # Logged at WARNING with the exception type, because the platform
        # only records "health check failed" — the reason (timeout vs.
        # refused vs. auth) is the part an operator actually needs, and this
        # is the only place it gets written down.
        log.warning("Health check FAILED — database unreachable: %s: %s", type(exc).__name__, exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
