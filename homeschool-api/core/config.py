import hmac
from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List

from core.pin_policy import MIN_PIN_LENGTH, pin_is_strong


class Settings(BaseSettings):
    # ── AI models ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    tutor_model: str = "claude-sonnet-4-6"
    session_model: str = "claude-haiku-4-5-20251001"

    # ── Voice output — self-hosted Kokoro TTS (undocumented internal fallback) ─
    # Not part of the documented setup path (docs/VOICE_SETUP.md covers only
    # OpenAI TTS below) — kept here purely as a code-level fallback for
    # anyone building from source who wants zero cloud dependency for voice.
    # Runs locally via kokoro-onnx (ONNX Runtime, CPU-friendly, ~80MB
    # quantized model). If the model files aren't present at
    # KOKORO_MODEL_DIR, the frontend falls back to the browser's built-in
    # speechSynthesis (see useTextToSpeech.ts) — voice output never blocks a
    # session either way.
    kokoro_model_dir: str = "./models/kokoro"
    # Must be a warm, elderly, MALE voice — Bede's persona and voice are both
    # historically male (the Venerable Bede), never gender-ambiguous or female.
    # "bm_george" is a reasonable starting default (British Male), not
    # independently verified against real audio. Can also be a '+'-separated
    # blend of two or more voices' style vectors, e.g. "bm_george+bm_lewis"
    # (equal blend) or "bm_george:0.7+bm_lewis:0.3" (weighted).
    kokoro_voice: str = "bm_george"
    # Kokoro's native speed is 1.0 — pushing it slower or faster tends to
    # introduce artifacts (stretched phonemes, odd pacing) rather than sound
    # more natural, since it moves the model outside its training range.
    # Valid range is 0.5–2.0 (enforced by kokoro-onnx itself).
    kokoro_speed: float = 1.0

    # ── Voice output — OpenAI TTS (preferred over Kokoro when configured) ────
    # Kokoro's ~82M-parameter model has a real ceiling — it never sounds more
    # than "decent small open model," no matter how KOKORO_VOICE/KOKORO_SPEED
    # are tuned (confirmed against real listening feedback, not a guess).
    # Setting OPENAI_API_KEY switches Bede's voice to OpenAI's TTS API, which
    # is a full cloud model and sounds meaningfully more natural. Leave unset
    # to keep the free, self-hosted Kokoro path (or no backend TTS at all —
    # the browser's own speech always still works either way).
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
    # not just a voice — no equivalent exists for Kokoro or tts-1/tts-1-hd.
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
    resend_from_address: str = "Bede <bede@example.com>"

    # ── Distress alert (optional) ─────────────────────────────────────────────
    # Unlike the post-session email above, a distress signal is child-
    # initiated — there's no parent present in the moment to type an address
    # in, so it has to be configured ahead of time. Reuses the same Resend
    # setup (RESEND_API_KEY/RESEND_FROM_ADDRESS above); leave PARENT_EMAIL
    # unset to disable this specific alert (the safeguarding event is still
    # always written to the encrypted audit log either way — see
    # core/audit.py's AuditEvent.SAFEGUARDING).
    parent_email: str = ""

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
    # Empty by default: the "demo" login role is entirely disabled unless a
    # deployment deliberately sets DEMO_PIN. Meant only for a dedicated public
    # demo deployment, never a family's real instance — issues a short-lived,
    # rights-restricted token against one fixed server-defined student config,
    # never the real parent_password/child_pin.
    demo_pin: str = ""
    demo_token_expire_minutes: int = 15
    demo_student_name: str = "Guest"
    demo_grade: str = "4"
    demo_grade_stage: str = "3-5"
    # Self-service alternative to the shared DEMO_PIN trial: a visitor
    # generates their own one-time 6-digit code (POST /auth/demo-code) rather
    # than typing a shared PIN or pasting their own Anthropic key. Capped by
    # message count instead of a hard session length (see
    # core/demo_code_session.py) — this expiry is just a backstop so a
    # generated token can't be replayed forever if leaked/copied.
    demo_code_token_expire_minutes: int = 120

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

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Explicit whitelist — no wildcards
    cors_origins: str = "http://localhost:5173,http://localhost:80"

    # ── Production flags ───────────────────────────────────────────────────────
    # Set to "true" in production to disable /docs and /redoc
    disable_api_docs: str = "false"
    # Set to "true" in Docker to enforce HTTPS-only cookie flags
    production: str = "false"

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

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.production.lower() == "true"

    @property
    def api_docs_enabled(self) -> bool:
        return self.disable_api_docs.lower() != "true"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
