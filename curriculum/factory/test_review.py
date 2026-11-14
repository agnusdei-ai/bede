"""Actual existing SQLite reviewer workflow; no manufactured authorization system."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from boundary import ROOT, Error
from fixture import write_fixture
from ledger import Ledger
from run import execute

# All values here are sample test configuration, not workspace secrets.
for key, value in {
    "SECRET_KEY": "factory-sample-secret-" + "x"*32,
    "MASTER_SECRET": "factory-sample-master-" + "y"*32,
    "ANTHROPIC_API_KEY": "sample-never-called",
    "DATABASE_URL": "postgresql+asyncpg://sample:sample@127.0.0.1/never_connect",
}.items():
    os.environ.setdefault(key, value)

sys.path.insert(0, str(ROOT/"homeschool-api"))
sys.path.insert(0, str(ROOT/"homeschool-api/tests"))

import pytest
from sqlalchemy import insert, update
from services.curriculum.models import ReviewDecision
from services.curriculum.persistence import reviewer_grants, reviews, sources
from services.curriculum.workflow import review_staged_lesson, CurriculumWorkflowDenied
from test_curriculum_workflow import setup, token
from review import stage_for_review, resolve_receipt, development_database


class ReviewerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, BEDE_CURRICULUM_FACTORY_ENABLED="1",
                              BEDE_FACTORY_MODE="development")
        self.env.start()
        parent = ROOT/"generated-artifacts/curriculum-factory"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name)
        write_fixture(self.root/"input")
        self.ledger = Ledger(self.root/"store")
        self.job = execute(self.ledger, self.root/"input/bundle.json", "review-sample")
        self.monkeypatch = pytest.MonkeyPatch()
        self.engine, self.Session, self.author, self.reviewer, self.outsider = await setup(self.monkeypatch)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.monkeypatch.undo()
        self.ledger.close()
        self.temp.cleanup()
        self.env.stop()

    async def stage(self, db):
        return await stage_for_review(
            db, token(self.author), "campus-a", self.ledger, self.job, "pairs",
            rights_verified_by="Sample rights staff", rights_evidence_ref="sample:original")

    async def approve(self, db):
        return await review_staged_lesson(
            db, token(self.reviewer), "campus-a", "pairs",
            decision=ReviewDecision.approve, notes="Sample adapter test, not curriculum approval")

    async def resolve(self, db, receipt, **kwargs):
        return await resolve_receipt(
            db, kwargs.get("credential", token(self.reviewer)), kwargs.get("campus", "campus-a"),
            receipt, self.ledger, self.job, kwargs.get("lesson", "pairs"))

    async def test_existing_authenticated_approval_exact_binding(self):
        async with self.Session() as db:
            self.assertEqual(await self.stage(db), 1)
            receipt, version = await self.approve(db)
            self.assertEqual(version, 2)
            result = await self.resolve(db, receipt)
            self.assertEqual(result["target"]["factory_key"], self.job["key"])
            self.assertEqual(result["kind"], "authenticated_development_receipt")
            self.assertEqual(self.ledger.get(self.job["key"])["status"], "succeeded")
            self.assertIn("pending", self.ledger.get(self.job["key"])["approvals"])

    async def test_no_self_review_even_with_real_reviewer_grant(self):
        async with self.Session() as db:
            await self.stage(db)
            await db.execute(insert(reviewer_grants).values(
                campus_id="campus-a", educator_id=self.author, enabled=True,
                granted_by="independent-admin", issued_at=__import__("datetime").datetime.now()))
            await db.commit()
            with self.assertRaises(CurriculumWorkflowDenied):
                await review_staged_lesson(
                    db, token(self.author), "campus-a", "pairs", decision=ReviewDecision.approve)

    async def test_missing_string_wrong_identity_and_wrong_campus_receipts(self):
        async with self.Session() as db:
            await self.stage(db)
            receipt, _ = await self.approve(db)
            for receipt_id, changes in (
                ("human:typed-name", {}), (receipt, {"campus": "campus-b"}),
                (receipt, {"credential": token(self.outsider)}),
                (receipt, {"credential": token(self.reviewer, auth_method="password")}),
                (receipt, {"credential": token(self.reviewer, ev=0)}),
                (receipt, {"credential": "reviewer-name"}),
                (receipt, {"lesson": "other"}),
            ):
                with self.subTest(changes=changes):
                    with self.assertRaises((Error, CurriculumWorkflowDenied)):
                        await self.resolve(db, receipt_id, **changes)

    async def test_revoked_grant_and_disabled_membership_denied(self):
        from core.database import PilotEducatorCampus
        async with self.Session() as db:
            await self.stage(db)
            receipt, _ = await self.approve(db)
            await db.execute(update(reviewer_grants).values(enabled=False))
            await db.commit()
            with self.assertRaises(CurriculumWorkflowDenied):
                await self.resolve(db, receipt)
            await db.execute(update(reviewer_grants).values(enabled=True))
            await db.execute(update(PilotEducatorCampus).where(
                PilotEducatorCampus.educator_id == self.reviewer).values(enabled=False))
            await db.commit()
            with self.assertRaises(CurriculumWorkflowDenied):
                await self.resolve(db, receipt)

    async def test_changed_content_tools_outputs_and_source_invalidate_approval(self):
        from boundary import contract as c, tools
        async with self.Session() as db:
            await self.stage(db)
            receipt, _ = await self.approve(db)
            with patch("run.tools", return_value={**tools(), "changed": True}):
                with self.assertRaisesRegex(Error, "stale"):
                    await self.resolve(db, receipt)
            # Historical authenticated review remains stored; factory cannot rewrite it.
            self.assertIsNotNone((await db.execute(
                __import__("sqlalchemy").select(reviews).where(reviews.c.review_id == receipt))).first())

    async def test_source_fingerprint_change_denied(self):
        async with self.Session() as db:
            await self.stage(db)
            receipt, _ = await self.approve(db)
            await db.execute(update(sources).values(content_hash="f"*64))
            await db.commit()
            with self.assertRaisesRegex(Error, "fingerprint"):
                await self.resolve(db, receipt)

    async def test_output_corruption_refuses_authenticated_receipt(self):
        async with self.Session() as db:
            await self.stage(db)
            receipt, _ = await self.approve(db)
            path = self.ledger.root/self.job["key"]/"student.html"
            path.write_bytes(b"corrupt")
            with self.assertRaisesRegex(Error, "checksum"):
                await self.resolve(db, receipt)

    async def test_revised_rubric_refuses_authenticated_receipt(self):
        from boundary import contract as c
        from fixture import example
        async with self.Session() as db:
            await self.stage(db)
            receipt, _ = await self.approve(db)
            bundle = example()
            bundle["lessons"][0]["assessments"][0]["key_rubric"] += " Changed."
            bundle["units"][0]["lesson_refs"] = [c.ref(bundle["lessons"][0])]
            bundle["grade"]["unit_refs"] = [c.ref(bundle["units"][0])]
            for gate in bundle["gates"]:
                gate["target"] = c.ref(bundle["grade"])
            (self.root/"input/bundle.json").write_bytes(c.canonical(bundle))
            with self.assertRaisesRegex(Error, "stale"):
                await self.resolve(db, receipt)

    async def test_rejected_review_never_resolves_as_approval(self):
        async with self.Session() as db:
            await self.stage(db)
            receipt, version = await review_staged_lesson(
                db, token(self.reviewer), "campus-a", "pairs", decision=ReviewDecision.reject)
            self.assertIsNone(version)
            with self.assertRaisesRegex(Error, "No current independent"):
                await self.resolve(db, receipt)

    async def test_production_database_and_disabled_factory_refused(self):
        class FakeDB:
            class bind:
                class url:
                    drivername = "postgresql+asyncpg"
        with self.assertRaisesRegex(Error, "refuses"):
            development_database(FakeDB())
        async with self.Session() as db:
            with patch.dict(os.environ, {"BEDE_FACTORY_MODE": "production"}):
                with self.assertRaisesRegex(Error, "disabled"):
                    await self.stage(db)


if __name__ == "__main__":
    unittest.main()
