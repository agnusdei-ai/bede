"""
Real check for Diagnostic build-loop unit 2.1 (MasteryProfile +
DiagnosticEvidenceLog ORM + config flag) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md.

No live Postgres is available in this sandbox (docker CLI present, no
daemon running) — that's a real sandbox limitation, not something this
test papers over. What IS verified here is real, not mocked: the actual
SQLAlchemy declarative models, registered on the actual Base.metadata
used by core.database.create_tables(), executed against a real (if
throwaway, in-memory SQLite) database engine via Base.metadata.create_all
— proving the table/column definitions are structurally valid SQL, not
just importable Python. What this does NOT prove: Postgres/asyncpg-
specific behavior, or that create_tables()'s actual asyncpg engine
accepts them (unit 2.2's round-trip test targets that, with the same
caveat).
"""

from sqlalchemy import LargeBinary, create_engine, inspect

from core.config import settings
from core.database import Base, DiagnosticEvidenceLog, MasteryProfile


def test_diagnostic_evidence_log_disabled_by_default():
    assert settings.diagnostic_evidence_log_enabled is False


def test_mastery_profile_table_name_and_composite_primary_key():
    assert MasteryProfile.__tablename__ == "mastery_profiles"
    pk_columns = {col.name for col in MasteryProfile.__table__.primary_key.columns}
    assert pk_columns == {"student_name", "subject_area"}


def test_diagnostic_evidence_log_table_name_and_primary_key():
    assert DiagnosticEvidenceLog.__tablename__ == "diagnostic_evidence_log"
    pk_columns = {col.name for col in DiagnosticEvidenceLog.__table__.primary_key.columns}
    assert pk_columns == {"id"}


def test_encrypted_columns_are_largebinary_not_plaintext_string():
    """The whole point of every _enc column: never a plaintext String type
    that could tempt someone into storing unencrypted data by accident."""
    assert isinstance(MasteryProfile.__table__.c.profile_enc.type, LargeBinary)
    assert isinstance(DiagnosticEvidenceLog.__table__.c.delta_enc.type, LargeBinary)


def test_mastery_profile_defaults():
    assert MasteryProfile.__table__.c.evidence_count.default.arg == 0
    assert MasteryProfile.__table__.c.subject_area.default.arg == "mathematics"


def test_diagnostic_evidence_log_defaults():
    assert DiagnosticEvidenceLog.__table__.c.subject_area.default.arg == "mathematics"
    assert callable(DiagnosticEvidenceLog.__table__.c.observed_at.default.arg)
    assert callable(DiagnosticEvidenceLog.__table__.c.created_at.default.arg)


def test_registered_on_the_real_base_used_by_create_tables():
    """Confirms these models are on THE SAME Base.metadata create_tables()
    calls Base.metadata.create_all() against — not a parallel/shadow
    metadata that would silently never get created in production."""
    assert "mastery_profiles" in Base.metadata.tables
    assert "diagnostic_evidence_log" in Base.metadata.tables


def test_create_all_succeeds_against_a_real_sqlite_engine():
    """Structural validation with a real (throwaway) database engine — not
    a live Postgres (unavailable in this sandbox), but a genuine SQL
    DDL execution proving the column/constraint definitions are valid,
    not just valid Python."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    table_names = set(inspect(engine).get_table_names())
    assert "mastery_profiles" in table_names
    assert "diagnostic_evidence_log" in table_names
