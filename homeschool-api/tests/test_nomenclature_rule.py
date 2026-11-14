"""The banned-nomenclature guard (scripts/check_nomenclature.sh) works and
is wired to run. Owner rule 2026-11-14."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_nomenclature.sh"
WORD = "synth" + "etic"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs the git checkout")


def _run():
    return subprocess.run([str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)


def test_the_repository_is_clean():
    result = _run()
    assert result.returncode == 0, result.stdout


def test_it_fails_on_a_tracked_file_that_uses_a_banned_word(tmp_path):
    probe = ROOT / "nomenclature_probe.txt"
    probe.write_text(f"a {WORD.capitalize()} learner\n")
    try:
        subprocess.run(["git", "add", "-N", probe.name], cwd=ROOT, check=True)
        result = _run()
        assert result.returncode == 1 and probe.name in result.stdout
    finally:
        subprocess.run(["git", "rm", "-q", "--cached", "-f", probe.name], cwd=ROOT, check=False)
        probe.unlink(missing_ok=True)


def test_only_the_intelligence_phrase_is_exempt_in_the_notices():
    notice = ROOT / "homeschool-api" / "data" / "school_data_notice.txt"
    assert ("artifi" + "cial intelligence") in notice.read_text()
    script = SCRIPT.read_text()
    assert "intelligence//Ig" in script and script.count("exclude)${notices") == 2


def test_the_workflow_runs_it_on_every_change():
    workflow = (ROOT / ".github" / "workflows" / "nomenclature.yml").read_text()
    assert "scripts/check_nomenclature.sh" in workflow
    assert "paths" not in workflow and "pull_request:" in workflow
