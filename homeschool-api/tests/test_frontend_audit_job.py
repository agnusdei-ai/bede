"""The frontend dependency audit cannot skip the frontend test suites.

`npm audit` ran as a STEP inside `homeschool-tutor-tests` and `demo-tests`,
immediately before `Type-check` and `Run tests`. A failing audit therefore
left both SKIPPED — and the thing that fails an audit is an advisory published
by a stranger, not a change a contributor made.

That is not hypothetical. On 2026-10-04, GHSA-vfj7-8cjw-p6xm (a
stack-exhaustion advisory in `braces`, reaching this repo only through
Tailwind 3's build-time globbing) turned both jobs red and hid 574
homeschool-tutor tests plus the demo's behind a finding that had nothing to do
with the pull request under review.

`homeschool-api/tests/test_dependency_audit_job.py` records the identical
defect and fix on the BACKEND side (twice in one day on 2026-10-01). The
frontend had the same structure and nobody split it; this is that fix applied
here, and these guards are deliberately its mirror.

**The split does not weaken the gate.** The audit still fails the workflow,
and the standing rule is unchanged: a red audit means upgrade the dependency,
or record why it is unreachable in `.github/audit-allowlist.json` — never
delete the step (see `frontend-tests.yml`'s own header on #296, where deleting
an audit gate took this repo from one blocked PR to zero vulnerability
visibility). What the split changes is only that a dependency advisory can no
longer hide a test regression behind it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "frontend-tests.yml"
TEST_WORKFLOW = REPO / ".github" / "workflows" / "test.yml"
ALLOWLIST = REPO / ".github" / "audit-allowlist.json"
GATE = REPO / "scripts" / "npm_audit_gate.py"

AUDIT_JOB = "frontend-dependency-audit"
TEST_JOBS = ["homeschool-tutor-tests", "demo-tests"]


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _runs(job: dict) -> str:
    return "\n".join(s.get("run", "") for s in job.get("steps", []))


def _step_names(job: dict) -> list[str]:
    return [s.get("name", "") for s in job.get("steps", [])]


def test_the_audit_is_its_own_job() -> None:
    jobs = _workflow()["jobs"]
    assert AUDIT_JOB in jobs, (
        f"{AUDIT_JOB} is gone. The audit must not move back inside a test "
        "job: a failing audit would skip Type-check and Run tests again, "
        "which is the defect this job was split out to fix."
    )


@pytest.mark.parametrize("job_name", TEST_JOBS)
def test_no_test_job_runs_an_audit_step(job_name: str) -> None:
    """The point of the split, stated as the assertion."""
    job = _workflow()["jobs"][job_name]
    offenders = [n for n in _step_names(job) if "audit" in n.lower()]
    assert not offenders, (
        f"{job_name} has an audit step again ({offenders!r}). A failing audit "
        "there skips Type-check and Run tests, so an advisory published by a "
        "stranger takes the frontend suite down with it."
    )
    body = _runs(job)
    assert "npm audit" not in body, (
        f"{job_name} invokes `npm audit` in a step body, which has the same "
        "effect whatever the step is called."
    )
    assert "npm_audit_gate" not in body, (
        f"{job_name} invokes the audit gate in a step body, same effect."
    )


@pytest.mark.parametrize(
    "job_name,scope,test_file",
    [
        ("homeschool-tutor-tests", "homeschool-tutor", "homeschool-tutor/src/palette.test.ts"),
        ("demo-tests", "demo", "demo/src/App.test.tsx"),
    ],
)
def test_every_test_job_still_tests(job_name: str, scope: str, test_file: str) -> None:
    """Check the actual QA selector contract, not an obsolete command string."""
    import subprocess
    import sys

    repo = WORKFLOW.parents[2]
    body = _runs(_workflow()["jobs"][job_name])
    assert (
        f"scripts/qa/runner.py --repo . --plan qa-plan.json --scope {scope}"
        in body
    ), f"{job_name} no longer invokes the QA test runner"
    assert "scripts/qa/selector.py --base" in body
    assert "scripts/qa/selector.py --full" in body
    assert (repo / "scripts/qa/runner.py").is_file()
    result = subprocess.run(
        [sys.executable, "scripts/qa/selector.py", "--file", test_file],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    commands = [c["argv"] for c in json.loads(result.stdout)["commands"]
                if c["scope"] == scope]
    assert ["npx", "tsc", "--noEmit"] in commands, f"{job_name} no longer type-checks"
    assert any(c[:3] == ["npx", "vitest", "run"]
               and test_file.split(scope + "/", 1)[1] in c
               for c in commands), f"{job_name} no longer executes its affected tests"


def test_the_audit_still_covers_both_projects() -> None:
    """Splitting it out must not quietly narrow what it audits."""
    body = _runs(_workflow()["jobs"][AUDIT_JOB])
    assert "homeschool-tutor" in body and "demo" in body, (
        f"{AUDIT_JOB} no longer audits both npm projects."
    )


def test_the_audit_goes_through_the_allowlist_aware_gate() -> None:
    """A bare `npm audit` cannot honour the recorded exception.

    `npm audit` has no --ignore flag, so running it directly would leave the
    escape hatch this workflow's own header names ("record why it is
    unreachable in .github/audit-allowlist.json") unreachable for npm — and
    the only ways out of a red gate would be an upgrade or deleting the step.
    """
    body = _runs(_workflow()["jobs"][AUDIT_JOB])
    assert "npm_audit_gate.py" in body, (
        f"{AUDIT_JOB} no longer runs scripts/npm_audit_gate.py, so an npm "
        "allowlist entry would be silently ignored."
    )
    assert GATE.exists(), "scripts/npm_audit_gate.py is missing"


def test_the_audit_is_gated_on_the_same_change_filter_as_the_tests() -> None:
    """The audit must run for the union of selected test packages.

    Per-package tests can skip unrelated packages, but an npm dependency
    finding must not be missed just because only one package changed.
    """
    jobs = _workflow()["jobs"]
    assert jobs[AUDIT_JOB].get("if") == "needs.changes.outputs.relevant == 'true'"
    outputs = jobs["changes"]["outputs"]
    filter_body = _runs(jobs["changes"])
    assert "relevant |= selected" in filter_body, "Missing union of frontend scopes"
    for job_name, output in (
        ("homeschool-tutor-tests", "tutor"), ("demo-tests", "demo"),
        ("license-server-tests", "license"),
    ):
        assert jobs[AUDIT_JOB].get("needs") == jobs[job_name].get("needs")
        assert output in outputs
        assert jobs[job_name].get("if") == (
            f"needs.changes.outputs.{output} == 'true'"
        )


@pytest.mark.parametrize("job_name", [AUDIT_JOB, *TEST_JOBS])
def test_no_job_is_allowed_to_fail_softly(job_name: str) -> None:
    """A gate that cannot turn the workflow red is decoration."""
    job = _workflow()["jobs"][job_name]
    assert not job.get("continue-on-error"), f"{job_name} is continue-on-error"
    for step in job.get("steps", []):
        assert not step.get("continue-on-error"), (
            f"{job_name} step {step.get('name')!r} is continue-on-error"
        )


def test_every_npm_allowlist_entry_states_its_reason() -> None:
    """An exemption without a reason is a silenced gate.

    The gate script fails closed on this too; asserting it here is just
    cheaper feedback than discovering it when CI next runs.
    """
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    for entry in data.get("npm", []):
        for field in ("id", "package", "reason", "added"):
            assert entry.get(field), (
                f"npm allowlist entry {entry.get('id', entry)!r} is missing {field!r}"
            )
        assert len(entry["reason"]) > 120, (
            f"npm allowlist entry {entry['id']}'s reason is too short to be a "
            "reason — this file exists so a decision is recorded, not waived."
        )


def test_the_gate_and_the_allowlist_are_in_the_api_change_filter() -> None:
    """Otherwise this whole file never runs for an edit to either.

    `test.yml`'s filter computes `relevant=false` for a path it does not name
    and skips `api-tests`, which is the vacuous-guard trap
    `test_decision_register.py` documents. Read the real `grep -qE` pattern
    and require each path as a WHOLE alternative — a substring test would be
    satisfied by any sibling entry sharing a prefix.
    """
    lines = [
        ln for ln in TEST_WORKFLOW.read_text(encoding="utf-8").splitlines() if "grep -qE" in ln
    ]
    assert lines, "test.yml no longer has a `grep -qE` change filter"
    alternatives: set[str] = set()
    for line in lines:
        import re

        group = re.search(r"\^\((.*?)\)'", line)
        if group:
            alternatives.update(p.strip() for p in group.group(1).split("|"))
    assert alternatives, "could not parse test.yml's change-filter alternation"
    for needed in (r"\.github/audit-allowlist\.json", r"scripts/npm_audit_gate\.py"):
        assert needed in alternatives, (
            f"{needed} is not its own alternative in test.yml's change-filter "
            "pattern, so editing it skips api-tests and this guard never runs "
            f"for exactly that edit. Found: {sorted(a for a in alternatives if 'audit' in a or 'npm' in a)}"
        )
