"""
Regression test for the missing reverse-proxy trust that once collapsed
every demo visitor onto one shared rate-limit bucket (see the Dockerfile's
`--proxy-headers --forwarded-allow-ips=*` flags on the uvicorn CMD).

Unlike the rest of tests/, this boots a *real* uvicorn subprocess against a
real Postgres so it exercises the actual proxy-header handling uvicorn does
at the ASGI-server layer — that layer is invisible to an in-process
TestClient, which talks to the ASGI app directly and never goes through it.
Skips itself if no Postgres is reachable, so `pytest tests/` still works for
anyone without one — see .github/workflows/test.yml for the CI job that
provides one.

Simulating "many distinct visitors behind one shared reverse-proxy peer"
locally needs two independent things, easy to conflate:
  1. Each simulated visitor sends a different X-Forwarded-For value (what
     Render's edge would forward for a real, distinct visitor).
  2. Every request's own TCP source address is the *same* one address, and
     that address must NOT be uvicorn's trusted-by-default "127.0.0.1" —
     otherwise the client's own loopback source gets trusted for free and
     the exact bug this test exists to catch never reproduces.
(2) is done with httpx's `local_address`, binding every simulated visitor's
outgoing connection to 127.0.0.2 — a second loopback address that routes
locally with no real network involved, but isn't uvicorn's default trusted
peer, standing in for "the container's only visible peer is the hosting
platform's own proxy."
"""
import asyncio
import itertools
import os
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import httpx
import pytest

API_DIR = Path(__file__).resolve().parent.parent

# The single, shared source address every simulated visitor connects from —
# standing in for "the only peer uvicorn ever actually sees, behind Render's
# edge proxy." Deliberately not uvicorn's default trusted peer (127.0.0.1).
_SHARED_PROXY_PEER = "127.0.0.2"

_ip_counter = itertools.count(1)


def _next_visitor_ip() -> str:
    """A fresh, never-reused simulated *real visitor* IP (the value carried
    in X-Forwarded-For) for each caller, so no two test cases in this module
    ever share a rate-limit bucket by accident."""
    n = next(_ip_counter)
    return f"198.51.{(n >> 8) & 0xFF}.{n & 0xFF}"


def _visitor_client(base_url: str) -> httpx.AsyncClient:
    """An httpx client whose connections all originate from
    _SHARED_PROXY_PEER, matching how every real visitor's request actually
    reaches the app once Render's edge proxy is in front of it."""
    transport = httpx.AsyncHTTPTransport(local_address=_SHARED_PROXY_PEER)
    return httpx.AsyncClient(base_url=base_url, transport=transport, timeout=10.0)


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def demo_api_base_url():
    port = _free_port()
    env = os.environ.copy()
    env["DATABASE_URL"] = os.environ.get(
        "DEMO_CONCURRENCY_TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/bede_concurrency_test",
    )
    env.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
    env.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 32)
    env.setdefault("MASTER_SECRET", "test-master-secret-" + "y" * 32)
    env.setdefault("PARENT_PASSWORD", "change-me-parent")
    env.setdefault("CHILD_PIN", "0000")
    env["DEMO_PIN"] = "913579"  # must differ from PARENT_PASSWORD/CHILD_PIN above

    # Same proxy-header flags as homeschool-api/Dockerfile's CMD — this test
    # exists specifically to catch a drift between the two. Bound to
    # 0.0.0.0 so it's reachable via any loopback alias, including the
    # _SHARED_PROXY_PEER address the test clients connect from.
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", "0.0.0.0", "--port", str(port),
            "--proxy-headers", "--forwarded-allow-ips=*",
        ],
        cwd=str(API_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    healthy = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                healthy = True
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)

    if not healthy:
        proc.terminate()
        try:
            output = proc.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            output = "(process did not exit after terminate)"
        pytest.skip(
            "Could not start homeschool-api for the demo concurrency test "
            f"(is Postgres reachable at {env['DATABASE_URL']}?). Server output:\n{output}"
        )

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.parametrize("concurrency", [10, 20, 30, 40, 50])
@pytest.mark.asyncio
async def test_distinct_visitors_scale_without_false_rate_limiting(demo_api_base_url, concurrency):
    """`concurrency` simulated visitors — each with its own X-Forwarded-For
    IP, all arriving through the one shared proxy peer described at the top
    of this file — hit POST /auth/demo-code at the same instant. Every one
    must succeed with a unique code. Before the --forwarded-allow-ips fix,
    uvicorn ignored X-Forwarded-For for any peer other than 127.0.0.1, every
    visitor collapsed onto the one shared peer address, and the 10-req/min
    auth bucket started rejecting real, distinct visitors well before
    reaching even this test's smallest batch size."""
    visitor_ips = [_next_visitor_ip() for _ in range(concurrency)]

    async with _visitor_client(demo_api_base_url) as client:
        t0 = time.perf_counter()
        responses = await asyncio.gather(*[
            client.post("/auth/demo-code", headers={"X-Forwarded-For": ip})
            for ip in visitor_ips
        ])
        elapsed = time.perf_counter() - t0

    statuses = [r.status_code for r in responses]
    assert all(s == 200 for s in statuses), (
        f"Expected all {concurrency} distinct visitors to get 200, got: {statuses}"
    )

    codes = [r.json()["code"] for r in responses]
    assert len(set(codes)) == concurrency, "Two different visitors were issued the same demo code"

    # Generous ceiling — this is a correctness regression test, not a
    # micro-benchmark, but a multi-second stall here would itself indicate
    # something is serializing requests that shouldn't be.
    assert elapsed < 5.0, f"{concurrency} concurrent visitors took {elapsed:.2f}s — expected well under 5s"


@pytest.mark.asyncio
async def test_fifty_concurrent_visitors_generate_and_redeem_without_collision(demo_api_base_url):
    """Extends the scaling test through the full code -> JWT exchange at the
    largest batch size: 50 distinct visitors generate a code and immediately
    redeem it, concurrently. Guards against a race in
    core/demo_code_session.redeem_code's check-then-set, in addition to the
    proxy/rate-limit behavior covered above."""
    visitor_ips = [_next_visitor_ip() for _ in range(50)]

    async with _visitor_client(demo_api_base_url) as client:
        code_responses = await asyncio.gather(*[
            client.post("/auth/demo-code", headers={"X-Forwarded-For": ip})
            for ip in visitor_ips
        ])
        assert all(r.status_code == 200 for r in code_responses)
        codes = [r.json()["code"] for r in code_responses]
        assert len(set(codes)) == 50

        login_responses = await asyncio.gather(*[
            client.post(
                "/auth/login",
                json={"role": "demo_code", "credential": code},
                headers={"X-Forwarded-For": ip},
            )
            for ip, code in zip(visitor_ips, codes)
        ])

    statuses = [r.status_code for r in login_responses]
    assert all(s == 200 for s in statuses), f"Expected all 50 logins to succeed, got: {statuses}"
    tokens = [r.json()["access_token"] for r in login_responses]
    assert len(set(tokens)) == 50, "Two different visitors were issued the same JWT"


@pytest.mark.asyncio
async def test_same_visitor_ip_is_still_rate_limited(demo_api_base_url):
    """The opposite regression: confirms trusting X-Forwarded-For didn't
    quietly disable the per-IP limiter altogether. One visitor firing well
    past AUTH_LIMIT (10/min, core/middleware.py) auth requests in a burst
    must still get rejected."""
    visitor_ip = _next_visitor_ip()

    async with _visitor_client(demo_api_base_url) as client:
        responses = await asyncio.gather(*[
            client.post("/auth/demo-code", headers={"X-Forwarded-For": visitor_ip})
            for _ in range(15)
        ])

    statuses = [r.status_code for r in responses]
    assert 429 in statuses, f"Expected the per-IP auth limit to reject some of a 15-request burst, got: {statuses}"
    assert statuses.count(200) <= 10, f"More than AUTH_LIMIT successes from one IP in a single burst: {statuses}"
