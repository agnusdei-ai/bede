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
from sqlalchemy import BigInteger, DateTime, Integer, LargeBinary, String, UniqueConstraint
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


class AuditLog(Base):
    """One AES-GCM-encrypted record per audit event."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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


async def create_tables() -> None:
    """Idempotent table creation — safe to call on every startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session
