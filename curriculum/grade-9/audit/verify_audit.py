"""Offline audit integrity checks and mock source contracts. No app startup."""
import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]


def verify(repo):
    data = json.loads((ROOT / "audit/source-register.json").read_text())
    assert not data["training_authorized"] and not data["rights_approvals"]
    ids = set()
    uses = {"copying", "distribution", "adaptation", "tts", "storage", "indexing", "model_processing"}
    for r in data["records"]:
        assert r["id"] not in ids
        ids.add(r["id"])
        for field in ("title", "author_translator", "edition_version", "publisher", "url",
                      "intended_use", "license", "evidence", "evidence_date", "jurisdiction",
                      "attribution", "reviewer", "rationale", "equipment_cost",
                      "accessibility_reading_demand_currency_context", "prohibited_or_unknown_uses"):
            assert r[field], (r["id"], field)
        assert set(r["permissions"]) == uses
        assert all(r["permissions"].values())
        assert r["disposition"] in {"candidate", "external-only", "HOLD", "reject"}
        assert r["activation"] == "NOT AUTHORIZED"
        assert r["model_training"].startswith("NOT AUTHORIZED")
    # Markdown targets, excluding external links and headings.
    for file in (ROOT / "audit").glob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", file.read_text()):
            if "://" not in target and not target.startswith("#"):
                assert (file.parent / target.split("#")[0]).exists(), (file.name, target)
    module_path = repo / "homeschool-api/services/curriculum/models.py"
    spec = importlib.util.spec_from_file_location("audit_curriculum_models", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # Only dependency-free models; block any accidental network attempt.
    socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Network forbidden"))
    spec.loader.exec_module(module)
    r = module.RightsStatus
    review = module.ReviewRecord("mock-review", "mock-item", 1,
                                "Mock Educator", datetime(2026, 11, 12),
                                module.ReviewDecision.approve)
    checks = []
    cases = [
        ("unverified rights denied", (r.unverified,), review),
        ("missing review denied", (r.original,), None),
        ("wrong version denied", (r.original,), replace(review, item_version=2)),
        ("agent identity cannot impersonate human", (r.original,), replace(review, reviewed_by="agent:audit")),
        ("nonapproval denied", (r.original,), replace(review, decision=module.ReviewDecision.reject)),
    ]
    for name, rights, record in cases:
        try:
            module.require_approvable(item_id="mock-item", version=1, rights=rights, review=record)
        except module.CurriculumModelError:
            checks.append(name)
        else:
            raise AssertionError(name)
    module.require_approvable(item_id="mock-item", version=1, rights=(r.original,), review=review)
    checks.append("mock original structural approval accepted (not authentication)")
    for status in (r.licensed, r.original):
        try:
            module.ContentChunk("mock", "source", "locator", "mock words", True,
                                "edition", status, ("objective",), "history", "grade9",
                                "mock-campus", module.Visibility.campus,
                                module.ItemStatus.staged, 1)
        except module.CurriculumModelError:
            checks.append(f"verbatim {status.value} denied")
        else:
            raise AssertionError("verbatim gate weakened")
    files = [
        "homeschool-api/services/curriculum/" + name + ".py"
        for name in ("models", "rights_gate", "workflow", "local_hybrid_index",
                     "citation_retriever", "learner_evolution", "persistence", "flag")
    ]
    print(json.dumps({"register_records": len(ids), "source_contract_checks": checks,
                      "source_hashes": {f: hashlib.sha256((repo / f).read_bytes()).hexdigest() for f in files},
                      "limits": "Mock pure-model checks only; no upstream pytest, DB, auth, browser, rights or deployment certification."}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    verify(parser.parse_args().repo.resolve())
