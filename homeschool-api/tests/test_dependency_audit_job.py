"""The dependency audit is a hard gate that cannot skip the test suite.

`pip-audit` used to run as step 5 of `api-tests`, immediately before
`Run tests`. A failing audit therefore left `Run tests` **skipped**, and the
thing that fails an audit is an advisory published by a stranger rather than
a change a contributor made.

That is not hypothetical. It happened twice on 2026-10-01:

* urllib3 CVE-2026-97687/97688/97689 took the backend suite down in the
  morning, so `main` had no test coverage at all while two PRs (#511's Music
  engine and #512) had already merged during a GitHub Actions billing outage
  with no gate having run on either.
* pypdf CVE-2026-102999 was published in the two hours between PR #513's own
  green run and its merge commit, taking `main`'s suite down a second time
  on an identical tree.

`main` IS the release (docs/RELEASE_QUALITY_GATES.md), so for both windows
nothing could distinguish a real regression from a third party's publication.

**This does not weaken the gate.** The audit still fails the workflow, and
the standing rule is unchanged: a red audit means upgrade the pin, or record
why the advisory is unreachable in `.github/audit-allowlist.json` — never
delete the step (see `.github/workflows/frontend-tests.yml`'s account of
#296, where deleting an audit gate took this repo from one blocked PR to
zero vulnerability visibility). What the split changes is only that a
dependency advisory can no longer hide a test regression behind it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml"

AUDIT_JOB = "dependency-audit"
TEST_JOB = "api-tests"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step_names(job: dict) -> list[str]:
    return [s.get("name", "") for s in job.get("steps", [])]


def _runs(job: dict) -> str:
    """Every `run:` body in a job, concatenated."""
    return "\n".join(s.get("run", "") for s in job.get("steps", []))


def test_the_audit_is_its_own_job() -> None:
    jobs = _workflow()["jobs"]
    assert AUDIT_JOB in jobs, (
        f"{AUDIT_JOB} is gone. The audit must not move back inside "
        f"{TEST_JOB}: a failing audit would skip the whole backend suite "
        "again, which is the defect this job was split out to fix."
    )


def test_the_test_job_runs_no_audit_step() -> None:
    """The point of the split, stated as the assertion.

    Any audit step in `api-tests` sits ahead of `Run tests` and can skip it.
    """
    job = _workflow()["jobs"][TEST_JOB]
    offenders = [n for n in _step_names(job) if "audit" in n.lower()]
    assert not offenders, (
        f"{TEST_JOB} has an audit step again ({offenders!r}). A failing audit "
        "there skips 'Run tests', so an advisory published by a stranger "
        "takes the backend suite down with it."
    )
    assert "pip-audit" not in _runs(job), (
        f"{TEST_JOB} invokes pip-audit in a step body, which has the same "
        "effect whatever the step is called."
    )


def test_the_test_job_still_runs_the_tests() -> None:
    job = _workflow()["jobs"][TEST_JOB]
    assert "pytest tests/" in _runs(job), (
        f"{TEST_JOB} no longer runs the backend suite at all."
    )


def test_the_audit_still_covers_both_lockfiles() -> None:
    """Splitting it out must not quietly narrow what it audits.

    A dev-only CVE still executes on the runner against this repo's code,
    which is why the dev lockfile is audited too.
    """
    body = _runs(_workflow()["jobs"][AUDIT_JOB])
    for lockfile in ("requirements.lock.txt", "requirements-dev.lock.txt"):
        assert re.search(rf"pip-audit -r {re.escape(lockfile)}", body), (
            f"{AUDIT_JOB} no longer audits {lockfile}."
        )


def test_the_audit_still_reads_the_allowlist() -> None:
    """The escape hatch stays the recorded one, not a silently widened flag."""
    body = _runs(_workflow()["jobs"][AUDIT_JOB])
    assert "audit-allowlist.json" in body, (
        f"{AUDIT_JOB} stopped reading .github/audit-allowlist.json, so "
        "exceptions would no longer have to be recorded with a reason."
    )


def test_the_audit_is_gated_on_the_same_change_filter() -> None:
    """It must run exactly when the suite it accompanies runs."""
    jobs = _workflow()["jobs"]
    assert jobs[AUDIT_JOB].get("needs") == jobs[TEST_JOB].get("needs")
    assert jobs[AUDIT_JOB].get("if") == jobs[TEST_JOB].get("if")


@pytest.mark.parametrize("job_name", [AUDIT_JOB, TEST_JOB])
def test_neither_job_is_allowed_to_fail_softly(job_name: str) -> None:
    """A gate that cannot turn the workflow red is decoration.

    `continue-on-error` is the one-line way to make this whole change
    pointless, so it is refused explicitly rather than trusted not to appear.
    """
    job = _workflow()["jobs"][job_name]
    assert not job.get("continue-on-error"), f"{job_name} is continue-on-error"
    for step in job.get("steps", []):
        assert not step.get("continue-on-error"), (
            f"{job_name} step {step.get('name')!r} is continue-on-error"
        )
