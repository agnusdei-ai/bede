"""The defect-only Python lint gate exists, runs unfiltered, and is clean.

Added with ruff.toml after an audit found an undefined name (a NameError on
an error path no test drove) and a twice-defined function in core/.
"""
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "python-lint.yml"


def test_the_workflow_runs_on_every_pull_request_without_a_path_filter():
    wf = yaml.safe_load(WORKFLOW.read_text())
    on = wf.get("on", wf.get(True))
    assert "pull_request" in on
    assert not (on.get("pull_request") or {}).get("paths")
    steps = " ".join(str(s.get("run", "")) for s in wf["jobs"]["ruff"]["steps"])
    assert "ruff check ." in steps
    assert "ruff==" in steps  # pinned, so a ruff release cannot turn it red


def test_the_rules_include_undefined_names_and_redefinitions():
    cfg = (ROOT / "ruff.toml").read_text()
    for rule in ('"F82"', '"F811"', '"E9"'):
        assert rule in cfg


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_the_tree_is_clean_and_the_gate_catches_an_undefined_name(tmp_path):
    assert subprocess.run(["ruff", "check", "."], cwd=ROOT).returncode == 0
    bad = tmp_path / "bad.py"
    bad.write_text("def f():\n    return logger\n")
    result = subprocess.run(["ruff", "check", "--config", str(ROOT / "ruff.toml"), str(bad)],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1 and "F821" in result.stdout


def test_the_stricter_rules_are_scoped_to_production_code():
    cfg = (ROOT / "ruff.toml").read_text()
    for rule in ("F401", "B904", "B905", "S110", "S112"):
        assert f'"{rule}"' in cfg


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
@pytest.mark.parametrize("where, caught", [
    ("homeschool-api/services", True),
    ("homeschool-api/routers", True),
    ("homeschool-api/tests", False),
])
def test_a_silenced_exception_fails_only_in_production_code(where, caught):
    """Planted inside the repository, because the per-file scoping is by
    path; a file in tmp_path would match neither side."""
    probe = ROOT / where / "_lint_gate_probe.py"
    probe.write_text("def f():\n    try:\n        return 1\n    except Exception:\n        pass\n")
    try:
        result = subprocess.run(["ruff", "check", str(probe)], cwd=ROOT,
                                capture_output=True, text=True)
    finally:
        probe.unlink()
    assert (result.returncode == 1 and "S110" in result.stdout) is caught
