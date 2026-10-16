"""Owner-led pilot flows: campus/learner selection and learner deletion.

These tests prove the mechanics on synthetic campuses (#598 fixtures:
Synthetic Campus/Teacher/Learner One and Two, "Example Learner"). They are
not pilot evidence; the owner performs deletion on the real build and keeps
the receipt.

No session plan or session launch exists here, on purpose: Owner Decision 7
keeps delivery of approved instruction unavailable until #585.
"""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from starlette.requests import Request

import routers.pilot_owner as owner
from core.database import Base, ClassicalEducator, PilotLearner
from core.pilot_journey_models import PilotDeletionReceipt
from routers.pilot_journey import DecisionInput, decide, record_evidence, request_recommendation
from routers.pilot_owner import (
    LEARNER_TABLES, DeletionConfirm, delete_learner, list_campuses,
    list_learners, list_receipts,
)
from test_valor_pilot_g2_journey import ADMIN, db, dibels, token, two_campuses  # noqa: F401

PASSWORD_ONLY = {"role": "parent", "auth_method": "password"}


def req():
    return Request({"type": "http", "client": ("127.0.0.1", 1),
                    "headers": [(b"user-agent", b"pytest")]})


async def _populated(db):
    """Two campuses, each with a same-named learner carrying evidence, a
    decided recommendation and a decision-ledger entry."""
    ta, tb, a, b, la, lb = await two_campuses(db)
    for learner, teacher in ((la, ta), (lb, tb)):
        tok = await token(db, teacher)
        await record_evidence(learner, dibels(), auth=tok, db=db)
        rec = await request_recommendation(learner, auth=tok, db=db)
        await decide(learner, rec["recommendation_id"],
                     DecisionInput(action="approve", expected_version=1), auth=tok, db=db)
    return ta, tb, a, b, la, lb


def _confirm(learner_id, name="Example Learner"):
    return DeletionConfirm(confirm_learner_id=learner_id, confirm_display_name=name)


# ── Selection ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_selection_requires_the_owners_passkey(db):
    _, _, a, _, _, _ = await two_campuses(db)
    for call in (lambda: list_campuses(auth=PASSWORD_ONLY, db=db),
                 lambda: list_learners(a, auth=PASSWORD_ONLY, db=db),
                 lambda: list_receipts(auth=PASSWORD_ONLY, db=db)):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_selection_lists_campuses_and_only_that_campus_learners(db):
    _, _, a, b, la, lb = await two_campuses(db)
    campuses = await list_campuses(auth=ADMIN, db=db)
    assert {c["campus_id"] for c in campuses} == {a, b}
    listed = await list_learners(a, auth=ADMIN, db=db)
    assert [r["learner_id"] for r in listed] == [la]
    assert listed[0]["display_name"] == "Example Learner"
    with pytest.raises(HTTPException) as exc:
        await list_learners("not-a-uuid", auth=ADMIN, db=db)
    assert exc.value.status_code == 404


# ── Deletion ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deletion_needs_passkey_and_exact_confirmation(db):
    _, _, a, _, la, lb = await _populated(db)
    with pytest.raises(HTTPException) as exc:
        await delete_learner(a, la, _confirm(la), req(), auth=PASSWORD_ONLY, db=db)
    assert exc.value.status_code == 403
    for confirm in (_confirm(lb), _confirm(la, "Someone")):
        with pytest.raises(HTTPException) as exc:
            await delete_learner(a, la, confirm, req(), auth=ADMIN, db=db)
        assert exc.value.status_code == 422
    # Campus B's learner through campus A's path is not found.
    with pytest.raises(HTTPException) as exc:
        await delete_learner(a, lb, _confirm(lb), req(), auth=ADMIN, db=db)
    assert exc.value.status_code == 404
    assert await db.get(PilotLearner, la) is not None


@pytest.mark.asyncio
async def test_deletion_cascades_by_uuid_and_spares_the_same_named_learner(db):
    ta, _, a, _, la, lb = await _populated(db)
    old = await token(db, ta)
    receipt = await delete_learner(a, la, _confirm(la), req(), auth=ADMIN, db=db)

    assert all(v == 0 for v in receipt["remaining_counts"].values())
    assert set(receipt["deleted_counts"]) == {name for name, _ in LEARNER_TABLES}
    for name, _ in LEARNER_TABLES:
        assert receipt["deleted_counts"][name] >= 1, name
    assert "Example Learner" not in json.dumps(receipt)  # receipt holds no name
    for _, model in LEARNER_TABLES:
        col = model.id if model is PilotLearner else model.learner_id
        assert (await db.execute(select(model).where(col == la))).scalars().all() == []
        assert (await db.execute(select(model).where(col == lb))).scalars().all() != []
    # The assigned teacher is signed out immediately.
    row = await db.get(ClassicalEducator, ta["id"])
    assert row.credential_version != old["ev"]
    listed = await list_receipts(auth=ADMIN, db=db)
    assert listed[0]["receipt_id"] == receipt["receipt_id"] and listed[0]["hash_verified"]
    # A second deletion finds nothing.
    with pytest.raises(HTTPException) as exc:
        await delete_learner(a, la, _confirm(la), req(), auth=ADMIN, db=db)
    assert exc.value.status_code == 404


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


@pytest.mark.asyncio
async def test_ordinary_audit_views_show_no_readable_learner_content(db, monkeypatch):
    """The audit entry and the receipt listing are the tombstones that may
    remain after deletion. Neither may carry the learner's name or any
    evidence, recommendation or note text: only ids and counts."""
    import re
    _, _, a, _, la, _ = await _populated(db)
    logged = []

    async def capture(event, **kw):
        logged.append((event, kw))

    monkeypatch.setattr(owner, "log_event", capture)
    receipt = await delete_learner(a, la, _confirm(la), req(), auth=ADMIN, db=db)
    assert [e for e, _ in logged] == ["student.data_deleted"]
    detail = logged[0][1]["detail"]
    assert re.fullmatch(rf"pilot_learner_deleted learner={_UUID} receipt={_UUID}", detail), detail
    listing = json.dumps(await list_receipts(auth=ADMIN, db=db))
    for text in ("Example Learner", "Synthetic DIBELS 8 report", "phoneme", "segmentation"):
        assert text not in detail and text not in listing and text not in json.dumps(receipt), text
    # The teacher journey writes no general audit entries at all; its own
    # decision ledger holds hashes and ciphertext, and is removed above.
    for mod in ("pilot_journey", "pilot_campuses"):
        src = (Path(owner.__file__).parent / f"{mod}.py").read_text(encoding="utf-8")
        assert "log_event" not in src, mod


@pytest.mark.asyncio
async def test_a_failed_recheck_rolls_back_and_writes_no_receipt(db, monkeypatch):
    _, _, a, _, la, _ = await _populated(db)
    real = owner._counts
    calls = {"n": 0}

    async def recheck_finds_leftovers(session, learner_id):
        calls["n"] += 1
        out = await real(session, learner_id)
        return out if calls["n"] == 1 else {**out, "evidence": 1}

    monkeypatch.setattr(owner, "_counts", recheck_finds_leftovers)
    with pytest.raises(HTTPException) as exc:
        await delete_learner(a, la, _confirm(la), req(), auth=ADMIN, db=db)
    assert exc.value.status_code == 500
    assert await db.get(PilotLearner, la) is not None
    assert (await db.execute(select(PilotDeletionReceipt))).scalars().all() == []


@pytest.mark.asyncio
async def test_tampered_receipt_fails_verification(db):
    _, _, a, _, la, _ = await _populated(db)
    receipt = await delete_learner(a, la, _confirm(la), req(), auth=ADMIN, db=db)
    await db.execute(update(PilotDeletionReceipt)
                     .where(PilotDeletionReceipt.id == receipt["receipt_id"])
                     .values(remaining_counts=json.dumps({"learners": 1})))
    await db.commit()
    assert (await list_receipts(auth=ADMIN, db=db))[0]["hash_verified"] is False


def test_cascade_covers_every_pilot_table_keyed_by_learner():
    """A new pilot table with a learner_id that the cascade forgets would
    leave a deleted child's data behind; this fails until it is added."""
    covered = {model.__tablename__ for _, model in LEARNER_TABLES}
    keyed = {
        t.name for t in Base.metadata.sorted_tables
        if t.name.startswith("pilot_") and "learner_id" in t.c
    }
    assert keyed - covered == {"pilot_deletion_receipts"}, keyed - covered
    assert "pilot_learners" in covered


def test_only_the_whole_learner_cascade_deletes_ledger_entries():
    """The decision ledger is append-only for teachers. The owner's erasure
    is the one exception, and it may only remove a learner's whole chain,
    never an individual entry."""
    src = Path(owner.__file__).read_text(encoding="utf-8")
    assert "delete(PilotDecision" not in src  # only via the LEARNER_TABLES loop
    assert "update(PilotDecision" not in src
    assert "delete(model).where(_learner_col(model) == learner.id)" in src


def test_owner_routes_are_mounted_on_the_real_app():
    import main
    assert owner.router in [getattr(r, "original_router", None) for r in main.app.routes]
