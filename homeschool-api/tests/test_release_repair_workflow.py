"""Guards on the release-repair workflows, prompts and their wiring.

These pin the trust boundary in the parsed YAML: no write permission, no
secret, no model, no schedule, no merge; candidate code isolated from state;
the existing owner holds unchanged; and the change filter naming the inputs.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from release_repair_helpers import REPO, pol

WF = REPO / ".github" / "workflows"
LOOP = WF / "release-repair.yml"
AUDIT = WF / "release-repair-audit.yml"
PROMPTS = sorted((REPO / ".github" / "agent-prompts").glob("release-repair-*.md"))
CODE = sorted((REPO / "scripts" / "release_repair").glob("*.py")) + [REPO / "scripts/release_repair/record.sh"]


def load(path):
    data = yaml.safe_load(path.read_text())
    data["on"] = data.pop(True, data.get("on"))
    return data


def steps(job):
    return job.get("steps", [])


def test_the_loop_is_dispatch_only_from_main_with_no_schedule():
    wf = load(LOOP)
    assert set(wf["on"]) == {"workflow_dispatch"}
    assert "refs/heads/main" in LOOP.read_text()
    assert wf["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("path", [LOOP, AUDIT])
def test_no_job_can_write_and_no_secret_is_used(path):
    text, wf = path.read_text(), load(path)
    perms = [wf.get("permissions", {})] + [j.get("permissions", {}) for j in wf["jobs"].values()]
    assert all(v in ("read", "none") for p in perms for v in p.values()), perms
    assert "secrets." not in text
    for word in ("anthropic", "claude-code-action", "API_KEY", "openai"):
        assert word not in text, word


def test_the_candidate_job_is_isolated_from_state():
    job = load(LOOP)["jobs"]["candidate"]
    assert job["permissions"] == {"contents": "read"}
    body = yaml.safe_dump(job)
    assert "download-artifact" not in body and "release-repair-state" not in body
    assert "GH_TOKEN" not in body and "github.token" not in body


def test_record_runs_only_trusted_code():
    job = load(LOOP)["jobs"]["record"]
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    runs = [s for s in steps(job) if "run" in s]
    assert runs and all(s.get("working-directory") == "trusted" for s in runs)
    for s in runs:
        assert not re.search(r"(?:python3?|bash|node|npm|npx)\s+\.\./candidate", s["run"])


def test_every_checkout_drops_its_credentials():
    for path in (LOOP, AUDIT):
        for job in load(path)["jobs"].values():
            for s in steps(job):
                if str(s.get("uses", "")).startswith("actions/checkout@"):
                    assert s["with"]["persist-credentials"] is False


def test_free_text_reaches_run_steps_only_through_env():
    for path in (LOOP, AUDIT):
        for job in load(path)["jobs"].values():
            for s in steps(job):
                assert "${{" not in s.get("run", ""), s.get("name")


def test_linux_jobs_are_pinned():
    for path in (LOOP, AUDIT):
        assert {j["runs-on"] for j in load(path)["jobs"].values()} == {"ubuntu-24.04"}


def test_nothing_in_the_loop_pushes_merges_or_deploys():
    pattern = re.compile(r"git push|gh pr merge|/merge\b|merge_pull_request|pulls/\d*/merge|deploy-demo|"
                         r"workflow_dispatch.*dispatches|createWorkflowDispatch")
    for f in CODE + [LOOP, AUDIT]:
        assert not pattern.search(f.read_text()), f.name


def test_the_audit_runs_on_every_push_to_main():
    wf = load(AUDIT)
    assert wf["on"] == {"push": {"branches": ["main"]}}
    assert wf["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_the_existing_owner_holds_are_unchanged():
    watchdog = load(WF / "demo-watchdog.yml")
    assert str(watchdog["jobs"]["repair"]["if"]).replace(" ", "") in ("${{false}}", "False")
    assert watchdog["jobs"]["repair"]["permissions"] == {"contents": "read"}
    merge = load(WF / "bede-event-driven-merge.yml")
    assert set(merge["on"]) == {"workflow_dispatch"}
    assert merge["jobs"]["guarded-merge"]["if"] is False


@pytest.mark.parametrize("prompt", PROMPTS, ids=lambda p: p.name)
def test_every_role_prompt_defers_to_the_common_rules(prompt):
    if prompt.name == "release-repair-common.md":
        text = prompt.read_text()
        for rule in ("push to `main`", "merge", "force-push", "invent a result", "AgentResult",
                     "raw crash reports", "model identifier"):
            assert rule in text, rule
    else:
        assert "release-repair-common.md" in prompt.read_text()


def test_all_four_roles_have_prompts():
    names = {p.name for p in PROMPTS}
    assert {f"release-repair-{r}.md" for r in ("common", "triage", "reproduce", "repair", "review")} <= names


def test_the_policy_bounds_the_budget_and_suppresses_nothing():
    p = pol()
    assert p.repair_budget == 2
    assert not any(r.get("suppress_repair") for r in p.failure_rules())
    ex = p.data["execution"]
    assert not any(ex.values())


def test_the_inputs_are_in_the_api_change_filter():
    line = next(l for l in (WF / "test.yml").read_text().splitlines() if "grep -qE" in l)
    alternatives = line.split("'", 2)[1].strip("^()").split("|")
    for alt in ("scripts/release_repair/", "config/", "schemas/", "\\.github/agent-prompts/",
                "docs/release/REPAIR_LOOP\\.md", "\\.github/workflows/"):
        assert alt in alternatives, alt


def test_the_selector_treats_the_loop_as_cross_cutting():
    text = (REPO / "scripts" / "qa" / "selector.py").read_text()
    for prefix in ('"scripts/release_repair/"', '"config/acceptance/"', '"schemas/"', '".github/agent-prompts/"'):
        assert prefix in text


def test_a_malformed_verification_request_is_refused_before_it_can_spend_an_attempt():
    resolve = load(LOOP)["jobs"]["resolve"]
    guard = steps(resolve)[0]["run"]
    assert "base_sha (40 hex) is required with branch" in guard and "task_id is required" in guard


def test_a_failed_candidate_job_is_infra_error_not_a_failed_repair():
    record = load(LOOP)["jobs"]["record"]
    dl = next(s for s in steps(record) if str(s.get("uses", "")).startswith("actions/download-artifact@"))
    assert dl.get("continue-on-error") is True
    script = (REPO / "scripts" / "release_repair" / "record.sh").read_text()
    assert "no repair attempt spent" in script and "exit 3" in script
