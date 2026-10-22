"""Opt-in additive curriculum storage. No imports from application startup.

The caller must explicitly invoke create_curriculum_tables after enabling the
feature. Learner variant payloads are ciphertext produced by the existing
student-scoped encryption layer; this module never stores plaintext scores.
"""
from __future__ import annotations

from sqlalchemy import (
    Column, DateTime, ForeignKeyConstraint, Integer, LargeBinary, MetaData,
    String, Table, UniqueConstraint,
)

from services.curriculum.flag import curriculum_engine_enabled

metadata = MetaData()

sources = Table(
    "curriculum_sources", metadata,
    Column("campus_id", String(36), primary_key=True),
    Column("source_id", String(100), primary_key=True),
    Column("edition", String(200), nullable=False),
    Column("source_url", String(2048), nullable=False),
    Column("content_hash", String(128), nullable=False),
    Column("rights_status", String(40), nullable=False),
    Column("rights_verified_by", String(100)),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
)

reviews = Table(
    "curriculum_reviews", metadata,
    Column("campus_id", String(36), primary_key=True),
    Column("review_id", String(100), primary_key=True),
    Column("item_id", String(100), nullable=False),
    Column("item_version", Integer, nullable=False),
    Column("reviewed_by", String(100), nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    Column("decision", String(30), nullable=False),
    Column("notes_enc", LargeBinary),
)

lessons = Table(
    "curriculum_lessons", metadata,
    Column("campus_id", String(36), primary_key=True),
    Column("lesson_id", String(100), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("owner_educator_id", String(100), nullable=False),
    Column("visibility", String(30), nullable=False),
    Column("status", String(30), nullable=False),
    Column("generated", Integer, nullable=False),
    Column("rights_status", String(40), nullable=False),
    Column("review_id", String(100)),
    Column("body_enc", LargeBinary, nullable=False),
    ForeignKeyConstraint(["campus_id", "review_id"],
                         ["curriculum_reviews.campus_id", "curriculum_reviews.review_id"]),
)

chunks = Table(
    "curriculum_chunks", metadata,
    Column("campus_id", String(36), primary_key=True),
    Column("chunk_id", String(100), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("source_id", String(100), nullable=False),
    Column("visibility", String(30), nullable=False),
    Column("status", String(30), nullable=False),
    Column("rights_status", String(40), nullable=False),
    Column("review_id", String(100)),
    Column("body_enc", LargeBinary, nullable=False),
    ForeignKeyConstraint(["campus_id", "source_id"],
                         ["curriculum_sources.campus_id", "curriculum_sources.source_id"]),
    ForeignKeyConstraint(["campus_id", "review_id"],
                         ["curriculum_reviews.campus_id", "curriculum_reviews.review_id"]),
)

variants = Table(
    "curriculum_variants", metadata,
    Column("campus_id", String(36), primary_key=True),
    Column("variant_id", String(100), primary_key=True),
    Column("parent_lesson_id", String(100), nullable=False),
    Column("parent_version", Integer, nullable=False),
    Column("learner_ref", String(100), nullable=False),
    Column("evidence_refs_enc", LargeBinary, nullable=False),
    Column("variant_enc", LargeBinary, nullable=False),
    Column("refresh_after", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(["campus_id", "parent_lesson_id", "parent_version"],
                         ["curriculum_lessons.campus_id", "curriculum_lessons.lesson_id",
                          "curriculum_lessons.version"]),
)


async def create_curriculum_tables(engine) -> bool:
    """Create only new curriculum tables; no DDL when disabled."""
    if not curriculum_engine_enabled():
        return False
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all, checkfirst=True)
    return True
