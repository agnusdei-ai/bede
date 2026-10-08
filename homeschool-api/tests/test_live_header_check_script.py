"""Guards `scripts/check_live_site_headers.sh`'s three outcomes.

That script is the live half of the standing security-header workflow: it runs
on every push to `main` and twice daily, and `test_site_headers.py` already
asserts it exists. Nothing asserted what it *concludes*, and its conclusion is
the whole product — a red run tells a reader to go reconfigure Cloudflare.

It used to decide "did the origin answer" by testing whether the response was
EMPTY. When an intermediary answers the request itself — an egress proxy, a
captive portal, a Cloudflare error page mid-deploy — the response is non-empty,
carries that intermediary's headers, and contains none of ours. So the script
reported `missing: <every header>` and printed the Worker-configuration advice:
a confident diagnosis of a problem that does not exist. A gate that cries wolf
is a gate someone deletes, which this repository has done once already (#296).

Tested by running the REAL script against a real local HTTP server, because the
defect lived in how it reads an actual HTTP response and a stub of the response
would be a second place for the bug to hide. The three cases are the three
things it must tell apart, and the third is the point: the genuine detection has
to survive a fix aimed at the other two.
"""
import re
import socket
import time
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_live_site_headers.sh"
_HEADERS = _ROOT / "site" / "_headers"

# Deliberately specific. A blunt `"Worker"` matches the honest unreachable
# message too, which names the Worker in order to say "do not look there yet" —
# so the first cut of this failed against a script that was behaving correctly.
# Same trap as a scan that fires on a docstring describing the thing it forbids.
_FALSE_VERDICT = "The deployed site is not serving headers"
_WORKER_ADVICE = "assets.run_worker_first"
_MISSING = "missing:"


def _declared_headers() -> list[str]:
    """The `/*` rule's header names, the same set the script parses."""
    names, inrule = [], False
    for line in _HEADERS.read_text().splitlines():
        if line[:1] not in (" ", "\t", "", "#"):
            inrule = line.startswith("/*")
            continue
        if inrule and line.strip().startswith("#"):
            continue
        match = re.match(r"\s+([A-Za-z-]+):", line)
        if inrule and match:
            names.append(match.group(1))
    return names


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(mode: str, port: int) -> subprocess.Popen:
    """A server in one of the three shapes the script must distinguish."""
    code = textwrap.dedent(f"""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        HDRS = {_declared_headers()!r}
        class H(BaseHTTPRequestHandler):
            def do_HEAD(self):
                if {mode!r} == "intermediary":
                    self.send_response(403)          # answered, but not by us
                    self.send_header("Content-Type", "text/html")
                else:
                    self.send_response(200)
                    keep = HDRS if {mode!r} == "healthy" else HDRS[1:]
                    for h in keep:
                        self.send_header(h, "x")
                self.end_headers()
            do_GET = do_HEAD
            def log_message(self, *a): pass
        HTTPServer(("127.0.0.1", {port}), H).serve_forever()
    """)
    proc = subprocess.Popen([sys.executable, "-c", code],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Poll with a real delay. Without one this spins through every attempt in
    # microseconds and gives up before the interpreter has even started.
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return proc
        except OSError:
            time.sleep(0.05)
    proc.kill()
    pytest.fail(f"the {mode} test server never came up")


def _run(mode: str):
    port = _free_port()
    proc = _serve(mode, port)
    try:
        return subprocess.run(
            ["bash", str(_SCRIPT)],
            cwd=_ROOT, capture_output=True, text=True, timeout=120,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin",
                 "SITE_HOSTS": f"http://127.0.0.1:{port}",
                 "SITE_PATHS": "/", "ATTEMPTS": "2", "SLEEP_SECONDS": "0"},
        )
    finally:
        proc.kill()


def test_the_script_and_its_header_file_are_both_present():
    """Canary: every case below would error rather than assert without these."""
    assert _SCRIPT.is_file(), f"{_SCRIPT} is missing"
    assert _declared_headers(), "parsed no headers out of site/_headers"


def test_a_healthy_origin_passes():
    out = _run("healthy")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "all" in out.stdout and _MISSING not in out.stdout


def test_an_intermediary_answering_is_not_reported_as_a_missing_header():
    """The defect this file exists for. A 403 from something that is not the
    origin must not read as "the deployed site is not serving headers", and
    must not send anyone to the Worker-configuration advice."""
    out = _run("intermediary")
    assert out.returncode != 0, "an unreachable origin must still fail the run"
    assert _MISSING not in out.stdout, (
        "a response the origin never served was reported as missing headers:\n"
        + out.stdout
    )
    assert _FALSE_VERDICT not in out.stdout, (
        "a run that never reached the origin still returned a verdict on the "
        "header set:\n" + out.stdout
    )
    assert _WORKER_ADVICE not in out.stdout, (
        "unreachability reached the Cloudflare/Worker diagnosis, which is a "
        "confident answer to a question this run cannot answer:\n" + out.stdout
    )
    assert "no response from the origin" in out.stdout


def test_a_real_missing_header_is_still_caught_and_still_blames_the_deployment():
    """The fix for the two cases above must not cost the detection itself."""
    out = _run("regressed")
    assert out.returncode != 0
    assert _MISSING in out.stdout, out.stdout
    assert _FALSE_VERDICT in out.stdout, out.stdout
    assert _WORKER_ADVICE in out.stdout, (
        "a genuine header regression must still point at the deployment:\n"
        + out.stdout
    )


def test_the_script_is_in_cis_change_filter():
    """test.yml computes relevant=false for a change touching nothing it names,
    which would skip this suite on an edit to the very script it guards. Reads
    the grep -qE pattern line itself, not the workflow anywhere — an earlier
    check of this shape elsewhere in the repo passed on a nearby comment."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    lines = [ln for ln in workflow.splitlines() if "grep -qE" in ln]
    assert lines, "test.yml no longer has a grep -qE change filter"
    assert any(r"scripts/check_live_site_headers\.sh" in ln for ln in lines), (
        "scripts/check_live_site_headers.sh is not named in test.yml's change "
        "filter, so editing it skips this suite."
    )
