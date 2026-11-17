#!/usr/bin/env python3
"""Run the real Bede API exactly as the image does, plus read-only counters.

    python instrumented_api.py --host 0.0.0.0 --port 8000 [--forwarded-allow-ips '*']

Imports `main.app` (real lifespan, real middleware, real engine) and serves it
with uvicorn on one worker with proxy headers, the same flags as
homeschool-api/Dockerfile's CMD. It adds no route and changes no behaviour. It
only observes, and writes one JSON snapshot of CUMULATIVE counters to
$CAPACITY_METRICS_PATH every half second (atomically, so a reader never sees a
partial file). The capacity run diffs two snapshots to get one step's numbers.

What it counts, and from where:
  * the DB pool: every acquisition through the pool class's own `_do_get`
    (time to get a connection, including opening one) and how many were
    checked out at that moment, as histograms, so a step's maximum and its
    p95 wait survive between samples;
  * every response status, and the client address uvicorn handed the app
    (after proxy headers), which is the address the per-IP rate limit keys on;
  * every 429 by the rate-limit bucket that refused it, read from the
    middleware's own audit detail rather than re-derived from the path;
  * this process's RSS, CPU time, threads, open file descriptors, disk I/O;
  * the transcription queue, if voice was used at all.

Test instrumentation only. Never part of a family's deployment.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from bisect import bisect_left
from pathlib import Path

WAIT_EDGES = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
STATE: dict = {
    "pool": {"acquisitions": 0, "contended": 0, "wait_sum_s": 0.0, "wait_hist": [0] * (len(WAIT_EDGES) + 1),
             "checkedout_hist": {}, "size": None, "max_overflow": None},
    "status": {}, "clients": {}, "rate_limited": {}, "requests": 0,
}
LOCK = threading.Lock()


def _instrument_pool() -> None:
    from core.database import engine
    pool = engine.sync_engine.pool
    cls = type(pool)
    original = cls._do_get
    STATE["pool"]["size"], STATE["pool"]["max_overflow"] = pool.size(), pool._max_overflow

    def timed(self):
        busy = self.checkedout()
        full = busy >= self.size() + max(self._max_overflow, 0)
        t0 = time.perf_counter()
        try:
            return original(self)
        finally:
            dt = time.perf_counter() - t0
            with LOCK:
                p = STATE["pool"]
                p["acquisitions"] += 1
                p["contended"] += int(full)
                p["wait_sum_s"] += dt
                p["wait_hist"][bisect_left(WAIT_EDGES, dt)] += 1
                k = str(busy + 1)
                p["checkedout_hist"][k] = p["checkedout_hist"].get(k, 0) + 1

    cls._do_get = timed  # class-level: also covers a pool recreated by dispose()


def _instrument_rate_limit() -> None:
    import core.middleware as mw
    from core.audit import AuditEvent
    original = mw.log_event

    async def counting(event, *a, **k):
        if event == AuditEvent.RATE_LIMITED:
            bucket = str(k.get("detail", "")).partition("bucket=")[2].split(" ")[0] or "unknown"
            with LOCK:
                STATE["rate_limited"][bucket] = STATE["rate_limited"].get(bucket, 0) + 1
        return await original(event, *a, **k)

    mw.log_event = counting


class Observe:
    """Outermost ASGI wrapper: sees the client address after uvicorn's proxy
    headers (what the rate limiter sees) and every response status."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        host = (scope.get("client") or ("none", 0))[0]

        async def wrapped(msg):
            if msg["type"] == "http.response.start":
                code = str(msg["status"])
                with LOCK:
                    STATE["requests"] += 1
                    STATE["status"][code] = STATE["status"].get(code, 0) + 1
                    STATE["clients"][host] = STATE["clients"].get(host, 0) + 1
            await send(msg)

        return await self.app(scope, receive, wrapped)


def _proc() -> dict:
    out: dict = {}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                out[line.split(":")[0].lower() + "_kb"] = int(line.split()[1])
            elif line.startswith("Threads:"):
                out["threads"] = int(line.split()[1])
        out["fds"] = len(os.listdir("/proc/self/fd"))
        for line in Path("/proc/self/io").read_text().splitlines():
            k, _, v = line.partition(":")
            if k in ("read_bytes", "write_bytes"):
                out[k] = int(v)
    except OSError:
        import resource
        out.setdefault("vmrss_kb", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        out.setdefault("threads", threading.active_count())
    t = os.times()
    out["cpu_s"] = t.user + t.system
    return out


def _transcription() -> dict | None:
    try:
        from services import transcription
    except Exception:
        return None
    sem = getattr(transcription, "_inference_semaphore", None)
    if sem is None:
        return None
    return {"free": sem._value, "waiting": len(getattr(sem, "_waiters", None) or [])}


SETTINGS_SHOWN = ("db_pool_size", "db_max_overflow", "rate_limit_api_per_minute", "rate_limit_auth_per_minute",
                  "rate_limit_voice_per_minute", "rate_limit_voice_stream_session_per_minute",
                  "voice_transcription_max_concurrency", "production")


def _writer(path: Path) -> None:
    from core.config import settings
    from core.database import engine
    tmp = path.with_suffix(".tmp")
    while True:
        with LOCK:
            snap = json.loads(json.dumps(STATE))
        pool = engine.sync_engine.pool
        snap["pool"]["checkedout_now"] = pool.checkedout()
        snap["t"] = time.time()
        snap["pid"] = os.getpid()
        snap["proc"] = _proc()
        snap["transcription"] = _transcription()
        snap["settings"] = {k: getattr(settings, k) for k in SETTINGS_SHOWN}
        tmp.write_text(json.dumps(snap))
        os.replace(tmp, path)
        time.sleep(0.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--forwarded-allow-ips", default="127.0.0.1")
    a = ap.parse_args()
    sys.path.insert(0, os.getcwd())
    import uvicorn
    import main as bede
    _instrument_pool()
    _instrument_rate_limit()
    path = Path(os.environ.get("CAPACITY_METRICS_PATH", "/tmp/capacity-metrics.json"))
    threading.Thread(target=_writer, args=(path,), daemon=True, name="capacity-metrics").start()
    # The same flags as homeschool-api/Dockerfile's CMD.
    uvicorn.run(Observe(bede.app), host=a.host, port=a.port, workers=1, proxy_headers=True,
                forwarded_allow_ips=a.forwarded_allow_ips, timeout_graceful_shutdown=120,
                access_log=False, lifespan="on")


if __name__ == "__main__":
    main()
