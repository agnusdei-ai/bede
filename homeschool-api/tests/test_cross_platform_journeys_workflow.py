"""The cross-platform browser journey workflow covers what it says it covers.

`.github/workflows/cross-platform-browser-journeys.yml` is the only CI path
that drives real Windows and macOS browsers through the app. The owner's
scope (#599, 2026-11-08) asks for Google Chrome and Microsoft Edge on BOTH
Windows and Mac, and the Safari engine on Mac. A matrix entry quietly
dropped, or a runner moved to a floating label, would leave the evidence
claiming a browser nobody ran, so the shape is pinned here.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "cross-platform-browser-journeys.yml"
JOURNEYS = ROOT / "scripts" / "qualification" / "browser_journeys" / "journeys.cjs"
RUNNER = ROOT / "scripts" / "qualification" / "browser_journeys" / "run_journeys.py"


def _matrix() -> list[dict]:
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    return data["jobs"]["journeys"]["strategy"]["matrix"]["include"]


def test_chrome_and_edge_run_on_both_windows_and_mac():
    by_os = {row["os"]: set(row["browsers"].split(",")) for row in _matrix()}
    assert set(by_os) == {"windows-2022", "macos-15"}, by_os
    for os_name, browsers in by_os.items():
        assert {"chrome", "msedge"} <= browsers, f"{os_name} lacks Chrome or Edge: {browsers}"


def test_the_safari_engine_runs_only_on_mac_and_is_not_called_safari():
    by_os = {row["os"]: set(row["browsers"].split(",")) for row in _matrix()}
    assert "webkit" in by_os["macos-15"]
    assert "webkit" not in by_os["windows-2022"]
    # Playwright's WebKit is the Safari engine, not Safari; nothing may claim otherwise.
    assert all("safari" not in b for bs in by_os.values() for b in bs)
    assert "NOT Safari itself" in WF.read_text(encoding="utf-8")


def test_runners_are_pinned_not_floating():
    for row in _matrix():
        assert not row["os"].endswith("-latest"), row["os"]


def test_evidence_is_about_one_fixed_sha():
    text = WF.read_text(encoding="utf-8")
    assert "^[0-9a-f]{40}$" in text
    assert re.search(r"fullmatch\(r\"\[0-9a-f\]\{40\}\"", RUNNER.read_text(encoding="utf-8"))
    assert "is not the candidate" in RUNNER.read_text(encoding="utf-8")


def test_the_journeys_launch_the_installed_branded_browsers():
    js = JOURNEYS.read_text(encoding="utf-8")
    assert "chromium.launch({ channel: name })" in js
    assert "pw.webkit.launch()" in js
    # Every browser runs at the same time against one service.
    assert "Promise.all(F.browsers.flatMap" in js


def _env_values(env) -> list[str]:
    return [str(v) for v in (env or {}).values()]


def test_no_workflow_uses_the_runner_context_where_github_forbids_it():
    """GitHub rejects `runner.*` in workflow- and job-level `env` when it
    parses the file, so a dispatch fails with 422 before anything runs. The
    YAML still loads cleanly, which is how this workflow first shipped with
    `${{ runner.temp }}` in its job env and only failed at dispatch. Steps
    may use it; these two levels may not."""
    offenders = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        if any("runner." in v for v in _env_values(data.get("env"))):
            offenders.append(f"{wf.name}: workflow env")
        for name, job in (data.get("jobs") or {}).items():
            if any("runner." in v for v in _env_values((job or {}).get("env"))):
                offenders.append(f"{wf.name}: jobs.{name}.env")
    assert not offenders, offenders
