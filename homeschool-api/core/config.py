import hmac
from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List

from core import licensing
from core.pin_policy import MIN_PIN_LENGTH, pin_is_strong

# Placeholder RESEND_FROM_ADDRESS — example.com can never be a verified
# sending domain in a real Resend account, so a deployment left on this
# default can never actually deliver mail no matter what RESEND_API_KEY is
# set to. services/email_service.py's email_configured() treats this value
# the same as an empty string — see that module for the full explanation.
DEFAULT_RESEND_FROM_ADDRESS = "Bede <bede@example.com>"


class Settings(BaseSettings):
    # ── AI models ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    tutor_model: str = "claude-sonnet-4-6"
    session_model: str = "claude-haiku-4-5-20251001"

    # ── Voice output — OpenAI TTS ─────────────────────────────────────────────
    # Setting OPENAI_API_KEY switches Bede's voice to OpenAI's TTS API — a
    # full cloud model, meaningfully more natural than a browser's default
    # voice. Leave unset to skip cloud voice entirely — the browser's own
    # speech takes over automatically, with no other changes needed (see
    # useTextToSpeech.ts). No self-hosted TTS backend is used anymore.
    openai_api_key: str = ""
    # gpt-4o-mini-tts (not the older tts-1/tts-1-hd) is the only OpenAI TTS
    # model that accepts `instructions` below — that's what actually lets us
    # steer character/delivery rather than just picking a fixed preset voice.
    openai_tts_model: str = "gpt-4o-mini-tts"
    # OpenAI's preset voices are fixed timbres, not custom-designed — "fable"
    # is the one OpenAI itself describes as having a British storyteller
    # quality, the closest preset starting point for Bede. Not independently
    # verified against real audio; try "onyx" (deeper, American) too.
    openai_tts_voice: str = "fable"
    # gpt-4o-mini-tts-only: steers delivery style/character in plain English.
    # This is the main lever for actually sounding like "a specific monk,"
    # not just a voice — no equivalent exists for tts-1/tts-1-hd.
    openai_tts_instructions: str = (
        "Speak as Bede, an elderly Benedictine monk from Southern England. "
        "Warm, unhurried, and deliberately thoughtful — the quiet, measured "
        "cadence of someone used to contemplation and reading aloud, never "
        "brisk or robotic. Gentle authority, softly spoken."
    )

    # ── Post-session diagnostic email (optional) ─────────────────────────────
    # Lets a parent (or a demo visitor) get Bede's end-of-session notes
    # emailed to them via Resend. The address is used for exactly one send
    # and is never written to the database or the audit log — see
    # services/email_service.py and routers/tutor.py's /email-summary.
    # Leave RESEND_API_KEY unset to disable the feature entirely.
    resend_api_key: str = ""
    # Must be a verified sending address/domain in your Resend account.
    resend_from_address: str = DEFAULT_RESEND_FROM_ADDRESS

    # ── Distress alert (optional) ─────────────────────────────────────────────
    # Unlike the post-session email above, a distress signal is child-
    # initiated — there's no parent present in the moment to type an address
    # in, so it has to be configured ahead of time. Reuses the same Resend
    # setup (RESEND_API_KEY/RESEND_FROM_ADDRESS above); leave PARENT_EMAIL
    # unset to disable this specific alert (the safeguarding event is still
    # always written to the encrypted audit log either way — see
    # core/audit.py's AuditEvent.SAFEGUARDING).
    parent_email: str = ""

    # ── Beta feedback (optional) ────────────────────────────────────────────────
    # Where CX/UX/content-quality feedback submitted via POST /feedback (any
    # authenticated role — parent, child, or a public demo visitor) is routed.
    # This is the operator's own inbox, deliberately separate from PARENT_EMAIL
    # above (a family's own address) — reuses the same Resend setup. Leave
    # unset to disable the feature entirely (POST /feedback returns 404).
    feedback_email: str = ""

    # ── Auth ───────────────────────────────────────────────────────────────────
    secret_key: str = "dev-secret-CHANGE-IN-PRODUCTION-must-be-32-chars-min"
    algorithm: str = "HS256"
    # Parent sessions: up to 8h (full school day). Child: 4h (single session).
    access_token_expire_minutes: int = 480
    child_token_expire_minutes: int = 240

    # Single-family credentials (set via env — never hardcoded in code)
    parent_password: str = "change-me-parent"
    child_pin: str = "0000"

    # ── Public demo mode (optional) ────────────────────────────────────────────
    # Empty by default: the public demo is entirely disabled unless a
    # deployment deliberately sets DEMO_PIN. Meant only for a dedicated public
    # demo deployment, never a family's real instance. DEMO_PIN is no longer a
    # credential anyone types — it's purely the on/off switch for the whole
    # public demo (POST /auth/demo-code is 404 when this is empty). The
    # visitor's actual login is a self-service, one-time 6-digit code (see
    # core/demo_code_session.py), which issues a short-lived, rights-
    # restricted token against one fixed server-defined student config, never
    # the real parent_password/child_pin. Each generated code is independent,
    # so concurrent visitors never collide with each other.
    demo_pin: str = ""
    demo_student_name: str = "Guest"
    demo_grade: str = "4"
    demo_grade_stage: str = "3-5"
    # Capped by message count instead of a hard session length (see
    # core/demo_code_session.py) — this expiry is just a backstop so a
    # generated token can't be replayed forever if leaked/copied.
    demo_code_token_expire_minutes: int = 120

    # ── Per-IP rate limits (requests per minute per client IP) ────────────────
    # Enforced by core/middleware.py's RateLimitMiddleware. The defaults suit
    # a family LAN and ordinary public-demo traffic. Raise them via env vars
    # (RATE_LIMIT_AUTH_PER_MINUTE, RATE_LIMIT_API_PER_MINUTE,
    # RATE_LIMIT_VOICE_PER_MINUTE) for an event where many visitors share one
    # public IP — a conference room's Wi-Fi looks like a single very chatty
    # client to a per-IP limiter. Takes effect on restart; no code edit.
    rate_limit_auth_per_minute: int = 10
    rate_limit_api_per_minute: int = 120
    rate_limit_voice_per_minute: int = 20

    # ── Sandbox mode (optional, parent-only) ──────────────────────────────────
    # An extra PIN — same "empty = disabled" pattern and strength rules as
    # DEMO_PIN — that unlocks a direct-answer chat with Bede for testing and
    # exploration (routers/sandbox.py). Unlike DEMO_PIN, this doesn't grant a
    # separate login/role: it's an additional check layered on top of an
    # *already-authenticated parent session* (require_parent), so it reuses
    # all of parent auth's existing security rather than duplicating it.
    # Nothing said in the sandbox is ever written to the database — no
    # narration assessments, no session records, no audit-logged content.
    sandbox_pin: str = ""

    # ── Parent MFA: FIDO2 security key (YubiKey, etc.) + TOTP ─────────────────
    # Empty rp_id disables WebAuthn entirely (same "empty = disabled" pattern
    # as DEMO_PIN) — a family only needs to set these if they want to enroll a
    # hardware key. Must be the exact domain the tablets/browsers use to reach
    # this deployment (no scheme/port) — WebAuthn refuses to verify otherwise.
    webauthn_rp_id: str = ""
    webauthn_rp_name: str = "Bede"
    webauthn_origin: str = ""
    # TOTP has no domain-binding requirement, so it's always available — no
    # separate enable flag needed, enrollment itself is the opt-in.
    totp_issuer: str = "Bede Homeschool"
    # Short-lived — just long enough for the parent to complete their second
    # factor right after the password check.
    mfa_pending_token_expire_minutes: int = 5

    # ── Database ──────────────────────────────────────────────────────────────
    # asyncpg-compatible PostgreSQL URL.
    # Neon example: postgresql+asyncpg://user:pass@host/db?ssl=require
    database_url: str = ""

    # ── Encryption at rest ─────────────────────────────────────────────────────
    # MASTER_SECRET is used to derive the Key Encryption Key.
    # Change this only with a key rotation procedure (see core/encryption.py).
    master_secret: str = "change-me-master-secret-32-chars-min"

    # ── Voice verification thresholds (cosine similarity, 0–1) ───────────────
    # Tune these per deployment. MFCC scores run ~0.05 lower than resemblyzer.
    voice_threshold_high: float = 0.82    # auto-pass
    voice_threshold_medium: float = 0.68  # parent override available

    # ── Diagnostic engine (optional) ──────────────────────────────────────────
    # Off by default — the strictest reading of "never persist raw evidence"
    # (docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md §5.3). When False, only the
    # encrypted MasteryProfile vector is written; DiagnosticEvidenceLog (the
    # derived-delta audit trail) stays empty even though the table exists.
    diagnostic_evidence_log_enabled: bool = False

    # ── Demo interaction-pattern analysis (optional) ──────────────────────────
    # On by default for demo sessions only (never parent/child production) —
    # structural signals only (which tools fired, turn counts, subject
    # completions), never conversation content. Disclosed in the demo's own
    # consent copy (demo/src/App.tsx). See services/interaction_signals.py.
    interaction_signal_logging_enabled: bool = True

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Explicit whitelist — no wildcards
    cors_origins: str = "http://localhost:5173,http://localhost:80"

    # ── Production flags ───────────────────────────────────────────────────────
    # Set to "true" in production to disable /docs and /redoc
    disable_api_docs: str = "false"
    # Set to "true" in Docker to enforce HTTPS-only cookie flags
    production: str = "false"

    # ── License ─────────────────────────────────────────────────────────────
    # Required once PRODUCTION=true, unless this is the public demo (see
    # is_demo_deployment / reject_missing_or_invalid_license_in_production
    # below) — an offline-verifiable certificate issued by scripts/issue_license.py.
    # See core/licensing.py and docs/PRODUCTION_SETUP.md#licensing.
    license_key: str = ""

    _WEAK_SECRETS = {
        "dev-secret-CHANGE-IN-PRODUCTION-must-be-32-chars-min",
        "change-me-parent",
        "change-me-master-secret-32-chars-min",
        "0000",
    }

    @model_validator(mode="after")
    def reject_demo_pin_reuse(self) -> "Settings":
        """A demo PIN that matches a real credential would let the low-rights
        demo role double as real family access, or vice versa — reject that
        regardless of production mode, since it's a correctness bug, not just
        a weak-default hygiene issue. Same reasoning for SANDBOX_PIN, which
        would otherwise let someone who only knows the child's PIN talk their
        way into the direct-answer sandbox by guessing it matches."""
        if self.demo_pin and (
            hmac.compare_digest(self.demo_pin, self.parent_password)
            or hmac.compare_digest(self.demo_pin, self.child_pin)
        ):
            raise ValueError("DEMO_PIN must not match PARENT_PASSWORD or CHILD_PIN")
        if self.sandbox_pin and (
            hmac.compare_digest(self.sandbox_pin, self.parent_password)
            or hmac.compare_digest(self.sandbox_pin, self.child_pin)
            or (self.demo_pin and hmac.compare_digest(self.sandbox_pin, self.demo_pin))
        ):
            raise ValueError("SANDBOX_PIN must not match PARENT_PASSWORD, CHILD_PIN, or DEMO_PIN")
        return self

    @model_validator(mode="after")
    def reject_weak_defaults_in_production(self) -> "Settings":
        if not self.is_production:
            return self
        problems = []
        if self.secret_key in self._WEAK_SECRETS:
            problems.append("SECRET_KEY is set to the default dev value")
        if self.parent_password in self._WEAK_SECRETS:
            problems.append("PARENT_PASSWORD is set to the default dev value")
        if self.child_pin in self._WEAK_SECRETS:
            problems.append("CHILD_PIN is set to the default dev value")
        elif not pin_is_strong(self.child_pin):
            problems.append(
                f"CHILD_PIN must be {MIN_PIN_LENGTH}+ digits and not an easily-guessable pattern "
                "— no sequential run (123456, 654321), repeated block (111111, 123123, 121212), "
                "or palindrome (669966). Repeated digits are fine otherwise, e.g. 602656 is a good PIN"
            )
        if self.demo_pin and not pin_is_strong(self.demo_pin):
            problems.append(
                f"DEMO_PIN must be {MIN_PIN_LENGTH}+ digits and not an easily-guessable pattern "
                "— no sequential run (123456, 654321), repeated block (111111, 123123, 121212), "
                "or palindrome (669966). Repeated digits are fine otherwise, e.g. 602656 is a good PIN — "
                "it's shared with the public, so it deserves the same bar as CHILD_PIN"
            )
        if self.sandbox_pin and not pin_is_strong(self.sandbox_pin):
            problems.append(
                f"SANDBOX_PIN must be {MIN_PIN_LENGTH}+ digits and not an easily-guessable pattern "
                "— no sequential run (123456, 654321), repeated block (111111, 123123, 121212), "
                "or palindrome (669966). Repeated digits are fine otherwise, e.g. 602656 is a good PIN"
            )
        if self.master_secret in self._WEAK_SECRETS:
            problems.append("MASTER_SECRET is set to the default dev value")
        if problems:
            raise ValueError(
                "Production mode is enabled but insecure defaults are in use: "
                + "; ".join(problems)
            )
        return self

    @model_validator(mode="after")
    def reject_missing_or_invalid_license_in_production(self) -> "Settings":
        """A real family deployment running PRODUCTION=true must carry a
        genuine, unexpired license. The operator's own public demo is
        exempt (see is_demo_deployment) — it's a stateless, zero-seat
        instance that exists specifically to be frictionless for
        prospective customers to try, so gating it behind the same
        paid-license check it's meant to sell is counterproductive, and
        there's no per-family seat count to enforce there in the first
        place. Kept as its own validator, separate from
        reject_weak_defaults_in_production above, since a license problem
        is a distinct failure mode (missing/invalid/expired, not "using a
        dev default") worth its own clear error message."""
        if not self.is_production or self.is_demo_deployment:
            return self
        if not self.license_key:
            raise ValueError(
                "Production mode is enabled but LICENSE_KEY is not set — issue one with "
                "scripts/issue_license.py (see docs/PRODUCTION_SETUP.md#licensing)"
            )
        try:
            info = licensing.verify_license(self.license_key)
        except licensing.InvalidLicenseError as exc:
            raise ValueError(f"LICENSE_KEY is invalid: {exc}") from exc
        if info.is_expired:
            raise ValueError(
                f"LICENSE_KEY expired on {info.expires.isoformat()} "
                f"({info.tier} license for {info.licensee!r}) — renew to continue running in production"
            )
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.production.lower() == "true"

    @property
    def is_demo_deployment(self) -> bool:
        """DEMO_PIN is the deliberate, deployment-level on/off switch for the
        whole public demo (see the field's own comment above) — never set on
        a family's real instance, so its presence reliably identifies "this
        is the operator's own public demo," not just "this happens to have a
        PIN configured." """
        return bool(self.demo_pin)

    @property
    def api_docs_enabled(self) -> bool:
        return self.disable_api_docs.lower() != "true"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
