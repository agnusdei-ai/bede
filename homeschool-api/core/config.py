import hmac
from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List

MIN_PIN_LENGTH = 6


def _is_sequential(pin: str) -> bool:
    """True if every digit steps by the same +1/-1 from the last, mod 10 —
    catches not just 123456/654321 but wraparound runs like 789012/901234
    that a naive non-modular check would miss."""
    diffs = {(int(b) - int(a)) % 10 for a, b in zip(pin, pin[1:])}
    return diffs in ({1}, {9})


def pin_is_strong(pin: str) -> bool:
    """At least 6 digits, no digit repeated anywhere in the PIN, and not a
    simple sequential run (ascending or descending, wraparound included)."""
    return (
        pin.isdigit()
        and len(pin) >= MIN_PIN_LENGTH
        and len(set(pin)) == len(pin)
        and not _is_sequential(pin)
    )


class Settings(BaseSettings):
    # ── AI models ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    tutor_model: str = "claude-sonnet-4-6"
    session_model: str = "claude-haiku-4-5-20251001"

    # ── Voice output (Bede speaking) — self-hosted Kokoro TTS ────────────────
    # No cloud dependency, no per-user API key — runs locally via kokoro-onnx
    # (ONNX Runtime, CPU-friendly, ~80MB quantized model). If the model files
    # aren't present at KOKORO_MODEL_DIR, the frontend falls back to the
    # browser's built-in speechSynthesis (see useTextToSpeech.ts) — voice
    # output never blocks a session either way.
    #
    # One-time setup: download kokoro-v1.0.onnx and voices-v1.0.bin from
    # github.com/thewh1teagle/kokoro-onnx/releases into this directory, then
    # run scripts/evaluate_bede_voice.py to compare candidate voices and
    # confirm KOKORO_VOICE — see docs/VOICE_SETUP.md.
    kokoro_model_dir: str = "./models/kokoro"
    # Must be a warm, elderly, MALE voice — Bede's persona and voice are both
    # historically male (the Venerable Bede), never gender-ambiguous or female.
    # "bm_george" is a reasonable starting default (British Male) but is NOT
    # independently verified against real audio — confirm it with
    # scripts/evaluate_bede_voice.py before relying on it.
    kokoro_voice: str = "bm_george"

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
        a weak-default hygiene issue."""
        if self.demo_pin and (
            hmac.compare_digest(self.demo_pin, self.parent_password)
            or hmac.compare_digest(self.demo_pin, self.child_pin)
        ):
            raise ValueError("DEMO_PIN must not match PARENT_PASSWORD or CHILD_PIN")
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
                f"CHILD_PIN must be {MIN_PIN_LENGTH}+ digits, no digit repeated, and not a "
                "sequential run (e.g. 384756, not 111111, 123123, 123456, or 654321)"
            )
        if self.demo_pin and not pin_is_strong(self.demo_pin):
            problems.append(
                f"DEMO_PIN must be {MIN_PIN_LENGTH}+ digits, no digit repeated, and not a "
                "sequential run (e.g. 384756, not 111111, 123123, 123456, or 654321) — "
                "it's shared with the public, so it deserves the same bar as CHILD_PIN"
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
