"""The WebKit reload diagnosis: a dispatch-only workflow plus PRESTATE logging.

It exists to separate "WebKit crashes" from "the third child's path crashes"
(release-repair cycle webkit-1). It must never become a gate, never upload a
raw crash report, never drift from the gate's own steps, and its logging must
never change a journey's result.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DIAG = REPO / ".github/workflows/webkit-reload-diagnosis.yml"
GATE = REPO / ".github/workflows/cross-platform-browser-journeys.yml"
JOURNEYS = REPO / "scripts/qualification/browser_journeys/journeys.cjs"


def _load(p):
    d = yaml.safe_load(p.read_text())
    d["_on"] = d.pop(True, d.get("on"))
    return d


def _steps(p):
    return _load(p)["jobs"]["journeys"]["steps"]


def test_it_is_dispatch_only_read_only_and_macos():
    d = _load(DIAG)
    assert set(d["_on"]) == {"workflow_dispatch"}
    assert d["permissions"] == {"contents": "read"}
    job = d["jobs"]["journeys"]
    assert job["runs-on"] == "macos-15" and job["env"]["PROFILE"] == "desktop"
    assert "secrets." not in DIAG.read_text()


def test_the_default_orders_compare_webkit_first_with_the_gates_order():
    """The probes showed the trigger is a pushState then two reloads, not the
    slot, so two orders confirm it: WebKit first, and the gate's own order."""
    orders = json.loads(_load(DIAG)["_on"]["workflow_dispatch"]["inputs"]["orders"]["default"])
    assert {o.split(",").index("webkit") for o in orders} == {0, 2}
    assert "chrome,msedge,webkit,firefox" in orders


def test_the_minimal_reproduction_runs_every_engine_and_varies_one_factor():
    job = _load(DIAG)["jobs"]["minimal"]
    assert job["runs-on"] == "macos-15"
    gate_version = _load(GATE)["jobs"]["journeys"]["env"]["PLAYWRIGHT_VERSION"]
    versions = job["strategy"]["matrix"]["playwright"]
    assert gate_version in versions and len(versions) >= 2     # the gate's WebKit build and a current one
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in versions)   # exact versions only
    assert job["env"]["PLAYWRIGHT_VERSION"] == "${{ matrix.playwright }}"
    assert "ENV " in (JOURNEYS.parent / "webkit_nav_repro.cjs").read_text()   # every run records its builds
    install = next(s for s in job["steps"] if "playwright install" in str(s.get("run", "")))
    assert all(e in install["run"] for e in ("webkit", "chromium", "firefox"))
    repro = (JOURNEYS.parent / "webkit_nav_repro.cjs").read_text()
    for v in ("A_no_push_two_reloads", "B_push_two_reloads", "C_push_one_reload",
              "D_replace_two_reloads", "E_real_navigation_two_reloads"):
        assert v in repro
    assert "process.exit(1)" not in repro       # a crash is the observation, not a script failure


def test_every_order_is_validated_before_anything_runs():
    run = _steps(DIAG)[0]["run"]
    assert "^[0-9a-f]{40}$" in run and "bad browser order" in run and ",webkit," in run


def test_it_runs_the_gates_own_steps_and_nothing_else():
    """A diagnosis that drifts from the gate diagnoses a different job."""
    def norm(steps, skip_first):
        out = []
        for s in steps[1 if skip_first else 0:]:
            s = dict(s)
            if str(s.get("uses", "")).startswith("actions/upload-artifact@"):
                s["with"] = {k: v for k, v in s["with"].items() if k != "name"}
            out.append(s)
        return out
    assert norm(_steps(DIAG), True) == norm(_steps(GATE), True)
    assert _load(DIAG)["jobs"]["journeys"]["env"]["PLAYWRIGHT_VERSION"] == _load(GATE)["jobs"]["journeys"]["env"]["PLAYWRIGHT_VERSION"]


def test_raw_crash_reports_are_never_uploaded():
    up = next(s for s in _steps(DIAG) if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert "raw" not in up["with"]["path"]
    collect = next(s for s in _steps(DIAG) if "collect_crash_reports.py" in str(s.get("run", "")))
    assert "crash-reports-raw-not-uploaded" in collect["run"]


def _body(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    return src[start:src.index("\n}\n", start)]


def test_the_page_state_logging_never_changes_a_result():
    src = JOURNEYS.read_text()
    for fn in ("trackPage", "logPrestate"):
        body = _body(src, fn)
        assert "check(" not in body and "throw" not in body, fn
    assert ".catch(" in _body(src, "logPrestate")       # a page that cannot answer still reloads


def test_every_watched_reload_is_preceded_by_its_page_state():
    src = JOURNEYS.read_text()
    labels = re.findall(r"logPrestate\(\w+, who, '(\w+)'", src)
    assert labels.count("reload_after_restart") == 2 and labels.count("first_reload") == 1
    child = _body(src, "child")
    assert child.index("'first_reload'") < child.index("await c.reload(); await passIntro(c);")
    assert child.index("'reload_after_restart'") < child.index("try { await c.reload(); }")


def test_the_navigation_probes_only_log_and_cover_the_child_journey():
    src = JOURNEYS.read_text()
    body = _body(src, "logNav")
    assert "check(" not in body and "throw" not in body and ".catch(" in body
    child = _body(src, "child")
    for label in ("after_sign_in", "after_lesson_turn_1", "after_overlapped_turn", "after_sibling_check",
                  "after_first_reload", "after_practice_answer", "after_restart_observed"):
        assert f"'{label}'" in child, label
    assert "logNav(p, who, 'after_sign_in')" in _body(src, "parent")


def _minimal_steps():
    return _load(DIAG)["jobs"]["minimal"]["steps"]


def test_the_minimal_reproduction_records_its_runner_and_command():
    """The runner is recorded, never assumed from its label: macOS version,
    architecture, the candidate, the Playwright version, the command and its
    exit status all land in runner.txt beside the log."""
    steps = _minimal_steps()
    record = next(s for s in steps if s.get("name") == "Record the runner")["run"]
    for item in ("sw_vers", "uname -m", "$CANDIDATE_SHA", "$PLAYWRIGHT_VERSION"):
        assert item in record, item
    run = next(s for s in steps if s.get("id") == "repro")
    assert "node webkit_nav_repro.cjs" in run["run"] and "exit=$status" in run["run"]
    assert run["env"]["REPEATS"] == "3"          # the recorded repeat count, unchanged
    assert "RESULTS_FILE=" in run["run"] and "TRACE_DIR=" in run["run"]


def test_the_minimal_reproduction_uploads_its_evidence_even_on_failure():
    steps = _minimal_steps()
    up = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert up["if"] == "always()" and "webkit-repro/" in up["with"]["path"]
    assert "raw" not in up["with"]["path"]
    collect = next(s for s in steps if "collect_crash_reports.py" in str(s.get("run", "")))
    assert collect["if"] == "always()" and "crash-reports-raw-not-uploaded" in collect["run"]
    assert "webkit-repro/crash-reports" in collect["run"]


def test_a_variant_the_engine_cannot_run_is_not_run_never_a_pass():
    """Firefox 142 has no Navigation API, so variant I errored there and was
    once counted as 'crashed 0/3'. It is NOT RUN: counted apart, and the tally
    says so rather than reporting zero crashes for runs that never executed."""
    repro = (JOURNEYS.parent / "webkit_nav_repro.cjs").read_text()
    assert "'navigation' in window" in repro and "not_run: no Navigation API" in repro
    assert "tally[key].not_run++; continue;" in repro
    assert "'NOT_RUN'" in repro
    assert "RESULTS_FILE" in repro and "TRACE_DIR" in repro


def test_each_pinned_playwright_is_checked_against_the_webkit_build_it_bundles():
    """1.56.0 bundles WebKit 26.0 and 1.63.0 WebKit 26.6; 1.64 moves to 27.2.
    The job fails if the installed build is not the expected one, if Node is
    not 22 or 24, or if macOS is older than 15, so no result can describe a
    different engine than it names. Every matrix version needs an entry."""
    job = _load(DIAG)["jobs"]["minimal"]
    step = next(s for s in job["steps"] if s.get("name") == "Confirm the engine, Node and macOS versions")
    expected = json.loads(step["env"]["EXPECTED_WEBKIT"])
    assert expected == {"1.56.0": "26.0", "1.63.0": "26.6"}
    assert set(job["strategy"]["matrix"]["playwright"]) <= set(expected)
    assert step["if"] == "always()" and "sys.exit" in step["run"]
    for check in ('("22", "24")', "< 15", "got != want"):
        assert check in step["run"], check
    setup_node = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/setup-node@"))
    assert str(setup_node["with"]["node-version"]) in ("22", "24")
    assert job["runs-on"] == "macos-15"
