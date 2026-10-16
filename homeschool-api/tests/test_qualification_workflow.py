"""The synthetic qualification workflow, guarded against its PARSED YAML.

.github/workflows/qualification.yml produces evidence about one fixed commit
and must never be able to do anything else. Every property it depends on is
asserted here against what GitHub will actually read (``yaml.safe_load``),
not against a grep of the text, plus the harness's own fail-closed logic in
scripts/qualification/ is exercised directly:

  * it qualifies a 40-hex candidate SHA, checks that exact commit out, and
    fails when HEAD differs; it never accepts a branch name;
  * read-only token, pinned runner, actions pinned by full SHA (reusing
    pins already in this repository), no pull_request_target, deploy,
    merge, release or workflow dispatch;
  * the brief's exact concurrency block, under which a superseded PR run is
    cancelled and a dispatched run never is;
  * evidence packaging and upload always run, and upload only after the
    credential scan passed; retention comes from an input;
  * G3/Mac is a placeholder input only and nothing claims a Mac check ran;
  * the preflight fails closed on each forbidden category, a missing route
    becomes an ABSENT cell rather than a skipped one, and seeding refuses a
    non-synthetic name.

See docs/SYNTHETIC_QUALIFICATION.md. Each assertion was verified by breaking
the property it guards (recorded in the PR).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "qualification.yml"
QUAL = REPO / "scripts" / "qualification"
sys.path.insert(0, str(QUAL))

EXACT_GROUP = "qualification-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}"
EXACT_CANCEL = "${{ github.event_name == 'pull_request' }}"
CANDIDATE_EXPR = "${{ inputs.candidate_sha || github.event.pull_request.head.sha }}"


def _wf() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text())
    doc["_on"] = doc.get("on", doc.get(True))  # PyYAML parses bare `on` as True
    return doc


def _steps() -> list[dict]:
    return _wf()["jobs"]["qualify"]["steps"]


def _step(name_part: str) -> dict:
    return next(s for s in _steps() if name_part in s.get("name", ""))


def _index(name_part: str) -> int:
    return next(i for i, s in enumerate(_steps()) if name_part in s.get("name", ""))


# ── triggers, token, runner ─────────────────────────────────────────────────

def test_only_dispatch_and_pull_request_trigger_it():
    assert set(_wf()["_on"]) == {"workflow_dispatch", "pull_request"}


def test_candidate_sha_is_a_required_dispatch_input():
    inp = _wf()["_on"]["workflow_dispatch"]["inputs"]["candidate_sha"]
    assert inp["required"] is True and inp["type"] == "string"


def test_token_is_read_only_everywhere():
    wf = _wf()
    assert wf["permissions"] == {"contents": "read"}
    for job in wf["jobs"].values():
        assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}


def test_runs_on_the_pinned_ubuntu():
    for job in _wf()["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"


def test_every_action_is_pinned_by_a_sha_already_used_in_this_repo():
    others = "\n".join(p.read_text() for p in WORKFLOW.parent.glob("*.yml") if p != WORKFLOW)
    uses = [s["uses"] for s in _steps() if "uses" in s]
    assert uses
    for ref in uses:
        name, _, sha = ref.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", sha), ref
        assert f"{name}@{sha}" in others, f"{ref} is not a pin this repository already uses"


@pytest.mark.parametrize("forbidden", [
    "pull_request_target", "createWorkflowDispatch", "workflow_dispatch:\n      ref",
    "gh pr merge", "gh workflow run", "gh release", "deploy-pages", "wrangler",
    "docker push", "secrets.", "--with-deps",
])
def test_no_forbidden_capability_appears(forbidden):
    assert forbidden not in WORKFLOW.read_text()


def test_no_step_merges_deploys_or_releases():
    for s in _steps():
        text = (s.get("run", "") + " " + s.get("uses", "")).lower()
        for word in ("merge", "deploy", "release", "publish"):
            assert word not in text, (s.get("name"), word)


# ── fixed candidate SHA ─────────────────────────────────────────────────────

def test_checkout_uses_the_candidate_sha_not_a_branch():
    co = _step("Check out the candidate")
    assert co["with"]["ref"] == CANDIDATE_EXPR
    assert co["with"]["persist-credentials"] is False
    assert _wf()["jobs"]["qualify"]["env"]["QUAL_CANDIDATE_SHA"] == CANDIDATE_EXPR


def test_the_sha_is_shape_checked_before_checkout_and_head_verified_after():
    shape = _step("Require a full commit SHA")
    assert "^[0-9a-f]{40}$" in shape["run"] and "exit 1" in shape["run"]
    assert shape["env"]["CANDIDATE"] == CANDIDATE_EXPR
    verify = _step("Verify HEAD is exactly")
    assert 'test "$head" = "$QUAL_CANDIDATE_SHA"' in verify["run"]
    assert _index("Require a full commit SHA") < _index("Check out the candidate") < _index("Verify HEAD")


# ── concurrency ─────────────────────────────────────────────────────────────

def test_concurrency_block_is_exactly_the_briefs():
    assert _wf()["concurrency"] == {"group": EXACT_GROUP, "cancel-in-progress": EXACT_CANCEL}


def _cancel_for(event_name: str) -> bool:
    """Evaluate the cancel-in-progress expression as Actions would. Only the
    one shape the exact block uses is accepted, so a change to the
    expression fails the test above rather than being evaluated loosely."""
    expr = _wf()["concurrency"]["cancel-in-progress"]
    m = re.fullmatch(r"\$\{\{ github\.event_name == '([a-z_]+)' \}\}", expr)
    assert m, expr
    return event_name == m.group(1)


def test_a_dispatched_run_is_never_cancelled_by_a_newer_run():
    """An IN-PROGRESS dispatched run. GitHub still replaces a *pending* run
    in the same group with a newer pending one; the exact block cannot close
    that, and docs/SYNTHETIC_QUALIFICATION.md says so."""
    assert _cancel_for("workflow_dispatch") is False
    assert _cancel_for("pull_request") is True
    # Nothing else can cancel it either: no job- or step-level concurrency,
    # and no step that cancels runs.
    for job in _wf()["jobs"].values():
        assert "concurrency" not in job
    assert "cancel" not in " ".join(s.get("run", "") for s in _steps()).lower()


# ── preflight, evidence, verdict ────────────────────────────────────────────

def test_preflight_runs_before_the_stack_and_cannot_be_skipped():
    pre = _step("Fail-closed preflight")
    assert "preflight.py --phase pre-start" in pre["run"]
    assert "if" not in pre and "continue-on-error" not in pre
    assert _index("Fail-closed preflight") < _index("Run the stack")


def test_application_environment_is_synthetic():
    env = _wf()["jobs"]["qualify"]["env"]
    assert env["PRODUCTION"] == "false"
    assert env["EDUCATOR_PILOT_ENABLED"] == "true"
    assert env["ELEVATION_ENFORCED"] == "true"
    assert env["BEDE_FORCE_ADAPTER"] == "local"
    assert env["LOCAL_LLM_BASE_URL"].startswith("http://127.0.0.1:")
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY", "RESEND_API_KEY",
                 "LICENSE_SERVER_URL", "LICENSE_KEY", "STRIPE_SECRET_KEY", "PARENT_EMAIL"):
        assert name not in env


def test_evidence_is_packaged_and_uploaded_even_when_the_matrix_fails():
    pkg, up, fin = _step("Package evidence"), _step("Upload evidence"), _step("Final verification")
    assert pkg["if"] == "always()" and fin["if"] == "always()"
    assert up["if"] == "always() && steps.package.outcome == 'success'"
    assert "continue-on-error" not in up


def test_retention_comes_from_an_input():
    up = _step("Upload evidence")
    assert "inputs.artifact_retention_days" in str(up["with"]["retention-days"])
    assert _wf()["_on"]["workflow_dispatch"]["inputs"]["artifact_retention_days"]["type"] == "number"
    assert up["with"]["name"] == "qualification-${{ env.QUAL_CANDIDATE_SHA }}"


def test_final_verification_fails_unless_matrix_and_package_succeeded():
    run = _step("Final verification")["run"]
    assert 'test "$PACKAGE_OUTCOME" = success' in run
    assert 'test "$QUALIFY_OUTCOME" = success' in run


# ── G3 placeholder ──────────────────────────────────────────────────────────

def test_mac_package_is_a_placeholder_input_only():
    inp = _wf()["_on"]["workflow_dispatch"]["inputs"]["mac_package"]
    assert inp["options"] == ["none"] and "PLACEHOLDER" in inp["description"]
    text = WORKFLOW.read_text().lower()
    assert "macos" not in text
    assert "physical mac verification: not run" in text


def test_nothing_claims_a_physical_mac_check_ran():
    import package
    text = (WORKFLOW.read_text() + (QUAL / "package.py").read_text()).lower()
    for claim in ("mac verification: pass", "mac verified", "physical mac verification: done",
                  "mac check passed"):
        assert claim not in text
    manifest = package.build_manifest(QUAL, {}, {})
    assert manifest["mac_package"]["built"] is False
    assert manifest["mac_package"]["physical_mac_verification"].startswith("NOT RUN")


# ── the harness itself fails closed ─────────────────────────────────────────

def _base_env(**overrides) -> dict:
    env = {
        "QUAL_CANDIDATE_SHA": "0" * 40, "PRODUCTION": "false", "EDUCATOR_PILOT_ENABLED": "true",
        "ELEVATION_ENFORCED": "true", "MCP_EXTERNAL_ENABLED": "false", "LOCUTO_IPC_ENABLED": "false",
        "LOCAL_LLM_BASE_URL": "http://127.0.0.1:8766/v1", "BEDE_FORCE_ADAPTER": "local",
        "DATABASE_URL": "",  # never connects in these tests
    }
    env.update(overrides)
    return env


def _failed(env: dict) -> set[str]:
    import preflight
    report = preflight.run("pre-start", env, skip_import=True)
    return {c["check"] for c in report.checks if not c["ok"]}


def test_preflight_baseline_only_fails_on_sha_and_database():
    failed = _failed(_base_env())
    assert failed <= {"head_equals_candidate", "database_is_postgres", "database_host_is_service"}


@pytest.mark.parametrize("override, expected", [
    ({"PRODUCTION": "true"}, "env_required:PRODUCTION=false"),
    ({"OPENAI_API_KEY": "x"}, "env_unset:OPENAI_API_KEY"),
    ({"ANTHROPIC_API_KEY": "x"}, "env_unset:ANTHROPIC_API_KEY"),
    ({"RESEND_API_KEY": "x"}, "env_unset:RESEND_API_KEY"),
    ({"STRIPE_SECRET_KEY": "x"}, "env_unset:STRIPE_SECRET_KEY"),
    ({"STRIPE_ANYTHING": "x"}, "env_prefix_forbidden:STRIPE_ANYTHING"),
    ({"LICENSE_SERVER_URL": "https://x"}, "env_unset:LICENSE_SERVER_URL"),
    ({"BEDE_REAL_DATA": "true"}, "env_marker_enabled:BEDE_REAL_DATA"),
    ({"BILLING_ENABLED": "1"}, "env_marker_enabled:BILLING_ENABLED"),
    ({"PILOT_AUTO_ENROLL": "yes"}, "env_marker_enabled:PILOT_AUTO_ENROLL"),
    ({"AUTH_BYPASS": "on"}, "env_marker_enabled:AUTH_BYPASS"),
    ({"PILOT_AUTO_DELIVER": "true"}, "env_marker_enabled:PILOT_AUTO_DELIVER"),
    ({"ELEVATION_ENFORCED": "false"}, "env_required:ELEVATION_ENFORCED=true"),
    ({"EDUCATOR_PILOT_ENABLED": "false"}, "env_required:EDUCATOR_PILOT_ENABLED=true"),
    ({"LOCAL_LLM_BASE_URL": "https://api.openai.com/v1"}, "ai_provider_is_loopback_stub"),
    ({"BEDE_FORCE_ADAPTER": "openai"}, "ai_adapter_forced_local"),
    ({"QUAL_CANDIDATE_SHA": "main"}, "candidate_sha_is_40_hex"),
    ({"DATABASE_URL": "postgresql+asyncpg://u:p@db.example.com:5432/x"}, "database_host_is_service"),
])
def test_preflight_fails_closed(override, expected):
    assert expected in _failed(_base_env(**override))


def test_delivery_route_detector_flags_session_launch_paths():
    import preflight
    assert preflight.delivery_offenders([("POST", "/pilot/me/learners/{learner_id}/session/start")])
    assert preflight.delivery_offenders([("POST", "/pilot/me/learners/{learner_id}/deliver")])
    assert not preflight.delivery_offenders([("GET", "/pilot/me/learners/{learner_id}/instruction")])
    assert not preflight.delivery_offenders([("POST", "/voice/stream/start")])  # not under /pilot


def test_candidate_route_table_has_no_pilot_delivery_route():
    """Invocation half: the detector run over the REAL app's routes, flattened
    the way preflight flattens them (FastAPI 0.141 nests _IncludedRouter)."""
    import main
    import preflight
    table = sorted(set(preflight.served_routes(main.app.routes)))
    assert ("GET", "/pilot/me/learners/{learner_id}") in table
    assert len(table) > 20
    assert preflight.delivery_offenders(table) == []


def test_a_missing_route_is_recorded_absent_never_skipped():
    import matrix
    from seed import Fixture

    class _Seeder:
        fx = Fixture(mode="virtual_authenticator")

    m = matrix.Matrix(api=None, driver=None, stack=None, seeder=_Seeder(), routes=set())
    for row in matrix.TABLE:
        if not row.get("special"):
            m.run_generic(row)
    m.voice_owner_binding()
    m.g2()
    m.deletion()
    assert m.cells
    assert {c.status for c in m.cells} == {"ABSENT"}
    covered = {c.row for c in m.cells}
    assert {r["id"] for r in matrix.TABLE} <= covered


def test_table_covers_every_group_the_brief_requires():
    import matrix
    assert {r["group"] for r in matrix.TABLE} == {"G1", "DIBELS", "G2", "DELETION"}
    for row in matrix.TABLE:
        for op in ("read", "write", "list", "delete"):
            if row.get(op):
                assert row[op][0] in ("GET", "POST", "PUT", "DELETE") and row[op][1].startswith("/")


def test_sse_denial_requires_the_server_to_refuse():
    import matrix
    assert matrix._sse_denied({"status": 404})
    assert matrix._sse_denied({"status": 200, "ended": True, "error": None, "data_events": 1,
                               "text": '{"type": "error", "message": "unknown or expired session"}'})
    # Attached and held open, or a client-side error, is not a denial.
    assert not matrix._sse_denied({"status": 200, "ended": False, "error": None, "data_events": 0})
    assert not matrix._sse_denied({"status": 200, "ended": True, "error": "ReadTimeout",
                                   "data_events": 1, "text": "unknown or expired session"})


def test_seeding_refuses_a_non_synthetic_name():
    import seed
    assert seed.assert_synthetic("Synthetic Campus One") == "Synthetic Campus One"
    with pytest.raises(seed.NotSynthetic):
        seed.assert_synthetic("Valor Academy")


def test_credential_scan_fails_closed(tmp_path):
    import package
    (tmp_path / "server.log").write_text("ok\nAuthorization: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4eHh4eHgifQ.c2lnbmF0dXJlc2ln\n")
    (tmp_path / "other.log").write_text("synthetic-literal-secret-value")
    findings = package.scan(tmp_path, {"SECRET_KEY": "synthetic-literal-secret-value"})
    assert {f["file"] for f in findings} == {"server.log", "other.log"}
    (tmp_path / "server.log").write_text("clean")
    (tmp_path / "other.log").write_text("clean")
    assert package.scan(tmp_path, {"SECRET_KEY": "synthetic-literal-secret-value"}) == []


# ── change filter ───────────────────────────────────────────────────────────

def test_this_guards_inputs_are_in_the_api_change_filter():
    """Without these, an edit to only the harness or the workflow computes
    relevant=false in test.yml and skips the guard written for that edit."""
    test_yml = (WORKFLOW.parent / "test.yml").read_text()
    line = next(line for line in test_yml.splitlines() if "grep -qE" in line)
    alternatives = line.split("'", 2)[1].strip("^()").split("|")
    assert "scripts/qualification/" in alternatives
    assert "\\.github/workflows/" in alternatives
    assert "docs/SYNTHETIC_QUALIFICATION\\.md" in alternatives
