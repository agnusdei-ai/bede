"""Self-contained smoke tests for the CI SARIF quality gate."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_codeql_sarif import check


def _report(root: Path, level: str | None) -> None:
    results = [] if level is None else [{"level": level, "ruleId": "security-test", "message": {"text": "synthetic"}}]
    (root / "test.sarif").write_text(json.dumps({"runs": [
        {"tool": {"driver": {"rules": []}}, "results": results}
    ]}))


def test_missing_results_fails_closed():
    with TemporaryDirectory() as folder:
        assert check(Path(folder)) == 2


def test_error_fails_warning_passes():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        _report(root, "error")
        assert check(root) == 1
        _report(root, "warning")
        assert check(root) == 0
        _report(root, None)
        assert check(root) == 0


def test_invalid_sarif_fails_closed():
    with TemporaryDirectory() as folder:
        (Path(folder) / "bad.sarif").write_text("{")
        assert check(Path(folder)) == 2
