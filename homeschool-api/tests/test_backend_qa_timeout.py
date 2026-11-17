"""The backend QA step must give the full suite room to finish.

scripts/qa/runner.py kills a test command after --timeout seconds (default
900) and reports it as a failure. The full backend suite reached about 14
minutes on a hosted runner, so a slower runner killed a suite that was
passing (#851, Backend regression tests run 43791656138, "timed out after 900
seconds"). The step passes 1800. A limit at or below the suite's own run time
turns runner speed into a red check, which is exactly what a timeout must not
do.
"""
import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/test.yml"
MIN_SECONDS = 1800


def _backend_runner_step() -> str:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    for job in jobs.values():
        for step in job.get("steps", []):
            run = str(step.get("run", ""))
            if "scripts/qa/runner.py" in run and "--scope backend" in run:
                return run
    raise AssertionError("no backend QA runner step in test.yml")


def test_the_backend_suite_gets_at_least_thirty_minutes():
    run = _backend_runner_step()
    match = re.search(r"--timeout\s+(\d+)", run)
    assert match, "the backend QA step relies on the runner's 900 s default"
    assert int(match.group(1)) >= MIN_SECONDS


def test_the_timeout_stays_within_what_the_runner_accepts():
    run = _backend_runner_step()
    assert int(re.search(r"--timeout\s+(\d+)", run).group(1)) <= 3600
