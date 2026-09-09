"""
The demo watchdog must not rely on `playwright install --with-deps`.

`--with-deps` runs `apt` on the GitHub runner. A transient upstream apt index
mismatch (seen on the Google Chrome repo) can fail the watchdog before the
synthetic journey even starts, producing false outage alarms.
"""
from pathlib import Path

import yaml


_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "demo-watchdog.yml"


def _workflow() -> dict:
    doc = yaml.safe_load(_WORKFLOW.read_text())
    # PyYAML may parse bare `on` as True.
    doc["_triggers"] = doc.get("on", doc.get(True))
    return doc


def test_demo_watchdog_installs_playwright_without_with_deps():
    steps = _workflow()["jobs"]["check"]["steps"]
    install_step = next(s for s in steps if s.get("name") == "Install Playwright (chromium only)")
    run = install_step["run"]

    assert "npx playwright install chromium" in run
    assert "--with-deps" not in run
