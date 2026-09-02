"""Guards for the per-PR lockfile gate itself.

`scripts/check_lockfile_consistency.py` replaced a live-resolve check that had
turned red four recorded times on upstream publishes with nothing in this
repository having changed (`docs/DECISIONS.md` entry 12). The replacement is
offline and deterministic, and these tests pin the three ways it could quietly
stop being worth having:

* it stops catching a raised floor the lockfile does not honour — the silent
  defect it exists for;
* it starts reporting a pin it simply cannot parse as absent — the false
  positive its first run actually produced, over extras;
* CI stops running it, or runs the currency check on every pull request again.

The checker is invoked as a module against temporary files rather than by
reading its source, so what is asserted is behaviour.
"""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "check_lockfile_consistency.py"
_WORKFLOW = _ROOT.parent / ".github" / "workflows" / "test.yml"

_spec = importlib.util.spec_from_file_location("_lockfile_gate", _SCRIPT)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _write(tmp_path: Path, source: str, lock: str) -> tuple[Path, Path]:
    src = tmp_path / "requirements.in"
    lockfile = tmp_path / "requirements.lock.txt"
    src.write_text(source)
    lockfile.write_text(lock)
    return src, lockfile


# ── The defect this gate exists for ─────────────────────────────────────────

def test_a_raised_floor_the_lockfile_does_not_honour_is_caught(tmp_path):
    """The silent one. Nothing errors, nothing is missing, and the version the
    floor was raised to rule out is exactly what ships."""
    src, lock = _write(tmp_path, "anthropic>=2.0.0\n", "anthropic==1.2.0\n")
    problems = gate.check(src, lock)
    assert len(problems) == 1
    assert "anthropic" in problems[0] and "1.2.0" in problems[0]


def test_a_requirement_absent_from_the_lockfile_is_caught(tmp_path):
    src, lock = _write(tmp_path, "flask>=3.0.0\n", "anthropic==1.2.0\n")
    problems = gate.check(src, lock)
    assert len(problems) == 1
    assert "absent" in problems[0]


def test_a_satisfied_floor_passes(tmp_path):
    src, lock = _write(tmp_path, "anthropic>=0.40.0\n", "anthropic==1.2.0\n")
    assert gate.check(src, lock) == []


# ── The false positive its first run produced ───────────────────────────────

@pytest.mark.parametrize("pin", [
    "uvicorn[standard]==0.52.4",
    "sqlalchemy[asyncio]==2.0.52",
])
def test_a_pin_carrying_extras_is_recognised(tmp_path, pin):
    """pip-compile carries a requirement's extras into the pinned name. The
    first cut of the name pattern did not allow the bracket, so it reported
    both of this repo's real extras-bearing requirements as missing from a
    lockfile that pins them — a gate that fails on a correct tree gets
    disabled, which is worse than no gate."""
    name = pin.split("[")[0]
    src, lock = _write(tmp_path, f"{name}[x]>=0.1\n", pin + " \\\n    --hash=sha256:abc\n")
    assert gate.check(src, lock) == []


def test_names_are_compared_canonically(tmp_path):
    """`Faster-Whisper`, `faster_whisper` and `faster-whisper` are one package."""
    src, lock = _write(tmp_path, "Faster_Whisper>=1.0.0\n", "faster-whisper==1.3.0\n")
    assert gate.check(src, lock) == []


def test_comments_options_and_includes_are_not_treated_as_requirements(tmp_path):
    src, lock = _write(
        tmp_path,
        "# a comment\n-r requirements.in\n--index-url https://example.invalid\n\nanthropic>=1.0\n",
        "anthropic==1.2.0\n",
    )
    assert gate.check(src, lock) == []


# ── An empty parse is not a pass ────────────────────────────────────────────

def test_a_lockfile_it_cannot_parse_at_all_fails_rather_than_passing_vacuously(tmp_path):
    """The failure mode of every scanner in this repository: a pattern that
    stops matching reports success. Same posture as
    scripts/check_live_site_headers.sh's own empty-parse refusal."""
    src, lock = _write(tmp_path, "anthropic>=1.0\n", "# nothing pinned here at all\n")
    problems = gate.check(src, lock)
    assert problems and "not currently checking anything" in problems[0]


# ── The real tree, and the wiring ───────────────────────────────────────────

def test_the_committed_lockfiles_actually_satisfy_the_committed_requirements():
    """Runs the gate exactly as CI does. This is the test-the-invocation half:
    the cases above prove the function works on fixtures, this proves the
    script runs and agrees about the files it is really pointed at."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_runs_the_offline_gate_and_not_the_live_resolve():
    """The whole point of entry 12's re-decision. If the per-PR job goes back
    to check_lockfile_freshness.sh, every pull request is hostage to PyPI
    again — and the symptom is a red check nobody can fix from the diff."""
    workflow = _WORKFLOW.read_text()
    job = workflow[workflow.index("  lockfile-freshness:"):]
    job = job[: job.index("\n  demo-concurrency-test:")]

    # Comments are stripped first. The job's own comment block explains at
    # length what it stopped running and why, so a scan over the raw text
    # matches the prose and fails against a correct workflow — the same
    # comment-matching false positive test_release_posture.py records, and
    # this test produced it on its first run.
    steps = "\n".join(
        line for line in job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "check_lockfile_consistency.py" in steps
    assert "check_lockfile_freshness.sh" not in steps, (
        "the per-PR gate resolves against PyPI again — see docs/DECISIONS.md "
        "entry 12's 2026-09-02 amendment"
    )


def test_lockfile_refresh_is_named_in_the_ci_change_filter():
    """The reason test_decision_register.py already documents: test.yml's
    filter computes relevant=false for a path it does not name, skips
    api-tests, and never runs the guard written for exactly that change. This
    file reads lockfile-refresh.yml, so a PR re-enabling its schedule and
    touching nothing else would sail past the test above."""
    workflow = _WORKFLOW.read_text()
    pattern = next(
        line for line in workflow.splitlines() if "grep -qE" in line
    )
    assert r"lockfile-refresh\.yml" in pattern, (
        "a PR that only edits .github/workflows/lockfile-refresh.yml would "
        "skip the suite that guards it"
    )


def test_the_currency_check_still_exists_for_attended_use():
    """Narrowing the gate is not deleting the property. The live resolve is
    still how a refresh is done; it just is not a per-PR gate."""
    assert (_ROOT / "scripts" / "check_lockfile_freshness.sh").exists()
    refresh = _ROOT.parent / ".github" / "workflows" / "lockfile-refresh.yml"
    assert refresh.exists()
    text = refresh.read_text()
    assert "workflow_dispatch" in text
    assert not re.search(r"^\s*schedule:", text, re.MULTILINE), (
        "the daily refresh is back on — it was switched off because refreshing "
        "~110 packages into the deployed backend was destabilising it"
    )
