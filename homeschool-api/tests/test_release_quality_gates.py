"""
The release quality gate's prerequisite, pinned (docs/RELEASE_QUALITY_GATES.md).

`main` requires branches to be up to date before merging. That setting is a
sub-option of "require status checks to pass", and GitHub blocks a pull
request whose required check never reports — it waits on "Expected — waiting
for status to be reported" indefinitely rather than treating "did not run" as
"passed".

So every workflow named in the ruleset must START on every pull request. If
someone re-adds a `paths:` filter to one of their `pull_request` triggers to
save CI minutes, every PR that doesn't touch those paths becomes permanently
unmergeable — and it will look like GitHub is broken, not like a workflow
edit, because the PR shows a check that simply never arrives.

That is a slow, confusing, repo-wide failure caused by a two-line change
nobody would flag in review. Hence a test.

The workflows still skip their heavy jobs on irrelevant changes; they do it
with an internal `changes` job instead. A SKIPPED job satisfies a required
check. A job that never ran does not.
"""
import json
import pathlib

import pytest
import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_RULESET = _ROOT / ".github" / "rulesets" / "main-branch-protection.json"
_WORKFLOWS = _ROOT / ".github" / "workflows"


def _ruleset() -> dict:
    return json.loads(_RULESET.read_text())


def _required_contexts() -> set[str]:
    for rule in _ruleset()["rules"]:
        if rule["type"] == "required_status_checks":
            return {c["context"] for c in rule["parameters"]["required_status_checks"]}
    raise AssertionError("the ruleset declares no required_status_checks rule")


def _workflow(name: str) -> dict:
    # PyYAML parses the bare key `on:` as the boolean True (YAML 1.1), which
    # is why this is not simply doc["on"].
    doc = yaml.safe_load((_WORKFLOWS / name).read_text())
    doc["_triggers"] = doc.get("on", doc.get(True))
    return doc


def _workflows_providing_required_checks() -> dict[str, dict]:
    """Every workflow file that defines at least one required check."""
    required = _required_contexts()
    found = {}
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        doc = _workflow(path.name)
        if set(doc.get("jobs", {})) & required:
            found[path.name] = doc
    return found


# ── The gate itself ─────────────────────────────────────────────────────────

def test_the_ruleset_requires_branches_to_be_up_to_date():
    """`strict_required_status_checks_policy` IS "require branches to be up to
    date before merging". Without it the rest of the ruleset still passes
    review while the failure it exists to prevent stays wide open."""
    rule = next(r for r in _ruleset()["rules"] if r["type"] == "required_status_checks")
    assert rule["parameters"]["strict_required_status_checks_policy"] is True


def test_the_ruleset_targets_the_default_branch():
    assert "~DEFAULT_BRANCH" in _ruleset()["conditions"]["ref_name"]["include"]


def test_the_ruleset_is_active_rather_than_evaluate_only():
    """GitHub rulesets can be imported in "evaluate" mode, which reports what
    would have happened and blocks nothing — indistinguishable from an active
    gate unless you look."""
    assert _ruleset()["enforcement"] == "active"


def test_nobody_bypasses_the_gate():
    """A bypass actor is the quiet way a gate stops being one.

    An earlier draft of the ruleset carried an `actor_id: 5` RepositoryRole
    entry meant to read "repository admin", written from memory rather than
    checked against GitHub's role ids. That fails in the worse direction than
    it sounds: a wrong id does not necessarily error, it can grant standing
    bypass to a role nobody picked — and the ruleset still displays as
    active, so the gate reports enforced while someone walks through it.

    An empty list is unambiguous. An emergency merge is still available by
    disabling the ruleset, which is visible and audited, rather than by a
    permanent exemption nobody re-reads.
    """
    actors = _ruleset().get("bypass_actors", [])
    assert actors == [], (
        f"the ruleset grants bypass to {actors!r}. If that is genuinely "
        f"intended, verify the actor_id against GitHub's documented role ids "
        f"first — guessing it is how a gate silently stops applying."
    )


# ── The prerequisite ────────────────────────────────────────────────────────

def test_every_required_check_is_defined_by_some_workflow():
    """A required context with no job behind it can never report, so it blocks
    every PR forever. Catches a renamed or deleted job."""
    defined = {job for doc in _workflows_providing_required_checks().values() for job in doc["jobs"]}
    missing = _required_contexts() - defined
    assert not missing, f"required checks with no job to produce them: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(_workflows_providing_required_checks()))
def test_a_required_workflow_starts_on_every_pull_request(name):
    """The failure this whole file exists for. A `paths:` filter here means
    the workflow does not start on an unrelated PR, the required check never
    reports, and that PR can never be merged by anyone."""
    trigger = _workflow(name)["_triggers"]["pull_request"]

    assert trigger is None or "paths" not in trigger, (
        f"{name} filters its pull_request trigger by path. Every check it "
        f"provides is required on main, so a PR that touches none of those "
        f"paths would wait forever on a status that never arrives. Skip the "
        f"work with the `changes` job instead — a skipped job satisfies a "
        f"required check. See docs/RELEASE_QUALITY_GATES.md."
    )


@pytest.mark.parametrize("name", sorted(_workflows_providing_required_checks()))
def test_the_skip_gate_exists_and_every_required_job_hangs_off_it(name):
    """The other half: dropping the paths filter without the internal gate
    would run the full suite on every docs typo. Both halves have to hold, so
    both are asserted."""
    doc = _workflow(name)
    jobs = doc["jobs"]
    assert "changes" in jobs, f"{name} has no `changes` gate job"

    for job_name in _required_contexts() & set(jobs):
        job = jobs[job_name]
        assert job.get("needs") == "changes", f"{name}:{job_name} does not depend on `changes`"
        assert "needs.changes.outputs.relevant" in str(job.get("if", "")), (
            f"{name}:{job_name} is not conditioned on the `changes` output"
        )


def test_the_gate_job_itself_is_never_skipped(name="changes"):
    """`changes` must have no `if:` of its own — a gate that can be skipped
    leaves its dependents skipped too, which reads as green."""
    for wf_name, doc in _workflows_providing_required_checks().items():
        assert "if" not in doc["jobs"][name], f"{wf_name}: the `changes` job is conditional"
