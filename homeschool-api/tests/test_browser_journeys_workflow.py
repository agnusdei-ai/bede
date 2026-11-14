"""The cross-platform browser journeys, guarded against their PARSED YAML.

.github/workflows/cross-platform-browser-journeys.yml is the automated layer
of docs/release/DEVICE_QUALIFICATION.md: Windows, macOS and Linux desktop
browsers, plus emulated iPhone/iPad/Android. A matrix row quietly dropped, a
trigger narrowed back to the journeys' own files, or a gate that lets an
unrun check pass would each leave the workflow green while proving less.
Each property here is asserted against what GitHub reads (yaml.safe_load)
or against the harness's own code, and each was verified by breaking it.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "cross-platform-browser-journeys.yml"
HARNESS = REPO / "scripts" / "qualification" / "browser_journeys"
JOURNEYS = HARNESS / "journeys.cjs"
CHECKLIST = REPO / "docs/release/DEVICE_QUALIFICATION.md"


def _wf() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text())
    doc["_on"] = doc.get("on", doc.get(True))  # PyYAML parses bare `on` as True
    return doc


def _job() -> dict:
    return _wf()["jobs"]["journeys"]


def _rows() -> list[dict]:
    return _job()["strategy"]["matrix"]["include"]


def _runner():
    spec = importlib.util.spec_from_file_location("run_journeys", HARNESS / "run_journeys.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the support matrix ──────────────────────────────────────────────────────

REQUIRED_ROWS = {
    ("windows-2022", "desktop"): {"chrome", "msedge", "firefox"},
    ("macos-15", "desktop"): {"chrome", "msedge", "webkit", "firefox"},
    ("ubuntu-24.04", "desktop"): {"chrome", "firefox"},
    ("macos-15", "mobile"): {"webkit", "chromium"},
    ("ubuntu-24.04", "boundary"): {"chrome", "firefox", "webkit"},
}


@pytest.mark.parametrize("row", sorted(REQUIRED_ROWS))
def test_every_supported_platform_row_is_in_the_matrix(row):
    found = {(r["os"], r["profile"]): set(r["browsers"].split(",")) for r in _rows()}
    assert row in found, f"matrix lost the {row} row"
    assert REQUIRED_ROWS[row] <= found[row], f"{row} lost a browser: has {sorted(found[row])}"


def test_every_runner_is_a_pinned_image():
    for r in _rows():
        assert not r["os"].endswith("-latest"), f"{r['os']} floats; pin it (see test_runner_pins.py)"
    assert any(r["os"] == "ubuntu-24.04" for r in _rows())


def test_the_profile_and_browsers_reach_the_runner():
    run = next(s for s in _job()["steps"] if "run_journeys.py" in str(s.get("run", "")))
    assert '--profile "$PROFILE"' in run["run"] and '--browsers "$BROWSERS"' in run["run"]
    assert _job()["env"]["PROFILE"] == "${{ matrix.profile }}"


def test_mobile_devices_run_on_the_engine_their_descriptor_names():
    """An iPhone emulated on Chromium would be neither an iPhone nor WebKit."""
    devices = _runner().MOBILE_DEVICES
    assert any("iPhone" in d for d in devices["webkit"]) and any("iPad" in d for d in devices["webkit"])
    assert any("Pixel" in d for d in devices["chromium"])
    assert all("iPhone" not in d and "iPad" not in d for d in devices["chromium"])
    for engine in devices:
        assert any("landscape" in d for d in devices[engine]) and any("landscape" not in d for d in devices[engine])
    assert "pw.devices[dev].defaultBrowserType" in JOURNEYS.read_text()


def test_mobile_results_are_labelled_emulated():
    assert "evidence: PROFILE === 'mobile' ? 'emulated'" in JOURNEYS.read_text()


# ── triggers ────────────────────────────────────────────────────────────────

REQUIRED_PATHS = [
    "homeschool-tutor/src/**",
    "homeschool-tutor/package-lock.json",
    "homeschool-api/routers/auth.py",
    "homeschool-api/routers/practice.py",
    "homeschool-api/core/deps.py",
    "homeschool-api/core/middleware.py",
    "scripts/qualification/browser_journeys/**",
    ".github/workflows/cross-platform-browser-journeys.yml",
]


@pytest.mark.parametrize("path", REQUIRED_PATHS)
def test_relevant_app_changes_trigger_it_not_only_journey_edits(path):
    assert path in _wf()["_on"]["pull_request"]["paths"]


def test_a_candidate_is_dispatched_by_full_sha_and_checked_out_exactly():
    on = _wf()["_on"]
    assert on["workflow_dispatch"]["inputs"]["candidate_sha"]["required"] is True
    steps = _job()["steps"]
    assert "^[0-9a-f]{40}$" in steps[0]["run"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ env.CANDIDATE_SHA }}"
    assert "checked-out HEAD" in (HARNESS / "run_journeys.py").read_text()


def test_token_is_read_only_and_no_pull_request_target():
    wf = _wf()
    assert wf["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in wf["_on"]


def test_candidate_evidence_is_kept_longer_than_pr_evidence():
    up = next(s for s in _job()["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert up["with"]["retention-days"] == "${{ github.event_name == 'workflow_dispatch' && 90 || 14 }}"
    assert "${{ matrix.profile }}" in up["with"]["name"]


# ── fail-closed: a check that never ran is not a pass ───────────────────────

def _results(tmp_path: Path, **summary) -> Path:
    base = {"expected_checks": 3, "missing_checks": [], "failed_checks": 0, "failed_steps": 0}
    base.update(summary)
    (tmp_path / "results.json").write_text(json.dumps({"summary": base, "checks": [], "steps": []}))
    return tmp_path


def test_complete_results_pass(tmp_path):
    assert _runner().completeness_failure(_results(tmp_path)) == 0


def test_missing_results_file_fails(tmp_path):
    assert _runner().completeness_failure(tmp_path) == 1


@pytest.mark.parametrize("summary", [
    {"missing_checks": ["child1_chrome/answer_persisted_after_restart"]},
    {"expected_checks": 0},
    {"failed_checks": 1},
    {"failed_steps": 2},
])
def test_incomplete_or_failed_results_fail(tmp_path, summary):
    assert _runner().completeness_failure(_results(tmp_path, **summary)) == 1


def test_the_gate_runs_after_the_journeys_exit():
    src = (HARNESS / "run_journeys.py").read_text()
    assert "rc = rc or completeness_failure(out)" in src


def test_the_journeys_declare_and_enforce_expected_checks():
    src = JOURNEYS.read_text()
    assert "function expectedChecks()" in src
    assert "missing_checks: missing" in src
    assert re.search(r"process\.exit\(summary\.failed_checks \|\| summary\.failed_steps \|\| missing\.length", src)


def test_versions_are_recorded_in_the_evidence():
    src = JOURNEYS.read_text()
    for field in ("playwright: require('playwright/package.json').version", "browsers: versions", "os_detail: F.os_detail"):
        assert field in src


# ── the physical layer is written down, and not claimed ─────────────────────

def test_the_device_checklist_exists_and_keeps_native_ios_on_hold():
    doc = CHECKLIST.read_text()
    for platform in ("iPhone", "iPad", "Android", "Windows", "macOS", "Ubuntu 24.04", "Debian 12"):
        assert platform in doc
    assert "NOT RUN" in doc and "emulated" in doc
    assert "HOLD" in doc and "IOS_IPADOS_RC1.md" in doc


# ── the stub must answer the product's real upload check ────────────────────

def _post_to_stub(system: str, with_image: bool, monkeypatch) -> str:
    """Send one non-streaming request to the real model_stub handler and
    return the reply text, the way the API's OpenAI-compatible client does."""
    import threading
    from http.server import ThreadingHTTPServer
    import httpx

    spec = importlib.util.spec_from_file_location("model_stub", HARNESS / "model_stub.py")
    stub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stub)
    # Skip the stub's added model latency. Through monkeypatch, so it is
    # restored: `stub.time` IS the global time module, and assigning to it
    # directly once disabled time.sleep for every later test in the process.
    monkeypatch.setattr(stub.time, "sleep", lambda *_: None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), stub.H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        user = [{"type": "text", "text": "check"}]
        if with_image:
            user.append({"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}})
        body = {"model": "sample-stub", "messages": [{"role": "system", "content": system},
                                                        {"role": "user", "content": user}]}
        r = httpx.post(f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions", json=body, timeout=10)
        return r.json()["choices"][0]["message"]["content"]
    finally:
        server.shutdown()


@pytest.mark.parametrize("context", ["worksheet", "lesson"])
def test_the_stub_passes_the_real_upload_check(tmp_path, monkeypatch, context):
    """Since #814 every uploaded picture is screened before it is read, and
    the screen also carries the pictures. A stub that answers it with a quiz
    reading makes the screen fail closed, so every journey upload is refused:
    that is what silently broke these journeys on main from #814 until this
    branch. Uses the product's own prompt and its own parser."""
    from services import content_screen
    monkeypatch.setattr("sys.argv", ["model_stub", "0", str(tmp_path)])
    reply = _post_to_stub(content_screen._rules(context), with_image=True, monkeypatch=monkeypatch)
    assert content_screen.parse_verdict(reply) is None, reply


def test_the_stub_still_reads_a_quiz(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["model_stub", "0", str(tmp_path)])
    reply = json.loads(_post_to_stub("Read this graded quiz. Subject: history", with_image=True, monkeypatch=monkeypatch))
    assert reply.get("sections"), "the reading branch no longer answers a quiz reading"


def test_the_checklist_is_in_the_ci_change_filter():
    """Without it, a checklist-only edit computes relevant=false, skips
    api-tests, and never runs the guard written for exactly that edit."""
    wf = (REPO / ".github" / "workflows" / "test.yml").read_text()
    line = next(l for l in wf.splitlines() if "grep -qE" in l and "homeschool-api/" in l)
    alternatives = line.split("'")[1].strip("^()").split("|")
    assert r"docs/release/DEVICE_QUALIFICATION\.md" in alternatives


BOUNDARY_CHECKS = [
    "open_redirect_refused", "wrong_password_plain_error", "invalid_token_logs_out_with_notice",
    "back_after_logout_shows_no_household", "oversize_upload_refused_before_send",
    "unsupported_upload_refused_without_reading", "double_approve_single_set", "blank_message_not_sent",
    "overlong_message_handled_plainly", "child_cannot_open_parent_pages", "text_scale_175_no_horizontal_scroll",
    "parent_locked_after_repeated_failures", "locked_parent_refused_even_with_right_password",
    "recovery_reachable_while_locked",
]


@pytest.mark.parametrize("name", BOUNDARY_CHECKS)
def test_every_boundary_is_an_expected_check(name):
    """A boundary dropped from the expected list would stop failing the run
    when it silently stops running."""
    src = JOURNEYS.read_text()
    block = src[src.index("if (PROFILE === 'boundary') {"):src.index("if (PROFILE === 'mobile') {", src.index("if (PROFILE === 'boundary') {"))]
    assert f"'{name}'" in block


def test_the_lockout_runs_last_and_once():
    """It locks the shared parent account, so anything after it would fail
    for that reason alone."""
    src = JOURNEYS.read_text()
    run = src[src.index("} else if (PROFILE === 'boundary') {"):]
    assert run.index("boundaryParent") < run.index("await boundaryLockout(browsers[0])")


def test_the_boundary_fixtures_straddle_the_real_limit():
    src = (HARNESS / "run_journeys.py").read_text()
    assert "f.truncate(25 * 1024 * 1024 + 1024)" in src
    ui = (REPO / "homeschool-tutor/src/utils/uploadParts.ts").read_text()
    assert "FILE_MAX_BYTES = 25 * 1024 * 1024" in ui
