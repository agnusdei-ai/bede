"""
Async SQLAlchemy setup targeting Neon (or any PostgreSQL provider).

Tables carry no plaintext — every BYTEA column that holds user data is
AES-256-GCM encrypted by core/encryption.py before it reaches the driver.

Startup sequence (main.py lifespan):
  1. create_tables()          — idempotent CREATE TABLE IF NOT EXISTS
  2. initialize_encryption()  — reads/writes encryption_config rows
"""

from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import Depends
from sqlalchemy import BigInteger, DateTime, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.config import settings


def normalize_database_url(url: str) -> str:
    """Most managed providers (Render, Railway, Heroku-style "postgres://")
    hand you a plain sync-driver URL — SQLAlchemy's async engine needs the
    +asyncpg suffix explicit in the scheme or it'll try (and fail) to load
    psycopg2 instead. Normalizing here means copy-pasting a provider's
    connection string as-is just works, rather than being a silent
    first-deploy footgun that only surfaces as an opaque driver error."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


def _build_engine():
    url = settings.database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Provide a postgresql+asyncpg://... connection string."
        )
    url = normalize_database_url(url)
    return create_async_engine(
        url,
        pool_pre_ping=True,   # verify connection health before each use
        pool_size=5,
        max_overflow=5,
    )


engine = _build_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class EncryptionConfig(Base):
    """Stores device.salt (raw bytes) and data_key (KEK-wrapped)."""
    __tablename__ = "encryption_config"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class LicenseConfig(Base):
    """The license key applied from the parent UI (PUT /admin/license) — a
    renewal/upgrade path that needs no .env edit and no restart. A single
    well-known row; the signed license text is not secret material (it's
    the same token the customer received by email, verifiable only against
    the embedded public key), so it's stored as plain text. Selection
    between this and the env LICENSE_KEY happens in core/license_state.py."""
    __tablename__ = "license_config"

    key: Mapped[str] = mapped_column(String(50), primary_key=True, default="license")
    license_text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AuditLog(Base):
    """One AES-GCM-encrypted record per audit event."""
    __tablename__ = "audit_log"

    # BigInteger().with_variant(Integer(), "sqlite"): on Postgres this is a
    # real BIGINT/BIGSERIAL identity column, unchanged from before. Plain
    # BigInteger doesn't get SQLite's "INTEGER PRIMARY KEY" rowid-alias
    # autoincrement (SQLite only special-cases the exact type name
    # "INTEGER"), which otherwise makes every insert under a SQLite test
    # engine fail with a NOT NULL constraint on id.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    event_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class VoiceProfile(Base):
    """One encrypted embedding row per enrolled student."""
    __tablename__ = "voice_profiles"

    student_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    profile_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class StudentConfig(Base):
    """Per-student session configuration saved by parent before each pod session."""
    __tablename__ = "student_configs"

    student_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    config_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class NarrationAssessment(Base):
    """One rubric-scored assessment per narration Bede evaluates during a session."""
    __tablename__ = "narration_assessments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    session_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    assessment_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class LearnerProfile(Base):
    """Stable learner-type profile per student — synthesized after session 3+."""
    __tablename__ = "learner_profiles"

    student_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    session_count: Mapped[int] = mapped_column(nullable=False, default=0)
    profile_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class LearnerBehaviorCheck(Base):
    """
    A deliberately minimal, parent-only sanity check on one claim: does
    Bede's own processing_style adaptation (services/ai_service.py's
    _processing_style_note, which asks Bede to reach for a specific tool
    more often for a given profile) actually change its behavior. This is
    NOT a psychometric instrument and makes no claim that categorizing a
    child this way improves learning outcomes — the "learning styles"
    literature this profile is loosely modeled on (VAK/VARK) is itself
    contested for that stronger claim (see Pashler et al. 2008). It only
    answers the narrower, verifiable question: since being profiled this
    way, how often has Bede actually followed through.

    Exists only for a student CURRENTLY profiled with one of
    routers/narration.py's TRACKABLE_STYLES (kinesthetic, reading_writing,
    visual — see that constant's own comment for why auditory isn't
    among them: no honest tool-level signal exists for it, nudge only).
    build_profile creates/resets this row when a profile newly becomes one
    of those three (including switching FROM one trackable style TO a
    different one — the count doesn't carry over) and deletes it the
    moment a resynthesis moves the student off all three. No event log,
    no per-turn timestamps, no narration content — a single running count
    plus the date counting started. What increments it depends on which
    style is active (see ai_service.py's three _increment_behavior_check
    call sites): kinesthetic counts invite_handwriting calls WITH
    `elements` set (a structured DITK task); reading_writing counts
    invite_handwriting calls WITHOUT `elements` (a plain written
    narration); visual counts successfully-resolved show_visual_aid
    calls. profile_enc holds encrypt_json({"count": int}); "since" is a
    plain (non-sensitive) timestamp, left unencrypted like every other
    table's created_at/updated_at column.
    """
    __tablename__ = "learner_behavior_checks"

    student_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    count_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class MasteryProfile(Base):
    """
    Per-student CDM/IRT/KST mastery vector for a subject area (K-8 math
    first — see docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md). profile_enc
    holds encrypt_json({skill_id: probability, ...}) — the plain
    MasteryVector from services.diagnostic.mastery, nothing more (no
    theta/calibration state — that's explicitly deferred, see
    docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md's decisions log). Never
    a transcript, never a raw probe outcome. Composite PK future-proofs
    this same table for reading/ELA/science vectors later (design doc
    §13) without a schema change — subject_area="reading" is a new row,
    not a new table.
    """
    __tablename__ = "mastery_profiles"

    student_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    subject_area: Mapped[str] = mapped_column(String(30), primary_key=True, default="mathematics")
    evidence_count: Mapped[int] = mapped_column(nullable=False, default=0)
    profile_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class DiagnosticEvidenceLog(Base):
    """
    One row per mastery update — ONLY derived deltas (skill_id,
    prior->posterior, probe_id, model_used, timestamp), matching
    services.diagnostic.mastery.MasteryUpdate exactly. Never a
    transcript, never the child's words, never probe prose — the same
    privacy class as NarrationAssessment (derived scores, not raw
    content). Opt-in and off by default
    (settings.diagnostic_evidence_log_enabled) — the strictest reading of
    "never persist raw evidence"; when disabled, only MasteryProfile is
    written and this table stays empty.
    """
    __tablename__ = "diagnostic_evidence_log"

    # BigInteger().with_variant(Integer(), "sqlite"): on Postgres this is a
    # real BIGINT/BIGSERIAL identity column, unchanged from before. Plain
    # BigInteger doesn't get SQLite's "INTEGER PRIMARY KEY" rowid-alias
    # autoincrement (SQLite only special-cases the exact type name
    # "INTEGER") — this table is the one currently exercised by a real
    # insert under a SQLite test engine (see tests/diagnostic's unit 2.2
    # round-trip tests), so it needs the per-dialect variant to actually
    # autoincrement there; Postgres behavior is unaffected either way.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    student_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject_area: Mapped[str] = mapped_column(String(30), nullable=False, default="mathematics")
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    delta_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SessionTranscript(Base):
    """Encrypted full session transcript saved at session end for parent review."""
    __tablename__ = "session_transcripts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    session_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    subjects: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(nullable=False, default=0)
    transcript_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ApiUsageEvent(Base):
    """
    Append-only per-call token usage log — the raw ingredient for both the
    per-student usage card on Progress.tsx and the household-wide total on
    GET /admin/status. Every real Anthropic API call this deployment makes
    (tutoring turns, sandbox turns, session summaries, learner-profile
    synthesis) writes exactly one row here via core/api_usage.py's
    record_usage(), best-effort and never blocking the actual turn — a
    logging hiccup here must not break a child's session.

    This deployment is BYOK (see .env.example's ANTHROPIC_API_KEY) — Bede
    itself is never billed for any of this, the family's own key is.
    Token counts and a model name are not sensitive content (no
    transcript, no prompt text), so — like MasteryProfile.evidence_count —
    these are plain (unencrypted) columns, not AES-256-GCM BYTEA.

    student_name is nullable: the parent sandbox (routers/sandbox.py) has
    no student context at all, so those turns roll into the household
    total only, never onto any specific student's card.
    """
    __tablename__ = "api_usage_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    student_name: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )


class ParentSecurityKey(Base):
    """
    One row per enrolled FIDO2 authenticator (YubiKey or other WebAuthn
    authenticator) for the parent role's optional second factor. Single-family
    app — there's exactly one parent credential, so these all belong to "the
    parent" with no user foreign key needed, same as parent_password itself.

    credential_enc holds the JSON {credential_id, public_key, sign_count,
    transports} (all base64/int — no secrets beyond what the authenticator
    already discloses to any relying party), AES-256-GCM encrypted like every
    other user-data column in this database.
    """
    __tablename__ = "parent_security_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    credential_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ParentTotpConfig(Base):
    """
    Single row (key="totp") holding the parent's TOTP secret once enrolled.
    `confirmed=False` while a freshly generated secret awaits its first
    verifying code — never treated as a valid second factor until confirmed,
    so an abandoned enrollment can't silently weaken login.
    """
    __tablename__ = "parent_totp_config"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ParentCredentialOverride(Base):
    """
    Single row (key="password") that, when present, WINS over the env
    PARENT_PASSWORD — same "DB value wins over env, live, no restart"
    precedence core/license_state.py already established for LICENSE_KEY,
    applied here for the same reason: PARENT_PASSWORD used to live only in
    .env, which made it impossible to actually change from inside the
    running app, forgotten or not. See core/parent_credential.py, the only
    module that reads/writes this table.

    hash/salt (core/credential_hash.py's PBKDF2-HMAC-SHA256, NOT this app's
    usual reversible AES-256-GCM encrypt_json) since a password is a
    verify-only secret — it should never need to be decrypted back to
    plaintext the way, say, a TOTP secret does.

    credentials_version increments on every change and is embedded in every
    parent/parent_pending JWT at issuance (core/deps.py checks it against
    the cached current value on every request) — the mechanism that makes
    "recover access, set a new password" actually END a takeover, not just
    add a new valid session alongside whatever token an attacker already
    holds. See docs/SECURITY.md's "Closed gaps" for the full design.
    """
    __tablename__ = "parent_credential_override"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credentials_version: Mapped[int] = mapped_column(default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ParentRecoveryCode(Base):
    """
    Single row (key="recovery") holding a high-entropy backup code, shown to
    the parent exactly once at enrollment (same "shown once, only the hash
    persists" contract as ParentTotpConfig's secret) — the "something you
    know" leg of the ≥2-of-3 recovery scheme services/parent_recovery.py
    requires to regain access when PARENT_PASSWORD and any authenticator
    are both lost. Hashed like ParentCredentialOverride, for the same
    reason. Deliberately a NEW secret rather than reusing CHILD_PIN or
    PARENT_PASSWORD, so a leak of one doesn't also expose the others.

    Mutually exclusive with ParentRecoveryPin below — a parent chooses ONE
    "something you know" recovery factor at enrollment time (this longer,
    machine-generated code, or the shorter, parent-chosen, memorable PIN),
    not both. services/parent_recovery.py's enroll functions delete the
    other row when one is enrolled, so at most one of the two tables ever
    has a row for "recovery" at a time.
    """
    __tablename__ = "parent_recovery_code"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ParentRecoveryPin(Base):
    """
    Single row (key="recovery") holding a parent-CHOSEN, memorable recovery
    PIN — the favored alternative to ParentRecoveryCode's longer, machine-
    generated code, for a parent who'd rather remember something than
    write down/store a longer secret. Same strength floor as CHILD_PIN/
    DEMO_PIN/SANDBOX_PIN (core/pin_policy.py's pin_is_strong(), enforced at
    enrollment in services/parent_recovery.py), not a separate, weaker rule
    set — a memorable PIN still has to clear the same "not an obviously
    guessable pattern" bar every other PIN in this app does.

    Mutually exclusive with ParentRecoveryCode above — see that model's
    own docstring for the "at most one row across both tables" contract.
    A separate table rather than a `kind` column added to
    ParentRecoveryCode specifically because this app has no migration
    tooling (core/database.py's create_tables() is CREATE TABLE IF NOT
    EXISTS only) — a new table is safe for an already-deployed instance
    in a way that adding a column to an existing one isn't.
    """
    __tablename__ = "parent_recovery_pin"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ParentLoginLockout(Base):
    """
    Single row (key="parent") tracking consecutive PARENT_PASSWORD
    failures for account-lockout purposes. Role-scoped, not per-IP —
    unlike core/middleware.py's RateLimitMiddleware, which is deliberately
    per-IP (a shared LAN/conference-room IP shouldn't share one budget) —
    because this app has exactly one parent identity, so an attacker
    spreading attempts across IPs should still trip a role-scoped lockout
    even though each IP individually stays under the rate limiter's
    threshold.

    DB-backed rather than the in-memory pattern core/audit.py's anomaly
    watch and RateLimitMiddleware use (docs/SECURITY.md's "Known open
    gaps" already discloses that in-memory limitation for those) —
    specifically because a lockout that silently resets on every container
    restart isn't a real lockout.
    """
    __tablename__ = "parent_login_lockout"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    failure_count: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class DemoCodeSession(Base):
    """
    Postgres-backed replacement for core/demo_code_session.py's old
    in-memory `_codes` dict — the single per-code store backing the entire
    public demo (POST /auth/demo-code, POST /auth/login role=demo_code).
    Moving this here means an in-flight demo/diagnostic session survives a
    backend restart or redeploy, not just the JWT's own device-fingerprint
    binding — a lost tab or a network blip was already recoverable (the
    code/JWT still worked); a restart wasn't, since the whole store lived
    in one process's memory.

    student_name/grade stay plaintext, matching the existing convention
    for the analogous columns on StudentConfig/MasteryProfile (a lookup
    key, not encrypted "data") — a self-chosen demo alias, not a real
    family's identity. mastery_vector_enc is the one field that holds
    anything resembling the mastery.MasteryVector shape a real session's
    MasteryProfile.profile_enc would, so it's encrypted the same way for
    consistency, even though a demo vector never touches that table.

    No separate TTL/expiry column — core/demo_code_session.py enforces
    _CODE_TTL_SECONDS the same way the old in-memory version did (filter
    on created_at at read/write time), just against a query instead of a
    dict comprehension.
    """
    __tablename__ = "demo_code_sessions"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    message_count: Mapped[int] = mapped_column(nullable=False, default=0)
    redeemed: Mapped[bool] = mapped_column(nullable=False, default=False)
    student_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    mastery_vector_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    mastery_evidence_count: Mapped[int] = mapped_column(nullable=False, default=0)
    email_sent: Mapped[bool] = mapped_column(nullable=False, default=False)


class DiagnosticPreviewUse(Base):
    """
    Postgres-backed replacement for core/diagnostic_preview_quota.py's old
    in-memory `_usage` dict — one row per distinct (ip, code) pair a
    visitor has opened the diagnostic preview for, within that module's
    rolling window.

    ip_hash, not ip: moving this off an ephemeral in-memory dict (wiped on
    every restart, never touched disk) onto a durable Postgres row is a
    real, new increase in exposure for a raw visitor IP specifically — a
    plaintext column would sit there indefinitely, readable by anyone with
    DB access, in a way the old dict never did. A keyed HMAC-SHA256 of the
    IP (core.diagnostic_preview_quota._hash_ip, keyed on settings.secret_key)
    stays exactly as equality-filterable in a WHERE clause as plaintext
    would (same input always hashes the same), while being unreversible —
    a DB compromise gets a set of opaque per-visitor tokens, not their
    actual IP addresses. AES-256-GCM (this app's usual encrypt-at-rest,
    e.g. MasteryProfile.profile_enc) isn't an option here specifically
    because its random-nonce-per-call design makes it non-equality-
    filterable; a keyed hash is the standard tool for "must stay
    queryable, must not be reversible."
    """
    __tablename__ = "diagnostic_preview_uses"
    __table_args__ = (
        # record_use() already checks-then-inserts to stay idempotent per
        # (ip_hash, code), but that check isn't atomic with the insert — two
        # concurrent record_use calls for the same brand-new (ip, code) pair
        # could both pass the check and both insert. A duplicate row there
        # is harmless on its own (has_quota reads distinct codes into a
        # set), but the constraint closes the race outright rather than
        # relying on that being true forever; core.diagnostic_preview_quota
        # treats a violation as "someone else already recorded this" and
        # swallows it.
        UniqueConstraint("ip_hash", "code", name="uq_diagnostic_preview_uses_ip_hash_code"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    ip_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )


class DemoInteractionSignal(Base):
    """
    Aggregated, anonymized structural interaction patterns from demo
    sessions only (never parent/child production sessions) — e.g. which
    tools fired how often, turn counts, subject completions. Never a
    transcript, never the child's or the model's actual words; the same
    "derived signal, not raw content" privacy class as
    DiagnosticEvidenceLog/NarrationAssessment, encrypted the same way.

    session_token (not the demo code itself) is a keyed HMAC-SHA256 of the
    code, matching DiagnosticPreviewUse.ip_hash's exact reasoning: stays
    equality-filterable (the same code always hashes the same, so counts
    accumulate correctly across calls within one session) while being
    unreversible — a DB compromise gets an opaque per-session token, not
    the original code, and can't be joined back to DemoCodeSession's
    optional student_name/grade columns. See services/interaction_signals.py.

    Retained on its own schedule (see that module's purge_old_signals),
    independent of DemoCodeSession's much shorter TTL — this table exists
    specifically to survive past a single session's lifetime so patterns
    can be aggregated across many sessions later, by
    scripts/export_interaction_signals.py.
    """
    __tablename__ = "demo_interaction_signals"

    session_token: Mapped[str] = mapped_column(String(64), primary_key=True)
    signals_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


async def create_tables() -> None:
    """Idempotent table creation — safe to call on every startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session
