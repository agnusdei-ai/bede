"""Release qualification runs one Playwright version, and it is the one whose
WebKit does not crash on Bede's reload path.

Playwright 1.56.0 bundles WebKit 26.0 (build 2215). Its Navigation API does not
record `history.pushState`, so a page reloaded twice after a client-side route
change hits a release assertion in `WebCore::Navigation::initializeForNewWindow`
(minimal reproduction: 3/3 crashes; Bede's own journey: crashed in every slot).
Playwright 1.63.0 bundles WebKit 26.6 (build 2359), where the same sequences ran
0/3 and the Navigation API records history correctly. See
docs/release/WEBKIT_RELOAD_CRASH.md.

So every place that qualifies a release pins the same version: one fact, written
in several workflow files, checked here rather than trusted. The diagnosis
workflow's `minimal` job is the one deliberate exception: it keeps 1.56.0 beside
the pin, because it exists to show the defect still reproduces where it did.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WF = REPO / ".github/workflows"
PINNED = "1.63.0"
REPRODUCING = "1.56.0"

# Every file that installs Playwright to qualify a release, and how it spells the pin.
PIN_SITES = {
    WF / "cross-platform-browser-journeys.yml": r"PLAYWRIGHT_VERSION: '([\d.]+)'",
    WF / "webkit-reload-diagnosis.yml": r"PLAYWRIGHT_VERSION: '([\d.]+)'",
    WF / "capacity.yml": r"PLAYWRIGHT_VERSION: '([\d.]+)'",
    WF / "qualification.yml": r"(?:playwright_version:\n(?:\s+\w+:.*\n)*?\s+default: |inputs\.playwright_version \|\| ')(\d+\.\d+\.\d+)",
    WF / "macos-installer-ui.yml": r"playwright==([\d.]+)",
    WF / "build-bede-operator.yml": r"playwright==([\d.]+)",
    REPO / "scripts/mac/collect-g3-evidence.sh": r"playwright@([\d.]+)",
    REPO / "docs/SAMPLE_QUALIFICATION.md": r"\| `playwright_version` \| `([\d.]+)`",
}

_ANY_PIN = re.compile(r"playwright(?:==|@)(\d+\.\d+\.\d+)|PLAYWRIGHT_VERSION: '(\d+\.\d+\.\d+)'")


@pytest.mark.parametrize("path", sorted(PIN_SITES), ids=lambda p: p.name)
def test_every_qualification_site_pins_the_reliable_version(path):
    found = re.findall(PIN_SITES[path], path.read_text())
    assert found, f"{path.name}: no Playwright pin found; the pattern or the file moved"
    assert set(found) == {PINNED}, f"{path.name} pins {sorted(set(found))}, expected {PINNED}"


def test_no_other_workflow_or_script_pins_a_different_version():
    """A new workflow that installs Playwright must join PIN_SITES, not drift."""
    files = list(WF.glob("*.yml")) + list((REPO / "scripts").rglob("*.sh"))
    stray = {}
    for f in files:
        for a, b in _ANY_PIN.findall(f.read_text()):
            v = a or b
            if v != PINNED:
                stray.setdefault(f.name, set()).add(v)
    assert not stray, f"Playwright pinned to a version other than {PINNED}: {stray}"


def test_the_minimal_reproduction_still_covers_the_crashing_build():
    d = yaml.safe_load((WF / "webkit-reload-diagnosis.yml").read_text())
    versions = d["jobs"]["minimal"]["strategy"]["matrix"]["playwright"]
    assert REPRODUCING in versions and PINNED in versions


def test_the_crash_record_names_the_pinned_build():
    doc = (REPO / "docs/release/WEBKIT_RELOAD_CRASH.md").read_text()
    assert f"Playwright {PINNED}" in doc and "WebKit 26.6" in doc and "build 2359" in doc


def test_the_change_filter_reaches_this_guard():
    line = next(l for l in (WF / "test.yml").read_text().splitlines() if "grep -qE" in l)
    alternatives = line.split("'", 2)[1].strip("^()").split("|")
    for alt in ("\\.github/workflows/", "scripts/mac/collect-g3-evidence\\.sh",
                "docs/SAMPLE_QUALIFICATION\\.md", "docs/release/WEBKIT_RELOAD_CRASH\\.md"):
        assert alt in alternatives, alt
