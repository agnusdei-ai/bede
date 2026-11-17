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


def _desktop_by_os() -> dict[str, set[str]]:
    """The desktop rows only, keyed by runner. Since #826 one runner can carry
    several rows (macos-15 has a desktop row and an emulated mobile row), so
    folding every row into one entry per OS would let the last row silently
    overwrite the desktop one."""
    rows = [r for r in _matrix() if r.get("profile", "desktop") == "desktop"]
    by_os = {r["os"]: set(r["browsers"].split(",")) for r in rows}
    assert len(by_os) == len(rows), "two desktop rows on one runner would hide each other"
    return by_os


def test_chrome_and_edge_run_on_both_windows_and_mac():
    by_os = _desktop_by_os()
    # Windows and Mac are required; Ubuntu was added deliberately (owner
    # decision, #826). Any other desktop runner would need the same decision.
    assert {"windows-2022", "macos-15"} <= set(by_os) <= {"windows-2022", "macos-15", "ubuntu-24.04"}, by_os
    for os_name in ("windows-2022", "macos-15"):
        assert {"chrome", "msedge"} <= by_os[os_name], f"{os_name} lacks Chrome or Edge: {by_os[os_name]}"


def test_the_safari_engine_runs_only_on_mac_and_is_not_called_safari():
    by_os = _desktop_by_os()
    assert "webkit" in by_os["macos-15"]
    assert "webkit" not in by_os["windows-2022"]
    # Playwright's WebKit is the Safari engine, not Safari; nothing may claim otherwise.
    assert all("safari" not in b for r in _matrix() for b in r["browsers"].split(","))
    assert "NOT Safari itself" in WF.read_text(encoding="utf-8")


def test_runners_are_pinned_not_floating():
    for row in _matrix():
        assert not row["os"].endswith("-latest"), row["os"]


def test_evidence_is_about_one_fixed_sha():
    text = WF.read_text(encoding="utf-8")
    assert "^[0-9a-f]{40}$" in text
    assert re.search(r"fullmatch\(r\"\[0-9a-f\]\{40\}\"", RUNNER.read_text(encoding="utf-8"))
    assert "is not the candidate" in RUNNER.read_text(encoding="utf-8")


def test_parent_password_is_not_written_to_the_fixture():
    runner = RUNNER.read_text(encoding="utf-8")
    journeys = JOURNEYS.read_text(encoding="utf-8")

    assert '"parent_password": parent_password' not in runner
    assert 'JOURNEY_PARENT_PASSWORD=parent_password' in runner
    assert "process.env.JOURNEY_PARENT_PASSWORD" in journeys


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


_QUALIFICATION = ROOT / "scripts" / "qualification"


def _browser_scripts():
    return [p for p in _QUALIFICATION.rglob("*") if p.suffix in {".cjs", ".js", ".mjs"} and "node_modules" not in p.parts]


def test_no_browser_check_passes_an_async_predicate_to_waitForFunction():
    """Playwright's waitForFunction does not await an async predicate: the
    Promise it returns is truthy, so the wait succeeds at once and the check
    never looks (measured with Chromium on Playwright 1.56, and on 1.63,
    the version CI pins: an async predicate returning false resolved at once,
    the same predicate written synchronously timed out). A check written that way
    passes whatever the page is doing. Poll with evaluate() instead."""
    offenders = [
        str(p.relative_to(ROOT)) for p in _browser_scripts()
        if re.search(r"waitForFunction\(\s*async\b", p.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


def test_the_journeys_check_no_service_worker_is_left_in_control():
    """Bede's service worker is retired (docs/RELIABILITY.md). The old check
    waited for one to take control, which would now hang forever."""
    src = JOURNEYS.read_text(encoding="utf-8")
    assert "'no_service_worker_in_control'" in src
    assert "serviceWorker?.ready" not in src
    assert "service_worker_in_control'" not in src.replace("no_service_worker_in_control'", "")
