"""Every knob the synthetic qualification harness turns, in one place.

Each value has a default and an environment override named ``QUAL_<NAME>``,
so the workflow (and a person running it by hand) changes inputs and never
code. Nothing here changes what the application does: these are the
harness's own settings and the lists the fail-closed preflight checks the
application's environment against.

See docs/SYNTHETIC_QUALIFICATION.md.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API_DIR = REPO / "homeschool-api"


def _env(name: str, default: str) -> str:
    return os.environ.get(f"QUAL_{name}", default)


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in _env(name, default).split(",") if item.strip()]


# ── Candidate ────────────────────────────────────────────────────────────────
CANDIDATE_SHA = _env("CANDIDATE_SHA", "")

# ── Output ───────────────────────────────────────────────────────────────────
OUT_DIR = Path(_env("OUT_DIR", str(REPO / "qualification-out"))).resolve()

# ── Stack ────────────────────────────────────────────────────────────────────
API_HOST = _env("API_HOST", "127.0.0.1")
API_PORT = int(_env("API_PORT", "8765"))
# The origin the browser page lives on. It is also WEBAUTHN_ORIGIN, so a
# passkey ceremony's clientDataJSON.origin matches what the server expects.
API_ORIGIN = _env("API_ORIGIN", f"http://localhost:{API_PORT}")
STUB_HOST = _env("AI_STUB_HOST", "127.0.0.1")
STUB_PORT = int(_env("AI_STUB_PORT", "8766"))
STARTUP_TIMEOUT_S = float(_env("STARTUP_TIMEOUT_S", "90"))
SHUTDOWN_TIMEOUT_S = float(_env("SHUTDOWN_TIMEOUT_S", "30"))
REQUEST_TIMEOUT_S = float(_env("REQUEST_TIMEOUT_S", "20"))
SSE_IDLE_WAIT_S = float(_env("SSE_IDLE_WAIT_S", "5"))

# ── Database ─────────────────────────────────────────────────────────────────
# The application connects as this role, which must NOT be a superuser: a
# superuser bypasses row security and ownership checks and can mask an
# authorization defect at the database layer.
APP_DB_ROLE = _env("APP_DB_ROLE", "bede_qual_app")
ALLOWED_DB_HOSTS = _csv("ALLOWED_DB_HOSTS", "127.0.0.1,localhost,postgres")
REQUIRE_EMPTY_DATABASE = _env("REQUIRE_EMPTY_DATABASE", "true") == "true"

# ── Login ────────────────────────────────────────────────────────────────────
# "virtual_authenticator" (default): every passkey ceremony runs in Chromium
# against a CDP virtual WebAuthn authenticator, through the real routes.
# "minted_token": the DOCUMENTED fallback. Teacher identities are created
# with the production provisioning service and their tokens minted with the
# production payload shape. It is recorded in the manifest as a deviation,
# and a run using it can never report the login cells as qualified.
TEACHER_AUTH_MODE = _env("TEACHER_AUTH_MODE", "virtual_authenticator")
TEACHER_AUTH_MODES = ("virtual_authenticator", "minted_token")

# ── Synthetic identities (the allowlist) ─────────────────────────────────────
CAMPUS_TITLES = {
    "campus_one": _env("CAMPUS_ONE_TITLE", "Synthetic Campus One"),
    "campus_two": _env("CAMPUS_TWO_TITLE", "Synthetic Campus Two"),
}
TEACHER_USERNAMES = {
    "teacher_one": _env("TEACHER_ONE_USERNAME", "synthetic-teacher-one"),
    "teacher_two": _env("TEACHER_TWO_USERNAME", "synthetic-teacher-two"),
}
# Deliberately ONE display name for both learners: cross-campus residue must
# not be able to hide behind distinct names.
SHARED_LEARNER_DISPLAY_NAME = _env("SHARED_LEARNER_DISPLAY_NAME", "Synthetic Learner")
LEARNER_FIXTURES = {"learner_one": "campus_one", "learner_two": "campus_two"}
TEACHER_HOME = {"teacher_one": "campus_one", "teacher_two": "campus_two"}
INSTITUTION_EMAIL_DOMAIN = _env("INSTITUTION_EMAIL_DOMAIN", "qualification.agnusdei.ai")

ALLOWED_NAMES = (
    set(CAMPUS_TITLES.values())
    | set(TEACHER_USERNAMES.values())
    | {SHARED_LEARNER_DISPLAY_NAME}
)

# ── Preflight lists ──────────────────────────────────────────────────────────
# Any of these set to a non-empty value fails the run before anything starts.
FORBIDDEN_NONEMPTY_ENV = _csv(
    "FORBIDDEN_NONEMPTY_ENV",
    # commercial AI
    "ANTHROPIC_API_KEY,OPENAI_API_KEY,MISTRAL_API_KEY,"
    # email (Resend) and outbound notification addresses
    "RESEND_API_KEY,RESEND_FROM_ADDRESS,PARENT_EMAIL,FEEDBACK_EMAIL,SALES_EMAIL,"
    # license server / billing
    "LICENSE_SERVER_URL,LICENSE_KEY,STRIPE_SECRET_KEY,STRIPE_WEBHOOK_SECRET,"
    "STRIPE_PUBLISHABLE_KEY,OPERATOR_TOKEN,ED25519_PRIVATE_KEY,"
    # external tool content
    "MCP_EXTERNAL_SERVERS",
)
# Any env var whose NAME starts with one of these prefixes and is non-empty fails.
FORBIDDEN_ENV_PREFIXES = _csv("FORBIDDEN_ENV_PREFIXES", "STRIPE_,RESEND_")
# Any env var whose NAME contains one of these markers and is truthy fails.
FORBIDDEN_TRUTHY_MARKERS = _csv(
    "FORBIDDEN_TRUTHY_MARKERS",
    "REAL_DATA,REAL_LEARNER,PRODUCTION_DATA,BILLING,AUTO_ENROLL,AUTOENROLL,"
    "AUTH_BYPASS,SKIP_AUTH,DISABLE_AUTH,AUTO_DELIVER,DELIVERY_ENABLED",
)
# Required exact values. A missing or different value fails.
REQUIRED_ENV = {
    "PRODUCTION": "false",
    "EDUCATOR_PILOT_ENABLED": "true",   # off would close every route under test: vacuous pass
    "ELEVATION_ENFORCED": "true",       # off is an authorization bypass
    "MCP_EXTERNAL_ENABLED": "false",
    "LOCUTO_IPC_ENABLED": "false",
}
# URL path segments that would mean a /pilot route launches or delivers
# instruction into a learner session.
DELIVERY_PATH_MARKERS = _csv(
    "DELIVERY_PATH_MARKERS", "session,launch,deliver,delivery,start,tutor,chat,stream",
)
# Names whose presence in the tutoring turn would mean it reads teacher-
# authorized instruction (mirrors tests/test_valor_pilot_delivery_disabled.py).
DELIVERY_SOURCE_MARKERS = _csv("DELIVERY_SOURCE_MARKERS", "authorized_instruction,pilot_session")
DELIVERY_SOURCE_FILES = _csv("DELIVERY_SOURCE_FILES", "routers/tutor.py,services/ai_service.py")

# ── Credential scan ──────────────────────────────────────────────────────────
# Values the harness itself generated (synthetic secrets) are scanned for
# verbatim in every collected log, in addition to these shapes.
CREDENTIAL_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{20,}",
    r"sk-ant-[A-Za-z0-9_-]{20,}",
    r"re_[A-Za-z0-9]{20,}",
    r"whsec_[A-Za-z0-9]{20,}",
    r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}",
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"postgres(?:ql)?(?:\+asyncpg)?://[^:\s/]+:[^@\s]+@",
]

# ── Package ──────────────────────────────────────────────────────────────────
LOCKFILES = _csv(
    "LOCKFILES",
    "homeschool-api/requirements.lock.txt,homeschool-api/requirements-dev.lock.txt,"
    "homeschool-tutor/package-lock.json",
)
