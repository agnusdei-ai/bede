import hmac
from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List

from core.pin_policy import MIN_PIN_LENGTH, pin_is_strong

# Placeholder RESEND_FROM_ADDRESS — example.com can never be a verified
# sending domain in a real Resend account, so a deployment left on this
# default can never actually deliver mail no matter what RESEND_API_KEY is
# set to. services/email_service.py's email_configured() treats this value
# the same as an empty string — see that module for the full explanation.
DEFAULT_RESEND_FROM_ADDRESS = "Bede <bede@example.com>"

# Public (not module-private) since core/parent_credential.py's change-
# password/recovery-reset flow enforces the exact same floor when a parent
# sets a NEW password in-app — one source of truth for both the startup
# validator below and that later-added path.
MIN_SECRET_LENGTH = 32
MIN_PASSWORD_LENGTH = 8

# Single source of truth for which LOCALE values this deployment accepts,
# and the display name services/ai_service.py's _locale_directive uses when
# instructing Bede to converse natively in that language. "en" is the
# implicit default and is deliberately not listed here (it's the absence of
# a locale directive, not a language name to display) — see
# Settings.reject_unsupported_locale below. New languages get added here
# only once their content has actually been drafted and reviewed, per
# docs/LOCALIZATION.md — listing a code here is what turns it on.
SUPPORTED_LOCALES = {
    "es": "Spanish (Español)",
}


class Settings(BaseSettings):
    # ── AI models ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    tutor_model: str = "claude-sonnet-4-6"
    session_model: str = "claude-haiku-4-5-20251001"

    # ── Provider adapters (vendor-agnostic tutor backend) ─────────────────────
    # ai_service.py talks to a provider ADAPTER, not a hardcoded Anthropic
    # client — see services/adapters/ and docs/PROVIDER_ADAPTERS.md. This
    # decouples Bede from any single vendor so an account closure/lockout at one
    # provider can't take the whole tutor offline.
    #
    # BEDE_ADAPTER_ORDER is a comma-separated preference list; the router picks
    # the FIRST adapter that is actually configured (has its credentials set) and
    # skips the rest. The default is deliberately "local,anthropic" rather than
    # "anthropic": the refactor exists for the case where Anthropic access is
    # GONE, so a self-hosted vLLM server (local) is the practical primary and
    # Anthropic is kept only as an optional last resort — the router never
    # requires ANTHROPIC_API_KEY to start or serve. openai/mistral are supported
    # secondaries but kept OUT of the default order on purpose: OPENAI_API_KEY
    # already drives OpenAI TTS (services/voice_synthesis.py), and auto-routing
    # the tutor through OpenAI just because a TTS key exists would be a silent
    # surprise. Enable them explicitly, e.g. BEDE_ADAPTER_ORDER=local,openai,anthropic.
    bede_adapter_order: str = "local,anthropic"
    # Manual override — when set to a single adapter name (local/openai/mistral/
    # anthropic) it pins the tutor to that provider, skipping order/failover
    # entirely. Empty = honor BEDE_ADAPTER_ORDER.
    bede_force_adapter: str = ""

    # ── Local self-hosted LLM (OpenAI-compatible, e.g. vLLM) ──────────────────
    # Points at a vLLM (or any OpenAI-compatible) server's /v1 endpoint serving
    # Qwen3-Coder-30B-A3B-Instruct. IMPORTANT: this model needs a GPU and CANNOT
    # run inside the Render web service (Render has no GPU instances) — it runs
    # on separate GPU hardware and LOCAL_LLM_BASE_URL points at it over the
    # network. See docs/PROVIDER_ADAPTERS.md's infrastructure note. Empty
    # LOCAL_LLM_BASE_URL = the local adapter is treated as unconfigured/skipped.
    local_llm_base_url: str = ""
    # vLLM's OpenAI server has no built-in auth; the SDK still requires a
    # non-empty key, so this placeholder is fine for a private/tunnelled server.
    local_llm_api_key: str = "not-needed"
    local_llm_model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"

    # ── OpenAI chat adapter (secondary; distinct from OpenAI TTS above) ────────
    # Reuses OPENAI_API_KEY (defined below for TTS) as the credential, plus this
    # model. Only used for tutoring when "openai" is added to BEDE_ADAPTER_ORDER.
    openai_model: str = "gpt-4.1-mini"

    # ── Mistral chat adapter (optional secondary) ─────────────────────────────
    mistral_api_key: str = ""
    mistral_model: str = "mistral-large-latest"

    # ── Language / locale (optional) ──────────────────────────────────────────
    # NOT the language every session runs in — it's which single non-English
    # locale this deployment OFFERS as a login-time choice. The actual
    # language a given session runs in is picked at the login screen itself
    # (Login.tsx's English/Español toggle, only rendered when GET
    # /auth/locales reports this value is non-"en") and carried as a JWT
    # claim from that point on — see routers/auth.py's login(), not read
    # globally by services/ai_service.py's _locale_directive anymore (it
    # takes a locale parameter instead). "en" (default) means the toggle
    # never appears at all — every session is English, same as before this
    # feature existed. Setting this to a supported value doesn't force
    # Spanish on anyone; it just makes the choice available. Bede converses
    # natively in whichever language was chosen — generated directly by the
    # model, not machine-translated after the fact, so grade-level reading
    # complexity and Socratic intent survive the language switch.
    #
    # Still deployment-wide in one sense: which locale CAN be offered is
    # fixed at setup (one extra language per deployment, not an arbitrary
    # set) — only the moment-to-moment choice of English-vs-that-language is
    # per-login. This also still gates whether SessionConfig.sex is required
    # for every student (routers/pod.py) — once the toggle exists at all,
    # ANY student could land in a non-English session on any given login, so
    # every student needs sex on file the moment this is non-"en", not just
    # the ones a parent expects to use it.
    locale: str = "en"

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
    # core/audit.py's AuditEvent.SAFEGUARDING). Also doubles as the
    # security-alert address for core/audit.py's anomaly watch (AuditEvent.
    # ANOMALY_ALERT) — see docs/SECURITY.md.
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
    # Separate, more generous bucket for the mechanics of an ALREADY-started
    # streaming-transcription session (POST /voice/stream/{id}/chunk|finish,
    # GET /voice/stream/{id}/events) — see RateLimitMiddleware's own comment
    # for why these must not share rate_limit_voice_per_minute with new
    # session starts. RATE_LIMIT_VOICE_STREAM_SESSION_PER_MINUTE env var.
    rate_limit_voice_stream_session_per_minute: int = 120
    # Separate bucket for /auth/recovery/* specifically — a locked-out parent
    # who just exhausted rate_limit_auth_per_minute failing their password is
    # exactly the person who needs recovery next; sharing one "auth" bucket
    # meant the login attempts that trip parent_lockout.py also 429'd their
    # very next call to GET /auth/recovery/methods, and the frontend
    # (AccountRecovery.tsx) had no way to tell that transient 429 apart from
    # "recovery isn't configured on this instance" — see docs/SECURITY.md.
    # RATE_LIMIT_ACCOUNT_RECOVERY_PER_MINUTE env var.
    rate_limit_account_recovery_per_minute: int = 10

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
    # On by default — this is what powers the end-of-session "Math Skill
    # Growth" before/after report (services.diagnostic.get_session_growth,
    # wired into generate_session_summary). Still only ever the derived
    # deltas (skill_id, prior->posterior, probe_id, model_used, timestamp),
    # never a transcript or probe text — same privacy class as
    # NarrationAssessment (docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md §5.3).
    # When False, only the encrypted MasteryProfile vector is written;
    # DiagnosticEvidenceLog stays empty and session summaries fall back to
    # not mentioning skill growth at all (no data to report it from).
    diagnostic_evidence_log_enabled: bool = True

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

    # SECRET_KEY/MASTER_SECRET: matches the dev-default placeholders' own
    # "-32-chars-min" naming — SECRET_KEY signs every JWT (core/security.py),
    # MASTER_SECRET derives the encryption key hierarchy (core/encryption.py).
    # PARENT_PASSWORD: the same minimum setup.sh and scripts/setup_wizard/
    # wizard.py already enforce interactively — this is the corresponding
    # boot-time check for a deployment whose .env was hand-edited afterward
    # (e.g. during incident-response containment, docs/INCIDENT_RESPONSE.md)
    # rather than created through either wizard. Both are the module-level
    # MIN_SECRET_LENGTH/MIN_PASSWORD_LENGTH above — also reused by
    # core/parent_credential.py's in-app password change/recovery flow.

    @model_validator(mode="after")
    def reject_unsupported_locale(self) -> "Settings":
        """Fail fast on a typo'd or not-yet-onboarded LOCALE value rather
        than silently falling back to English — a deployment operator
        setting LOCALE=espanol or LOCALE=ES (case mismatch) deserves a clear
        startup error, not a family that thinks they configured Spanish and
        never notices Bede is still speaking English."""
        if self.locale != "en" and self.locale not in SUPPORTED_LOCALES:
            supported = ", ".join(sorted(SUPPORTED_LOCALES))
            raise ValueError(
                f"LOCALE={self.locale!r} is not supported — use 'en' or one of: {supported}"
            )
        return self

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
        elif len(self.secret_key) < MIN_SECRET_LENGTH:
            problems.append(
                f"SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters — "
                "it signs every JWT (core/security.py)"
            )
        if self.parent_password in self._WEAK_SECRETS:
            problems.append("PARENT_PASSWORD is set to the default dev value")
        elif len(self.parent_password) < MIN_PASSWORD_LENGTH:
            problems.append(
                f"PARENT_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters — "
                "the same minimum setup.sh and the setup wizard already enforce interactively"
            )
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
        elif len(self.master_secret) < MIN_SECRET_LENGTH:
            problems.append(
                f"MASTER_SECRET must be at least {MIN_SECRET_LENGTH} characters — "
                "it derives the encryption key hierarchy (core/encryption.py)"
            )
        if problems:
            raise ValueError(
                "Production mode is enabled but insecure defaults are in use: "
                + "; ".join(problems)
            )
        return self

    # NOTE — the license is deliberately NOT validated here anymore. It used
    # to be a hard model_validator that refused to construct Settings (and
    # therefore refused to boot) on a missing/invalid/expired LICENSE_KEY.
    # That turned every renewal into a customer-side .env edit, and an
    # expiry bricked the instance until someone edited that file. Licensing
    # is now resolved at startup in main.py's lifespan via
    # core/license_state.py — a valid license stored in the DATABASE (pasted
    # into the parent UI, PUT /admin/license) wins over the env key, and an
    # unlicensed production instance boots into a gated "license required"
    # mode (core/middleware.py's LicenseGateMiddleware) where the parent can
    # log in and paste a key, instead of refusing to start. Production
    # non-demo deployments are exactly as licensed as before — just not
    # brickable over an expiry.

    @model_validator(mode="after")
    def reject_no_ai_provider_configured_in_production(self) -> "Settings":
        """services/adapters/router.py never REQUIRES any single vendor's
        credentials to be present — an unconfigured adapter is simply
        skipped, and the router still returns something so the app boots
        (see get_default_client's own docstring). That's the right behavior
        at the router layer (never take the whole tutor down over one
        misconfigured entry), but it means a deployment with ZERO providers
        configured at all boots clean and then fails on the first real
        request — a confusing runtime error instead of a clear one at
        startup. This validator is the fail-fast counterpart: at least ONE
        of Anthropic, OpenAI, Mistral, or a local self-hosted model must be
        configured before a real family deployment goes live. Deliberately
        does not care WHICH one — that choice belongs entirely to the family
        (see docs/PROVIDER_ADAPTERS.md and setup.sh's provider picker)."""
        if not self.is_production:
            return self
        if not (
            self.anthropic_api_key
            or self.local_llm_base_url
            or self.openai_api_key
            or self.mistral_api_key
        ):
            raise ValueError(
                "Production mode is enabled but no AI provider is configured — set one of "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, MISTRAL_API_KEY, or LOCAL_LLM_BASE_URL "
                "(see docs/PROVIDER_ADAPTERS.md)"
            )
        return self

    @model_validator(mode="after")
    def reject_exposed_docs_and_wildcard_cors_in_production(self) -> "Settings":
        """Fail-fast counterpart to `api_docs_enabled`/`cors_origins_list`.
        setup.sh, scripts/setup_wizard/wizard.py, and render.yaml (for the
        demo) all set DISABLE_API_DOCS=true correctly — but nothing in
        Settings itself stopped a hand-edited production .env from booting
        with the interactive API docs (/docs, /redoc, /openapi.json —
        including the full internal admin/audit/license endpoint shapes)
        publicly reachable. Same reasoning for a CORS wildcard, which would
        defeat the "explicit whitelist, no wildcards" design cors_origins's
        own comment already states as intentional — checked regardless of
        production mode, since allow_credentials=True (main.py's
        CORSMiddleware) makes a "*" origin a misconfiguration at any time,
        not just in production."""
        if "*" in self.cors_origins_list:
            raise ValueError(
                "CORS_ORIGINS must not include '*' — list explicit allowed origins "
                "(comma-separated), never a wildcard, especially with allow_credentials=True"
            )
        if self.is_production and self.api_docs_enabled:
            raise ValueError(
                "Production mode is enabled but API docs are not disabled — set "
                "DISABLE_API_DOCS=true (otherwise /docs, /redoc, and /openapi.json "
                "are publicly reachable, exposing the full internal API schema)"
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
