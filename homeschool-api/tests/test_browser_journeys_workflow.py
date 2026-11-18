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
import os
import signal
import subprocess
import sys
import time
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
    # One picture is sent, so the reply must name exactly one kind (#825).
    assert content_screen.parse_verdict(reply, context, 1) is None, reply


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
    "overlong_message_handled_plainly", "child_cannot_open_parent_pages", "text_scale_200_no_horizontal_scroll",
    "conversation_visible_at_200",
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


# ── the runner stops what it started ────────────────────────────────────────

@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX; Windows uses taskkill /T")
def test_stop_all_stops_a_servers_children_too(tmp_path):
    """`npx vite preview` is npx starting node. Signalling npx alone left node
    holding the port, and the next run failed with 'Port 18400 is already in
    use'. Stopping the group must reach the child the launcher started."""
    run = _runner()
    pidfile = tmp_path / "child.pid"
    launcher = subprocess.Popen(["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"], **run.own_group())
    for _ in range(50):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.05)
    child = int(pidfile.read_text())
    run.stop_all([launcher, None])
    assert launcher.poll() is not None
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child, signal.SIGKILL)
        pytest.fail("the launcher's child outlived stop_all")
    run.stop_all([launcher])  # a second call is harmless


def test_cleanup_is_registered_before_the_first_server_starts():
    """A failure while seeding happens before the run's try/finally, so the
    stop has to be registered before the first Popen, not after."""
    src = (HARNESS / "run_journeys.py").read_text()
    body = src[src.index("procs: list[subprocess.Popen] = []"):]
    assert body.index("atexit.register(") < body.index("subprocess.Popen(")
    for name in ("model_stub.py", '"uvicorn"', '"vite", "preview"', "journeys.cjs"):
        start = body.index(name)
        call = body[start:body.index(")\n", start)]
        assert "own_group()" in call, f"{name} is not started in its own process group"


# ── native crash reports on macOS (diagnostic only) ─────────────────────────
# A fake report proves the collection mechanics only, not that macOS writes
# one or that it is read correctly; that is checked on the runner.

COLLECTOR = HARNESS / "collect_crash_reports.py"
SECRET = "SAMPLE_SECRET_MARKER_7f3a"
SECRET_PATH = "/Users/runner/private-marker-dir/Thing.framework/Thing"


def _collector():
    spec = importlib.util.spec_from_file_location("collect_crash_reports", COLLECTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _step(name_part: str) -> dict:
    return next(s for s in _job()["steps"] if name_part in str(s.get("name", "")))


def _names() -> list[str]:
    return [str(s.get("name", "")) for s in _job()["steps"]]


def _ips(path: Path, proc="com.apple.WebKit.WebContent", secret=True):
    header = {"bug_type": "309", "app_name": proc, "timestamp": "2026-11-15 00:53:00.00 +0000"}
    body = {
        "procName": proc, "pid": 4242, "faultingThread": 0,
        "exception": {"type": "EXC_BAD_ACCESS", "signal": "SIGSEGV", "codes": "0x1, 0x0"},
        "termination": {"namespace": "SIGNAL", "indicator": "Segmentation fault: 11",
                        "reasons": [f"token={SECRET} at {SECRET_PATH}"] if secret else []},
        "usedImages": [{"name": "WebCore", "path": SECRET_PATH}],
        "threads": [{"triggered": True, "frames": [{"imageIndex": 0, "symbol": "WebCore::Page::reload"}]}],
    }
    path.write_text(json.dumps(header) + "\n" + json.dumps(body))


def _fresh(tmp_path):
    marker = tmp_path / "marker"; marker.write_text("")
    os.utime(marker, (time.time() - 60, time.time() - 60))
    user, system = tmp_path / "user", tmp_path / "system"; user.mkdir(); system.mkdir()
    return marker, user, system


def test_the_job_start_is_marked_early_and_collection_sits_between_the_journeys_and_the_upload():
    n = _names()
    mark = n.index(next(x for x in n if "Mark the job start for crash reports" in x))
    run = n.index(next(x for x in n if "Run concurrent journeys" in x))
    collect = n.index(next(x for x in n if "Collect native crash reports" in x))
    upload = n.index(next(x for x in n if "Preserve journey evidence" in x))
    assert mark < run < collect < upload
    assert "macOS" in str(_step("Mark the job start").get("if"))


def test_collection_runs_after_a_failure_and_cannot_change_the_row():
    step = _step("Collect native crash reports")
    assert "always()" in str(step.get("if")) and "macOS" in str(step.get("if"))
    assert step.get("continue-on-error") is True
    # The window follows the journeys' outcome, read from the steps context.
    assert step.get("env", {}).get("JOURNEYS_OUTCOME") == "${{ steps.journeys.outcome }}"
    assert _step("Run concurrent journeys").get("id") == "journeys"
    assert '"$JOURNEYS_OUTCOME" = "failure"' in step["run"] and '--wait "$wait"' in step["run"]
    # The journeys keep their own result: not wrapped, not continue-on-error.
    run = _step("Run concurrent journeys")
    assert "continue-on-error" not in run and "|| true" not in run["run"] and "||" not in run["run"]


def test_only_the_sanitized_summary_is_uploaded_and_upload_still_runs_after_a_failure():
    upload, step = _step("Preserve journey evidence"), _step("Collect native crash reports")
    assert "always()" in str(upload.get("if"))
    assert "bede-browser-journeys/crash-reports/" in upload["with"]["path"]
    assert "--summary-dir \"$RUNNER_TEMP/bede-browser-journeys/crash-reports\"" in step["run"]
    raw = re.search(r'--raw-dir "\$RUNNER_TEMP/([^"]+)"', step["run"]).group(1)
    assert not raw.startswith("bede-browser-journeys") and raw not in upload["with"]["path"]


def test_only_new_relevant_reports_are_taken_and_same_names_never_collide(tmp_path):
    cc = _collector(); marker, user, system = _fresh(tmp_path)
    old = user / "com.apple.WebKit.WebContent-old.ips"; _ips(old)
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    (user / "Finder-new.ips").write_text("{}\n{}")
    _ips(user / "com.apple.WebKit.WebContent-same.ips"); _ips(system / "com.apple.WebKit.WebContent-same.ips")
    (user / "jetsamevent-2026.IPS").write_text(json.dumps({"bug_type": "298"}) + "\n" +
                                               json.dumps({"largestProcess": "com.apple.WebKit.WebContent", "processes": []}))
    rec = cc.collect(marker, [("user", user), ("system", system)], tmp_path / "raw", wait=0)
    got = sorted((r["source"], r["file"]) for r in rec["reports"])
    assert got == [("system", "com.apple.WebKit.WebContent-same.ips"), ("user", "com.apple.WebKit.WebContent-same.ips"),
                   ("user", "jetsamevent-2026.IPS")]
    assert (tmp_path / "raw/user/com.apple.WebKit.WebContent-same.ips").exists()
    assert (tmp_path / "raw/system/com.apple.WebKit.WebContent-same.ips").exists()
    assert rec["outcome"] == "report_collected"
    crash = next(r for r in rec["reports"] if r["kind"] == "crash")
    assert crash["exception"]["type"] == "EXC_BAD_ACCESS" and crash["termination"]["namespace"] == "SIGNAL"
    assert crash["triggered_thread"] == 0 and crash["frames"] == ["WebCore WebCore::Page::reload"]


def test_printed_and_saved_output_never_carries_a_secret_or_a_path(tmp_path):
    cc = _collector(); marker, user, system = _fresh(tmp_path)
    _ips(user / "com.apple.WebKit.WebContent-x.ips")
    out = tmp_path / "summary"
    r = subprocess.run([sys.executable, str(COLLECTOR), "--marker", str(marker), "--summary-dir", str(out),
                        "--raw-dir", str(tmp_path / "raw"), "--wait", "0", "--dir", f"user={user}"], capture_output=True, text=True)
    assert r.returncode == 0
    saved = (out / "crash-report-summary.json").read_text()
    for text in (r.stdout, saved):
        assert SECRET not in text and "private-marker-dir" not in text and "/Users/runner" not in text
        assert "EXC_BAD_ACCESS" in text
    cleaned = cc.sanitize("Authorization: Bearer abcdefgh12345678")
    assert "abcdefgh12345678" not in cleaned and cleaned.startswith("Authorization: <redacted>")


def test_no_report_is_inconclusive_and_never_read_as_a_kill(tmp_path):
    cc = _collector(); marker, user, system = _fresh(tmp_path)
    rec = cc.collect(marker, [("user", user), ("system", system)], tmp_path / "raw", wait=0)
    assert rec["outcome"] == "no_matching_report"
    assert rec["note"] == ("No matching native report was collected within the observation window. "
                           "The process-termination cause remains unknown.")
    assert "kill" not in json.dumps(rec).lower()


def test_missing_and_denied_directories_are_recorded_separately_from_an_empty_search(tmp_path, monkeypatch):
    cc = _collector(); marker, user, system = _fresh(tmp_path)
    rec = cc.collect(marker, [("user", user), ("gone", tmp_path / "nope")], tmp_path / "raw", wait=0)
    assert rec["directories"] == {"user": "searched", "gone": "missing"} and rec["outcome"] == "no_matching_report"
    real = cc.os.scandir
    monkeypatch.setattr(cc.os, "scandir", lambda d: (_ for _ in ()).throw(PermissionError()) if str(d) == str(system) else real(d))
    rec = cc.collect(marker, [("system", system)], tmp_path / "raw", wait=0)
    assert rec["directories"] == {"system": "permission_denied"} and rec["outcome"] == "collection_failed"
    rec = cc.collect(tmp_path / "no-marker", [("user", user)], tmp_path / "raw", wait=0)
    assert rec["outcome"] == "collection_failed" and "marker" in rec["note"]


def test_a_collector_error_still_leaves_a_record(tmp_path, monkeypatch):
    cc = _collector(); marker, user, _ = _fresh(tmp_path)
    monkeypatch.setattr(cc, "collect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = tmp_path / "summary"
    status = cc.main(["--marker", str(marker), "--summary-dir", str(out), "--raw-dir", str(tmp_path / "raw"),
                      "--wait", "0", "--dir", f"user={user}"])
    rec = json.loads((out / "crash-report-summary.json").read_text())
    assert status == 2 and rec["outcome"] == "collection_failed" and "RuntimeError" in rec["note"]


def test_a_report_written_after_the_failure_is_still_caught_within_the_window(tmp_path):
    import threading
    cc = _collector(); marker, user, _ = _fresh(tmp_path)
    threading.Timer(0.6, lambda: _ips(user / "com.apple.WebKit.WebContent-late.ips")).start()
    t0 = time.monotonic()
    rec = cc.collect(marker, [("user", user)], tmp_path / "raw", wait=5, interval=0.2)
    assert [r["file"] for r in rec["reports"]] == ["com.apple.WebKit.WebContent-late.ips"]
    assert time.monotonic() - t0 < 4, "it should stop once the report has settled, not wait out the window"


# ── GitHub expression rules a YAML parse cannot see ─────────────────────────

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_STATUS_FN = re.compile(r"\b(always|success|failure|cancelled)\s*\(\s*\)")


def _status_functions_outside_if(node, path=""):
    """Yield (path, value) for every ${{ }} using a status function anywhere but an `if:`."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "if":
                continue
            yield from _status_functions_outside_if(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _status_functions_outside_if(v, f"{path}[{i}]")
    elif isinstance(node, str):
        for expr in re.findall(r"\$\{\{(.*?)\}\}", node, re.S):
            if _STATUS_FN.search(expr):
                yield path, expr.strip()


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.y*ml")), ids=lambda p: p.name)
def test_status_functions_appear_only_in_if_conditions(workflow):
    """GitHub allows always()/success()/failure()/cancelled() only in `if:`.
    Anywhere else the whole file is rejected and no job runs at all: on
    1f50205f, failure() in a step's env stopped every row of the
    cross-platform matrix, and a YAML parse reported nothing wrong."""
    bad = list(_status_functions_outside_if(yaml.safe_load(workflow.read_text())))
    assert not bad, f"{workflow.name}: status function outside `if:` at {bad}"


def _fixture_keys() -> set[str]:
    """The keys run_journeys.py writes into fixture.json, read from its source."""
    src = (HARNESS / "run_journeys.py").read_text()
    m = re.search(r"\n    fixture = \{(.*?)\}\n", src, re.S)
    assert m, "run_journeys.py no longer builds `fixture = {...}`"
    return set(re.findall(r'"([a-z_]+)":', m.group(1)))


def test_every_fixture_field_the_journeys_read_is_written():
    # #824 moved the parent password out of fixture.json (it is uploaded as an
    # artifact) and changed one of its three readers. The other two typed
    # `undefined` into the sign-in form and every boundary run failed with
    # "expected string, got undefined", naming no cause. A field read from F
    # that run_journeys.py never writes is that defect, whatever it is called.
    written = _fixture_keys()
    for js in sorted(HARNESS.glob("*.cjs")):
        read = set(re.findall(r"\bF\.([a-z_]+)", js.read_text()))
        assert read <= written, f"{js.name} reads {sorted(read - written)} from the fixture, which never has them"


def test_the_parent_password_stays_out_of_the_uploaded_fixture():
    assert not any("password" in k for k in _fixture_keys())
    src = JOURNEYS.read_text()
    assert "process.env.JOURNEY_PARENT_PASSWORD" in src
    assert "JOURNEY_PARENT_PASSWORD=parent_password" in (HARNESS / "run_journeys.py").read_text()
