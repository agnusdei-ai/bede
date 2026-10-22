"""Real SQLite database tests for additive curriculum persistence."""
import pytest
from sqlalchemy import inspect, insert, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from services.curriculum.persistence import (
    create_curriculum_tables, metadata, reviews, lessons, variants,
)


@pytest.mark.asyncio
async def test_disabled_creates_no_tables(monkeypatch):
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        assert await create_curriculum_tables(engine) is False
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda c: inspect(c).get_table_names())
        assert not any(name.startswith("curriculum_") for name in names)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_additive_idempotent_and_campus_scoped(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "true")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("CREATE TABLE existing_record (id INTEGER PRIMARY KEY)")
        assert await create_curriculum_tables(engine)
        assert await create_curriculum_tables(engine)
        async with engine.begin() as connection:
            names = await connection.run_sync(lambda c: set(inspect(c).get_table_names()))
            assert "existing_record" in names
            assert {table.name for table in metadata.tables.values()} <= names
            await connection.execute(insert(reviews), [
                dict(campus_id=campus, review_id="r1", item_id="l1", item_version=1,
                     reviewed_by="educator-1", reviewed_at=__import__("datetime").datetime(2026, 1, 1),
                     decision="approve") for campus in ("campus-a", "campus-b")
            ])
            await connection.execute(insert(lessons), [
                dict(campus_id=campus, lesson_id="l1", version=1,
                     owner_educator_id="educator-1", visibility="campus",
                     status="approved", generated=0, rights_status="original",
                     review_id="r1", body_enc=b"synthetic-ciphertext")
                for campus in ("campus-a", "campus-b")
            ])
            result = (await connection.execute(
                select(lessons.c.campus_id).where(lessons.c.campus_id == "campus-a")
            )).scalars().all()
            assert result == ["campus-a"]
            assert "variant_enc" in variants.c
            assert "evidence_refs_enc" in variants.c
    finally:
        await engine.dispose()
