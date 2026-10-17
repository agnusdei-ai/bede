"""G2 decision guarantees #604's original suite did not prove.

Three properties #604's suite does not yet prove, each using a durable
engine with separate sessions rather than one shared in-memory session:

* restart: a decision and its audit chain survive disposing the engine and
  reloading key material, as a process restart would;
* concurrency: two sessions deciding the same recommendation at once
  produce exactly one decision and one ledger entry;
* atomicity: if the audit write fails after the status update, neither
  survives (checked from a fresh session, as production's get_db would).

Synthetic campuses and learners only. Set G2_GAP_DB_URL to a
postgresql+asyncpg URL to run against Postgres; default is file SQLite.
"""
import asyncio
import os
import tempfile

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import core.encryption as encryption_module
import routers.pilot_journey as journey
from core.config import settings
from core.database import Base
from core.encryption import initialize_encryption
from core.pilot_journey_models import PilotDecision, PilotRecommendation
from routers.pilot_journey import (DecisionInput, authorized_instruction,
                                   decide, decision_ledger)
from tests.test_valor_pilot_g2_journey import (evidence_and_recommendation,
                                               token, two_campuses)

URL = os.environ.get("G2_GAP_DB_URL") or f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/g2.sqlite"


def _engine():
    return create_async_engine(URL, pool_pre_ping=True)


@pytest_asyncio.fixture
async def durable(monkeypatch):
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(encryption_module, "_DATA_KEY", None)
    engine = _engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await initialize_encryption(settings.master_secret, s)
        ta, tb, a, b, la, lb = await two_campuses(s)
        tok, ev, rec = await evidence_and_recommendation(s, ta, la)
    yield {"engine": engine, "factory": factory, "tok": tok, "la": la,
           "rid": rec["recommendation_id"], "proposal": rec["proposal"], "ta": ta}
    await engine.dispose()


@pytest.mark.asyncio
async def test_restart_preserves_decision_and_audit_chain(durable, monkeypatch):
    d = durable
    async with d["factory"]() as s:
        await decide(d["la"], d["rid"], DecisionInput(action="approve", expected_version=1),
                     auth=d["tok"], db=s)
    await d["engine"].dispose()

    # "Restart": new engine, key material reloaded from the database.
    monkeypatch.setattr(encryption_module, "_DATA_KEY", None)
    engine2 = _engine()
    factory2 = async_sessionmaker(engine2, expire_on_commit=False)
    try:
        async with factory2() as s:
            await initialize_encryption(settings.master_secret, s)
            ledger = await decision_ledger(d["la"], auth=d["tok"], db=s)
            assert ledger["chain_valid"] is True
            assert [e["action"] for e in ledger["entries"]] == ["approve"]
            inst = await authorized_instruction(d["la"], auth=d["tok"], db=s)
            assert inst["authorized_instruction"] == d["proposal"]
            # And replay after restart is still refused.
            with pytest.raises(HTTPException) as exc:
                await decide(d["la"], d["rid"], DecisionInput(action="approve", expected_version=1),
                             auth=d["tok"], db=s)
            assert exc.value.status_code == 409
    finally:
        await engine2.dispose()


@pytest.mark.asyncio
async def test_concurrent_decisions_produce_exactly_one(durable):
    d = durable

    async def attempt(action):
        async with d["factory"]() as s:
            try:
                await decide(d["la"], d["rid"], DecisionInput(action=action, expected_version=1),
                             auth=d["tok"], db=s)
                return 200
            except HTTPException as e:
                return e.status_code

    codes = sorted(await asyncio.gather(attempt("approve"), attempt("reject")))
    assert codes == [200, 409], codes
    async with d["factory"]() as s:
        rows = (await s.execute(select(PilotDecision))).scalars().all()
        rec = await s.get(PilotRecommendation, d["rid"])
    assert len(rows) == 1
    assert rec.version == 2 and rec.status in ("approved", "rejected")
    assert rows[0].action == {"approved": "approve", "rejected": "reject"}[rec.status]


@pytest.mark.asyncio
async def test_failed_audit_write_leaves_no_decision(durable, monkeypatch):
    d = durable
    real = journey.entry_hash

    def boom(*a, **k):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(journey, "entry_hash", boom)
    async with d["factory"]() as s:
        with pytest.raises(RuntimeError):
            await decide(d["la"], d["rid"], DecisionInput(action="approve", expected_version=1),
                         auth=d["tok"], db=s)
    monkeypatch.setattr(journey, "entry_hash", real)

    async with d["factory"]() as s:  # fresh session, as get_db would give
        rec = await s.get(PilotRecommendation, d["rid"])
        rows = (await s.execute(select(PilotDecision))).scalars().all()
    assert rec.status == "pending" and rec.version == 1
    assert rows == []
