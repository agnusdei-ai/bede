"""Static regression guard for the privileged event-driven merge gate."""

from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "bede-event-driven-merge.yml"
)
TEXT = WORKFLOW.read_text(encoding="utf-8")


def test_event_triggered_not_cron_polling():
    assert "workflow_run:" in TEXT
    assert "pull_request_target:" in TEXT
    assert "types: [completed]" in TEXT
    assert "schedule:" not in TEXT
    for workflow in (
        "Backend regression tests",
        "Frontend regression tests",
        "CodeQL analysis",
    ):
        assert workflow in TEXT


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
    assert "github.event.workflow_run.event == 'pull_request'" in TEXT
    assert "createWorkflowDispatch" in TEXT
    assert "deploy-demo.yml" not in TEXT
    assert "pilot GO" in TEXT
