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


class StudentKey(Base):
    """One random data key per student, wrapped under DATA_KEY.

    Every encrypted column belonging to a student is encrypted under their
    key rather than DATA_KEY directly, so destroying this single row
    crypto-shreds all of their stored data at once — live rows, dead tuples
    awaiting VACUUM, WAL segments, and every backup taken while the key
    existed. See core/student_keys.py for the full reasoning, and
    docs/DATA_CLASSIFICATION.md for how it fits the tier model.

    Deliberately NOT cascaded by a foreign key: services/student_deletion.py
    destroys the key explicitly in the same transaction as the row deletes,
    so the ordering and the failure mode are visible in code rather than
    implied by schema."""
    __tablename__ = "student_keys"

    student_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PrivilegedElevation(Base):
    """A time-boxed grant of management-plane privilege to one session.

    P8: being logged in as the parent is the ordinary account identity;
    doing something on the management plane (reading the audit log,
    repointing the AI provider, weakening MFA, crypto-shredding a student)
    additionally requires an explicit, recent re-authentication. This row is
    that grant.

    Keyed on the token's `jti`, so the grant belongs to one session rather
    than to "the parent" — a second device logged in at the same time does
    not inherit it.

    Deliberately in the database rather than in process memory, and this is
    the point rather than an implementation detail: an in-memory grant would
    be invisible to sibling replicas, so the same session would be elevated
    on the replica that granted it and not on the next one a load balancer
    picked. The failure mode is worse than it sounds — an operator would see
    privileged actions intermittently rejected and reasonably conclude the
    step-up was broken, and the natural fix (make it sticky) is worse than
    the bug. See docs/DEPLOYMENT_TOPOLOGY.md."""
    __tablename__ = "privileged_elevations"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class DeviceRecord(Base):
    """P9 (docs/ARCHITECTURE_PRINCIPLES.md), Option C from
    docs/DEVICE_IDENTITY_DESIGN.md — a REVOCATION mechanism, deliberately not
    a cryptographic identity. `device_id` is a UUID the browser generates
    once and persists in localStorage (not sessionStorage — it must survive
    a closed tab/browser restart, since it identifies the physical device
    rather than one login), sent at `POST /auth/login` and embedded as a
    JWT claim from then on.

    THE PROPERTY THIS BUYS: "revoke that lost tablet" becomes real. Before
    this, the only levers were changing PARENT_PASSWORD or CHILD_PIN, both
    of which sign out the WHOLE family. core/deps.py's per-request check
    against core/device_registry.py's cached revoked set means a revoked
    device stops working on its very next request, not just at its next
    login — the same "next-request, not immediate" trade
    core/parent_credential.py's credentials_version already makes, for the
    same multi-replica-staleness reason (see that module's docstring).

    THE PROPERTY THIS DOES NOT BUY: `device_id` is client-asserted, not
    cryptographically proven — an attacker who steals a token gets its
    device_id too, so this defends against a KNOWN-lost device (a parent
    revoking the tablet they know is missing), not an attacker impersonating
    a device that was never reported lost. A genuine per-device keypair
    (docs/DEVICE_IDENTITY_DESIGN.md's Option A) is the deferred, harder
    follow-up for the parent role specifically — still not built, and
    deliberately so; see that document's own "Why Option A stopped here".

    Deliberately NOT role-scoped: one physical tablet is commonly used by
    both the parent (setting up the day) and a child (the lesson itself),
    so `last_role`/`last_seen_at` are simply overwritten by whichever login
    happens most recently, rather than the table carrying one row per
    (device, role) pair.

    No separate "who revoked this" column: a device can only ever be
    revoked by an elevated parent (`core/deps.py`'s `require_elevated_parent`
    — this is a single-tenant app, so there is exactly one identity that
    could), and that action is already durably recorded independently of
    this table, in the encrypted audit log (`AuditEvent.DEVICE_REVOKED`,
    `core/audit.py`) — the same place every other security-relevant action
    in this app is recorded, rather than duplicating a narrower copy here.
    """
    __tablename__ = "device_records"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    # 'parent' | 'child' — whichever role most recently logged in from this
    # device. Not encrypted: no more sensitive than AuditLog's own role
    # column, and this table exists specifically to be listed back to the
    # parent in plain form.
    last_role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Truncated — this is a display label ("Safari on iPad"), not a forensic
    # record; AuditLog is where a full audit trail already lives.
    last_user_agent: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


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

    # BigInteger().with_variant(Integer(), "sqlite"): on Postgres this is a
    # real BIGINT/BIGSERIAL identity column, unchanged from before. Plain
    # BigInteger doesn't get SQLite's "INTEGER PRIMARY KEY" rowid-alias
    # autoincrement (SQLite only special-cases the exact type name
    # "INTEGER") — see DiagnosticEvidenceLog's own comment on this exact
    # issue below; this table just hadn't been exercised by a real insert
    # under a SQLite test engine until tests/test_assess_narration.py did.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
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


class LessonBookmark(Base):
    """
    Where a student left off in ONE subject, as of the end of their last
    session — the piece that lets a new day pick a lesson back up mid-
    thread instead of restarting cold, regardless of what topic the parent
    happens to have typed into SessionConfig.lesson_focus/current_unit
    today (see CLAUDE.md's "Lesson continuity (bookmarks)" section).

    Deliberately internal-only, never surfaced in the parent UI: this is
    NOT a tracked signal like LearnerBehaviorCheck's per-style counters —
    there's nothing here to measure or score, just a short factual resume
    point Bede reads back into its own prompt. The same "no black-box
    signal about my kid" instinct that shaped LearnerBehaviorCheck and the
    phonics/language check-ins argues for the opposite conclusion here:
    the note is plain prose, generated by the same model the parent
    already trusts to write their session summary, and the parent's own
    lesson_focus/current_unit always outranks it (see
    services/ai_service.py's _bookmark_note) — there is no separate
    metric being computed about the child, so there is nothing to hide OR
    to expose. bookmark_enc holds encrypt_json({"note": str}); note is a
    1-2 sentence factual resume point ("We were partway through the fall
    of Rome; the child had identified the frontier problem but hadn't
    reached the economic factors yet."), never a suggestion or judgment.
    updated_at drives the "fade" behavior in _bookmark_note: an old
    bookmark is phrased as "a while back" rather than "last time" instead
    of ever being deleted outright — a lapsed family should never feel
    like Bede silently lost their place.
    """
    __tablename__ = "lesson_bookmarks"

    student_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    subject: Mapped[str] = mapped_column(String(50), primary_key=True)
    bookmark_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
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
    content).

    Governed by settings.diagnostic_evidence_log_enabled, which is ON by
    default. This docstring previously said "opt-in and off by default",
    which was true only for Phases 1-4: the flag was flipped to True once
    the end-of-session "Math Skill Growth" before/after report
    (services.diagnostic.get_session_growth) needed real deltas to read
    back — see docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md §5.3, which
    records that change. The stale wording mattered more than a typo
    normally would: a deployer reading this model to decide what their
    database holds would have concluded nothing was written here.

    Turning the flag off is still supported and is the strictest reading
    of privacy constraint P3 — when disabled, only MasteryProfile is
    written, this table stays empty, and session summaries omit skill
    growth entirely rather than reporting it from nothing.
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


class SkillActivityLog(Base):
    """
    An append-only record of WORK ACTUALLY DONE — one row per completed
    learning activity, per student, per skill.

    DELIBERATELY NOT PSYCHOMETRIC, and that is the whole point of it
    existing alongside MasteryProfile rather than inside it. MasteryProfile
    and DiagnosticEvidenceLog hold inferred latent ability: "this child has
    a 0.47 probability of having mastered multi-digit multiplication" — a
    claim ABOUT THE CHILD. This table holds only what happened: "on this
    date, in Mathematics, a multi-digit multiplication task was completed
    unaided." A parent reads facts and draws their own conclusion; nothing
    here classifies the child, ranks them, or estimates a trait they carry.

    That distinction is what makes this table safe to read across a pod.
    "Who has done this work" is an ordinary thing for a self-managed team
    to know and is how one member comes to help another; "who is better at
    this" is a ranking of children, which this project does not build (see
    CLAUDE.md's standing constraint). A completion count can support the
    first without ever producing the second, because it never aggregates
    into a score.

    `detail_enc` holds encrypt_json({"skill_id", "label", "assistance",
    "subject"}) — the same derived-not-raw privacy class as
    NarrationAssessment and DiagnosticEvidenceLog. Never the child's words,
    never a transcript, never the task's prose.

    `assistance` is the only qualitative field, and it is factual rather
    than evaluative: unaided / with_a_hint / with_help. It records how the
    work went, not how able the child is.
    """
    __tablename__ = "skill_activity_log"

    # Same BigInteger-with-SQLite-variant reasoning as
    # DiagnosticEvidenceLog above — this table is exercised by real inserts
    # under the SQLite test engine and needs the variant to autoincrement.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    student_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject_area: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    detail_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
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


class DemoCodeUnitNote(Base):
    """
    Optional, parent-provided one-line note on what the family is already
    covering outside Bede's own built-in curriculum (a book, a unit) — set
    once at POST /auth/demo-code alongside student_name/grade, and threaded
    into the demo's SessionConfig.current_unit exactly like a real parent's
    current_unit field (see docs/PARENT_SETUP.md's companion_mode section).
    This lets the demo show the same "Bede anchors on what the family
    brought in, not just its own curriculum" behavior the real app offers,
    rather than only ever demonstrating Bede's bundled subject content. See
    CLAUDE.md's "Continuing Mastery (demo)" section.

    A standalone table rather than a new column on DemoCodeSession: this
    codebase's startup only ever runs CREATE TABLE IF NOT EXISTS (core/
    database.py's create_tables(), no ALTER TABLE migration path), so a new
    table is the only way to add this to an already-running deployment
    without a manual schema change.

    Same TTL/eviction convention as DemoCodeSession: no expiry column,
    core/demo_code_session.py filters on created_at at read/write time and
    opportunistically deletes rows past the same cutoff. Plaintext, not
    encrypted — same convention as DemoCodeSession's own student_name/grade
    (a demo topic, not a real family's identity); sanitized (HTML/prompt-
    injection/credential stripping) both at write time (routers/auth.py)
    and again by _build_subject_prompt's existing current_unit handling
    (services/ai_service.py), for defense in depth on public, anonymous
    input.
    """
    __tablename__ = "demo_code_unit_notes"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    note: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )


class DemoCodeFaithNote(Base):
    """
    Optional, parent-provided label for the visiting family's own church
    tradition (e.g. "Baptist", "Catholic", "Non-denominational") — set once
    at POST /auth/demo-code alongside student_name/current_unit, and
    threaded into the demo's SessionConfig.faith_tradition exactly like
    DemoCodeUnitNote does for current_unit.

    Exists because the demo deliberately shows every subject
    (routers/tutor.py's _demo_session_config: `subjects=list(Subject)`),
    including both Scripture & Bible Study and Saints & Catechism side by
    side, regardless of the visitor's own background — unlike a real
    family, who simply enables whichever of those two modules fits their
    own church (see CLAUDE.md's Subject enum comments). This lets Bede
    frame that content consistently with the family's own tradition
    (services/ai_service.py's _faith_tradition_note) instead of assuming
    one, without hiding either module from the demo's curriculum showcase.

    Standalone table for the same reason as DemoCodeUnitNote: this
    codebase's startup only ever runs CREATE TABLE IF NOT EXISTS (no ALTER
    TABLE path), so a new table is the only way to add this to an
    already-running deployment. Same TTL/eviction convention as
    DemoCodeUnitNote: no expiry column, core/demo_code_session.py filters
    on created_at at read/write time and opportunistically deletes rows
    past the same cutoff. Plaintext, not encrypted — a self-described
    tradition, not a real family's identity, same convention as
    DemoCodeSession's own student_name/grade; sanitized both at write time
    (routers/auth.py) and again by _build_subject_prompt's handling
    (services/ai_service.py).
    """
    __tablename__ = "demo_code_faith_notes"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    tradition: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )


class DemoCodeActivityLog(Base):
    """
    The public demo's own work ledger — what the visitor actually finished
    during this one demo session.

    DELIBERATELY NOT SkillActivityLog, and the difference is the whole
    point. That table is a permanent, per-student record a family builds
    over months; this one lives exactly as long as the demo code does and
    is gone the moment it expires or the visitor logs out. A demo visitor
    is anonymous and their `student_name` is whatever they typed at the
    code screen, so it is not isolated from a real family's — writing them
    into the same table would be both a broken promise and a collision.

    WHY THIS IS COMPATIBLE WITH "your conversation is never stored". What
    is kept here is derived and structural, in exactly the category the
    consent screen already carves out: which skill was worked, how much
    help it took, and what Bede noticed about the work. Never the child's
    words, never a transcript, never the task's prose — the same
    derived-not-raw class as DemoCodeSession.mastery_vector_enc beside it,
    encrypted for the same reason and evicted on the same schedule.

    ONE ROW PER CODE, not one per activity: `activities_enc` holds an
    encrypted JSON list, appended to under read-modify-write. A demo
    session produces a few dozen entries at most, so the simpler shape
    wins — and it keeps eviction to a single DELETE alongside
    DemoCodeUnitNote/DemoCodeFaithNote rather than a range scan.
    core/demo_code_session.py caps the list length.

    Standalone table for the same reason as those two siblings: startup
    only ever runs CREATE TABLE IF NOT EXISTS (no ALTER TABLE path), so a
    new table is the only way to ship this to an already-running
    deployment. Same TTL/eviction convention as well — no expiry column,
    core/demo_code_session.py filters on created_at at read time and
    deletes past the same cutoff.
    """
    __tablename__ = "demo_code_activity_logs"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    activities_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )


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


class AIProviderOverride(Base):
    """
    Up to two rows (key="primary", key="secondary") that, when present,
    pick which already-CONFIGURED AI adapters (services/adapters/) serve
    as primary and, optionally, the first failover tried if primary errors
    — same "DB value wins over the env default, live, no restart"
    precedent core/license_state.py and core/parent_credential.py already
    established for LICENSE_KEY/PARENT_PASSWORD, applied here to
    BEDE_ADAPTER_ORDER/BEDE_FORCE_ADAPTER (core/config.py) for the same
    reason: those are plain env-loaded Settings read once at process
    startup, so switching providers (e.g. a degraded local Ollama model,
    want Mistral instead, or picking Claude over Mistral as backup) used
    to mean an .env edit and a restart. See core/provider_state.py, the
    only module that reads/writes this table, and services/adapters/
    router.py's FailoverClient, which consults the in-process cache on
    every request. `key` was always a String primary key rather than a
    hardcoded singleton specifically so a second row could be added later
    without a schema change — this is that second row.

    Deliberately narrow: this table only ever stores the NAME of an adapter
    that is already configured elsewhere (real credentials in
    settings/.env) — never a credential itself. routers/admin.py rejects
    picking a provider with no credentials configured before it ever
    reaches this table, and services/adapters/router.py's
    provider_state.effective_order() silently ignores a stored name that
    is no longer configured, unknown, or (for secondary) identical to
    primary (falls back to the env order for that slot) rather than
    breaking service.
    """
    __tablename__ = "ai_provider_override"

    key: Mapped[str] = mapped_column(String(20), primary_key=True, default="primary")
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
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
