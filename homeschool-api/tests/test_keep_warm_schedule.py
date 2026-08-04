"""
The demo's keep-warm window is a COST decision, and it now lives in two
files at once.

Render's free plan grants 750 instance-hours per month across the whole
workspace. A 31-day month is 744 hours. So a keep-warm that actually worked
around the clock would consume the entire allowance and get the service
suspended for the rest of the month — strictly worse than the cold starts it
was meant to prevent. The 12:00-23:59 UTC window is what keeps the arithmetic
safe (~367 hours/month), and it is the single most important property of this
whole mechanism.

`workers/keep-warm/` (Cloudflare, reliable) is replacing
`.github/workflows/keep-demo-warm.yml` (GitHub Actions, which throttles
scheduled runs to roughly hourly). Both are live during the cutover, because
merging cannot create the Cloudflare project — see docs/DEMO_HOSTING.md — and
deleting the workflow first would leave no keep-warm at all. Two copies of one
fact is exactly the drift this repository's own standing rule says to pin with
a test rather than trust someone to remember, so:

  - both must cover the same hours
  - neither may creep to 24/7

Delete this file's `GITHUB_WORKFLOW` half when the workflow is retired; the
24/7 assertions stay.
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GITHUB_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "keep-demo-warm.yml"
WORKER_CONFIG = REPO_ROOT / "workers" / "keep-warm" / "wrangler.jsonc"

# 750 free instance-hours per month, against 744 hours in a 31-day month.
FREE_TIER_MONTHLY_HOURS = 750
LONGEST_MONTH_HOURS = 31 * 24


def _strip_jsonc(text: str) -> str:
    """wrangler.jsonc allows // comments; json.loads does not."""
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


def _cron_hour_field(expression: str) -> str:
    """The hour field of a 5-field cron expression."""
    return expression.split()[1]


def _hours_covered(hour_field: str) -> int:
    if hour_field == "*":
        return 24
    start, _, end = hour_field.partition("-")
    return int(end) - int(start) + 1


def _worker_crons() -> list[str]:
    config = json.loads(_strip_jsonc(WORKER_CONFIG.read_text()))
    return config["triggers"]["crons"]


def _workflow_crons() -> list[str]:
    return re.findall(r"cron:\s*'([^']+)'", GITHUB_WORKFLOW.read_text())


def test_the_worker_defines_exactly_one_schedule():
    assert len(_worker_crons()) == 1


@pytest.mark.parametrize("source", ["worker", "workflow"])
def test_neither_keep_warm_runs_around_the_clock(source):
    """The load-bearing assertion. An unrestricted hour field would keep the
    service awake ~744 hours a month against a 750-hour allowance shared with
    every other free service in the workspace, and Render suspends free
    services for the remainder of the month once it is spent."""
    crons = _worker_crons() if source == "worker" else _workflow_crons()
    assert crons, f"{source} has no cron schedule at all"
    for expression in crons:
        hours = _hours_covered(_cron_hour_field(expression))
        assert hours < 24, (
            f"{source} cron {expression!r} covers all 24 hours — that is "
            f"~{LONGEST_MONTH_HOURS}h/month against a {FREE_TIER_MONTHLY_HOURS}h "
            f"allowance. See docs/DEMO_HOSTING.md before widening this."
        )
        monthly_hours = hours * 31
        assert monthly_hours < FREE_TIER_MONTHLY_HOURS, (
            f"{source} cron {expression!r} would consume ~{monthly_hours}h/month, "
            f"over the {FREE_TIER_MONTHLY_HOURS}h free allowance"
        )


def test_the_two_keep_warms_cover_the_same_window():
    """While both are live, one of them being widened or narrowed alone would
    silently change the cost envelope or leave a coverage gap."""
    worker_hours = _cron_hour_field(_worker_crons()[0])
    workflow_hours = {_cron_hour_field(e) for e in _workflow_crons()}
    assert workflow_hours == {worker_hours}, (
        f"keep-warm windows disagree: worker covers {worker_hours}, "
        f"workflow covers {sorted(workflow_hours)}"
    )


def test_the_worker_pings_often_enough_to_beat_renders_idle_timer():
    """Render sleeps a free service after 15 minutes idle, and Cloudflare
    states cron triggers may be delayed by a few minutes. A cadence at or
    near 15 would let a single delayed run drop the service."""
    minute_field = _worker_crons()[0].split()[0]
    assert minute_field.startswith("*/"), f"expected a step cadence, got {minute_field!r}"
    every_minutes = int(minute_field[2:])
    assert every_minutes <= 5, (
        f"pinging every {every_minutes} minutes leaves too little margin against "
        "Render's 15-minute idle timer once cron jitter is allowed for"
    )
