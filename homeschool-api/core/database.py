"""
Async SQLAlchemy setup targeting Neon (or any PostgreSQL provider).

Tables carry no plaintext — every BYTEA column that holds user data is
AES-256-GCM encrypted by core/encryption.py before it reaches the driver.

Startup sequence (main.py lifespan):
  1. create_tables()          — idempotent CREATE TABLE IF NOT EXISTS
  2. initialize_encryption()  — reads/writes encryption_config rows
"""

from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy import BigInteger, DateTime, LargeBinary, String
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.config import settings


def _build_engine():
    url = settings.database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Provide a postgresql+asyncpg://... connection string."
        )
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


async def create_tables() -> None:
    """Idempotent table creation — safe to call on every startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session
