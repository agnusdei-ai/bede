"""Static regression guard for the privileged event-driven merge gate.

Automatic merging is DELIBERATELY PAUSED during synthetic qualification
(owner decision, 2026-10-15, commit 280e8d3). This guard tests that paused
policy rather than being deleted: while the workflow carries the pause
marker it must be impossible to run automatically or manually, a manual
trigger stays declared, and every merge-safety control stays intact for the
day the owner approves resuming. Resuming is a human decision; when the
marker is removed, the active-state test below takes over and requires the
real event triggers and the pull-request-origin guard back.

Assertions read the PARSED workflow, so a trigger left in a comment cannot
satisfy them.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "bede-event-driven-merge.yml"
)
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC = yaml.safe_load(TEXT)
# PyYAML reads the bare key `on` as boolean True.
TRIGGERS = DOC.get("on", DOC.get(True)) or {}
JOB_IF = DOC["jobs"]["guarded-merge"]["if"]

PAUSE_MARKER = "# Paused at owner's request"
PAUSED = PAUSE_MARKER in TEXT
AUTOMATIC_TRIGGERS = ("workflow_run", "pull_request_target", "push", "schedule")


@pytest.mark.skipif(not PAUSED, reason="merge automation has been resumed")
def test_paused_merge_automation_cannot_run():
    # No automatic trigger of any kind while paused.
    for trigger in AUTOMATIC_TRIGGERS:
        assert trigger not in TRIGGERS, f"{trigger} must not be a trigger while paused"
    # The manual trigger is preserved, so the workflow stays visible and
    # resumable without being re-created.
    assert set(TRIGGERS) == {"workflow_dispatch"}, TRIGGERS
    # And the job is inert even under manual dispatch.
    assert JOB_IF is False, JOB_IF


@pytest.mark.skipif(PAUSED, reason="merge automation is deliberately paused")
def test_resumed_automation_is_event_triggered_not_cron_polling():
    assert "workflow_run" in TRIGGERS
    assert "pull_request_target" in TRIGGERS
    assert TRIGGERS["workflow_run"]["types"] == ["completed"]
    for workflow in (
        "Backend regression tests",
        "Frontend regression tests",
        "CodeQL analysis",
    ):
        assert workflow in TRIGGERS["workflow_run"]["workflows"]
    assert "github.event.workflow_run.event == 'pull_request'" in str(JOB_IF)


def test_never_polls_on_a_schedule():
    assert "schedule" not in TRIGGERS


def test_merge_is_opt_in_exact_sha_and_review_gated():
    for control in (
        "release:automerge",
        "pr.draft",
        "pr.head.sha",
        "pr.mergeable_state",
        "review.commit_id === sha",
        "minApprovals = sensitive ? 2 : 1",
        "head_sha: sha",
        "merge_method: 'squash'",
        "pull_number: n, sha",
    ):
        assert control in TEXT


def test_privileged_workflow_does_not_run_untrusted_code_or_deploy():
    assert "actions/checkout@" not in TEXT
    assert "github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3" in TEXT
    assert "createWorkflowDispatch" in TEXT
    assert "deploy-demo.yml" not in TEXT
    assert "pilot GO" in TEXT
