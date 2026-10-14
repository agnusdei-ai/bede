import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/institutional/VALOR_RELEASE_JOURNEYS.json"


def load():
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_release_ledger_cannot_claim_ready_with_blocked_workflows():
    data = load()
    assert data["release_status"] == "blocked_pending_runtime_qualification"
    assert len(data["journeys"]) >= 8
    assert len({item["id"] for item in data["journeys"]}) == len(data["journeys"])
    assert all(j["required_tests"] and j["surface"] for j in data["journeys"])
    assert all(j["status"] in {"blocked", "verified"} for j in data["journeys"])
    if any(j["status"] == "blocked" for j in data["journeys"]):
        assert data["release_status"] != "ready"


def test_no_external_usability_participant_or_customer_pilot_release_gate():
    data = load()
    sessions = data["owner_usability_sessions"]
    assert sessions["min"] == 1 and sessions["max"] <= 5
    assert sessions["external_participants_required"] is False
    assert data["institutional_pilot_is_separate_engagement"] is True


def test_unverified_connectors_never_masquerade_as_required_api():
    data = load()
    required = {"schoolaxis", "jupiter_ed"}
    by_id = {entry["id"]: entry for entry in data["connectors"]}
    assert required <= by_id.keys()
    for connector in data["connectors"]:
        assert connector["data_policy"]
        if connector["api_status"] in {"unverified", "discovery"}:
            assert connector["release_requirement"] != "required_api"
