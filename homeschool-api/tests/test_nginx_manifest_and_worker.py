"""The family deployment's nginx serves the web app manifest and the retired
service worker, and still refuses every other .json file.

Until this was fixed, homeschool-tutor/nginx.conf's `.json` deny rule caught
/manifest.json too, so every browser on the Docker deployment got a 404 for
it. The home-screen install read no name, icon or display mode, and the old
service worker's install step, which fetched it, failed every time, so the
worker never ran for a single family. See docs/RELIABILITY.md.

Two layers. The first reads the config, so it runs everywhere. The second
runs the REAL nginx against the REAL config on a free port and asks it, since
which location wins is nginx's decision and a config that reads right can
still serve the wrong thing (that is how the original 404 went unnoticed). It
needs an nginx binary and skips without one; GitHub's Ubuntu runners have
one.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CONF = _ROOT / "homeschool-tutor" / "nginx.conf"
_PUBLIC = _ROOT / "homeschool-tutor" / "public"


def _location_block(conf: str, header: str) -> str:
    start = conf.index(header)
    depth = 0
    for i in range(conf.index("{", start), len(conf)):
        depth += {"{": 1, "}": -1}.get(conf[i], 0)
        if depth == 0:
            return conf[start : i + 1]
    raise AssertionError(f"unterminated block {header}")


def _uncommented(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


CONF = _uncommented(_CONF.read_text())


@pytest.mark.parametrize("path", ["/manifest.json", "/sw.js"])
def test_the_file_has_an_exact_location(path):
    assert f"location = {path} {{" in CONF, (
        f"{path} has no exact-match location; a regex rule decides what it serves"
    )


@pytest.mark.parametrize("path", ["/manifest.json", "/sw.js"])
def test_the_exact_location_keeps_the_server_security_headers(path):
    """nginx stops inheriting the server's add_header lines into any location
    that has an add_header of its own. One here would serve these files with
    no CSP and no X-Frame-Options."""
    block = _location_block(CONF, f"location = {path} {{")
    assert "add_header" not in block
    assert "auth_request" not in block, "no user data here; it must load before sign-in"


def test_the_worker_is_never_cached():
    """A browser that still has the old worker must fetch the retired one."""
    assert re.search(r"expires\s+-1\s*;", _location_block(CONF, "location = /sw.js {"))


def test_every_other_json_file_is_still_refused():
    assert re.search(r"location\s+~\s+\\\.\([^)]*\bjson\b[^)]*\)\$\s*\{\s*deny all;", CONF)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


@pytest.fixture(scope="module")
def real_nginx(tmp_path_factory):
    binary = shutil.which("nginx") or ("/usr/sbin/nginx" if Path("/usr/sbin/nginx").exists() else None)
    if not binary:
        pytest.skip("no nginx binary here; the config checks above still ran")
    work = tmp_path_factory.mktemp("nginx")
    root = work / "root"
    shutil.copytree(_PUBLIC, root)
    (root / "index.html").write_text("<!doctype html><title>Bede</title>")
    (root / "notes.json").write_text("{}")
    port = _free_port()
    site = (
        _CONF.read_text()
        .replace("/usr/share/nginx/html", str(root))
        .replace("http://api:8000", "http://127.0.0.1:9")
        .replace("listen 80;", f"listen 127.0.0.1:{port};")
    )
    (work / "site.conf").write_text(site)
    temp = work / "tmp"
    temp.mkdir()
    mime = next((p for p in ("/etc/nginx/mime.types", "/usr/local/etc/nginx/mime.types", "/opt/homebrew/etc/nginx/mime.types") if Path(p).exists()), None)
    temps = " ".join(f"{d}_temp_path {temp};" for d in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
    (work / "nginx.conf").write_text(
        ""
        # As root, nginx would drop its workers to `nobody`, which cannot
        # read a pytest temp directory.
        + ("user root; " if os.geteuid() == 0 else "")
        + f"worker_processes 1; pid {work}/nginx.pid; error_log {work}/error.log; daemon off;\n"
        "events {}\n"
        f"http {{ {'include ' + mime + ';' if mime else ''} access_log off; {temps}\n"
        f"include {work}/site.conf; }}\n"
    )
    proc = subprocess.Popen([binary, "-c", str(work / "nginx.conf"), "-p", str(work)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        if proc.poll() is not None:
            pytest.fail(f"nginx would not start: {proc.stderr.read().decode()[-500:]}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield base
    proc.terminate()
    proc.wait(timeout=10)


def test_real_nginx_serves_the_manifest_with_the_security_headers(real_nginx):
    status, headers = _get(real_nginx + "/manifest.json")
    assert status == 200, "the home-screen manifest is refused again"
    assert headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in headers.get("Content-Security-Policy", "")


def test_real_nginx_serves_the_worker_uncached(real_nginx):
    status, headers = _get(real_nginx + "/sw.js")
    assert status == 200
    assert "no-cache" in headers.get("Cache-Control", "")
    assert headers.get("X-Frame-Options") == "DENY"


def test_real_nginx_still_refuses_other_json(real_nginx):
    status, _ = _get(real_nginx + "/notes.json")
    assert status == 404


def test_ci_runs_this_suite_when_only_the_nginx_config_changes():
    """Without the entry, an nginx-only edit computes relevant=false, skips
    api-tests, and never runs the guard written for exactly that edit."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    line = next(ln for ln in workflow.splitlines() if "grep -qE" in ln and "^(" in ln)
    pattern = re.search(r"'(\^\(.*\))'", line).group(1)
    assert re.match(pattern, "homeschool-tutor/nginx.conf")
    assert re.match(pattern, "homeschool-tutor/public/sw.js")
