"""G1 voice binding: browser, direct API and SSE must agree. Run by hand.

    cd homeschool-api && python scripts/g1_browser_check.py [report.json]

Optionally with G1_TEST_DATABASE_URL set to a NON-superuser Postgres URL.

What it does, all with synthetic data:

1. Serves the assembled API on 127.0.0.1:8000 through tests/g1_harness.py
   (a real uvicorn server), seeding Synthetic Campus One/Two, Teacher One/Two
   and two learners with the SAME display name through the real admin routes.
   Transcription is a synthetic echo, so no model or audio stack is needed.
2. Runs the same voice scenarios twice: directly against the API with httpx
   (reading SSE incrementally), and in a real Chromium page on the app's own
   origin, driving the app's REAL frontend modules through the real Vite dev
   server and its /api proxy (scripts/g1_browser_check.cjs).
3. Compares the two and prints one JSON report. Exit status 0 only if every
   scenario agrees AND matches the expected G1 outcome.

Needs: the frontend's node_modules (npm ci in homeschool-tutor), Node, and a
Playwright install whose browsers are on PLAYWRIGHT_BROWSERS_PATH. Nothing
here runs in CI; the pytest suites cover the API and SSE halves there.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

API_DIR = pathlib.Path(__file__).resolve().parents[1]
TUTOR_DIR = API_DIR.parent / "homeschool-tutor"
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(API_DIR / "tests"))

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("SECRET_KEY", "g1-browser-check-secret-" + "x" * 32)
os.environ.setdefault("MASTER_SECRET", "g1-browser-check-master-" + "y" * 32)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost/unused")

import httpx  # noqa: E402
from _pytest.monkeypatch import MonkeyPatch  # noqa: E402

UNKNOWN = {"type": "error", "message": "unknown or expired session"}
VITE_PORT = 5199


def _echo_transcription(mp):
    import services.pilot_authz as pilot_authz
    import services.streaming_transcription as st

    async def echo(audio_bytes, language="en"):
        return {"text": audio_bytes[-12:].decode("ascii", "ignore"), "language": language}
    mp.setattr(st, "transcribe_audio", echo)
    mp.setattr(st, "partial_passes_are_affordable", lambda: True)
    mp.setattr(pilot_authz, "REVALIDATE_INTERVAL_SECONDS", 0.2)


def _sse(response):
    for line in response.iter_lines():
        if line.startswith("data:"):
            yield json.loads(line[5:].strip())


def _pcm(tag: str) -> dict:
    return {"audio": ("chunk.wav", b"\x00\x01" * 12 + tag.encode(), "audio/wav")}


def api_scenarios(w) -> dict:
    """The same scenarios as the browser, sent straight to the API."""
    c, one, two = w.client, w.teacher(w.teacher_one), w.teacher(w.teacher_two)
    out = {}

    sid = c.post("/voice/stream/start", json={"learner_id": w.learner_one}, headers=one).json()["session_id"]
    c.post(f"/voice/stream/{sid}/chunk", files=_pcm("api-one....."), headers=one)
    items = []
    with c.stream("GET", f"/voice/stream/{sid}/events", headers=one) as r:
        events = _sse(r)
        for item in events:
            items.append(item)
            if item["type"] == "partial":
                break
        c.post(f"/voice/stream/{sid}/finish", headers=one)
        items.extend(events)
    out["authorized"] = {"types": [i["type"] for i in items], "first": items[0]}

    r = c.post("/voice/stream/start", json={"learner_id": w.learner_one}, headers=two)
    out["crossCampusStart"] = [r.status_code, r.json()]

    sid = c.post("/voice/stream/start", json={"learner_id": w.learner_one}, headers=one).json()["session_id"]
    with c.stream("GET", f"/voice/stream/{sid}/events", headers=two) as r:
        out["copiedSessionSubscribe"] = list(_sse(r))

    sid = c.post("/voice/stream/start", json={"learner_id": w.learner_one}, headers=one).json()["session_id"]
    c.post(f"/voice/stream/{sid}/chunk", files=_pcm("before-revo."), headers=one)
    items = []
    with c.stream("GET", f"/voice/stream/{sid}/events", headers=one) as r:
        events = _sse(r)
        for item in events:
            items.append(item)
            if item["type"] == "partial":
                break
        w.revoke(w.campus_one, w.teacher_one, w.learner_one)
        items.extend(events)
    out["revocation"] = {"items": items}
    with c.stream("GET", f"/voice/stream/{sid}/events", headers=w.teacher(w.teacher_one)) as r:
        out["reconnect"] = list(_sse(r))
    return out


def browser_scenarios(w) -> dict:
    vite = subprocess.Popen(
        ["npx", "vite", "--port", str(VITE_PORT), "--strictPort", "--host", "127.0.0.1"],
        cwd=TUTOR_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    app = f"http://127.0.0.1:{VITE_PORT}"
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"{app}/src/services/voiceApi.ts", timeout=5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Vite dev server did not start")
            time.sleep(0.5)
        ev = w.credential_version(w.teacher_one)
        payload = {
            "app": app, "api": str(w.client.base_url).rstrip("/"),
            "admin": w.admin()["Authorization"].split()[1],
            "one": w.teacher(w.teacher_one)["Authorization"].split()[1],
            # Revocation bumps the credential version by one: the token a
            # teacher would hold after signing in again.
            "oneNext": w.teacher(w.teacher_one, ev=ev + 1)["Authorization"].split()[1],
            "two": w.teacher(w.teacher_two)["Authorization"].split()[1],
            "learnerOne": w.learner_one, "campusOne": w.campus_one, "teacherOne": w.teacher_one,
        }
        env = dict(os.environ, BEDE_G1_INPUT=json.dumps(payload))
        env.setdefault("NODE_PATH", subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip())
        proc = subprocess.run(["node", str(API_DIR / "scripts" / "g1_browser_check.cjs")],
                              capture_output=True, text=True, env=env, timeout=180)
        report = json.loads(proc.stdout or '{"ok": false, "error": %s}' % json.dumps(proc.stderr[-2000:]))
        if not report.get("ok"):
            raise RuntimeError(report.get("error"))
        return report["result"]
    finally:
        vite.terminate()
        vite.wait(timeout=20)


def main() -> int:
    from g1_harness import backend_name, g1_world

    mp = MonkeyPatch()
    try:
        _echo_transcription(mp)
        with g1_world(mp, port=8000) as w:
            api = api_scenarios(w)
            w.grant(w.campus_one, w.teacher_one, w.learner_one)  # a new grant version
            browser = browser_scenarios(w)
            revocations = [e["detail"] for e in w.audit_events()
                           if e.get("event") == "authz.revoked_in_flight"]
    finally:
        mp.undo()

    expected_types = ["partial", "final", "done"]
    checks = {
        "authorized_stream_agrees": api["authorized"]["types"] == browser["authorized"]["types"] == expected_types,
        "permitted_event_received": api["authorized"]["first"]["type"] == browser["authorized"]["first"]["type"] == "partial",
        "cross_campus_start_denied": api["crossCampusStart"] == [404, {"detail": "Record not found"}]
        and browser["crossCampusStart"] == "Could not start voice streaming",
        "copied_session_subscribe_denied": api["copiedSessionSubscribe"] == browser["copiedSessionSubscribe"] == [UNKNOWN],
        "revocation_closes_stream": api["revocation"]["items"][-1] == browser["revocation"]["items"][-1] == UNKNOWN
        and [i["type"] for i in api["revocation"]["items"]] == [i["type"] for i in browser["revocation"]["items"]]
        == ["partial", "error"],
        "admin_revoke_accepted": browser["revokeStatus"] == 204,
        "reconnect_after_revocation_denied": api["reconnect"] == browser["reconnect"] == [UNKNOWN],
        "revocations_audited": sum("stage=voice.events" in d for d in revocations) >= 2,
    }
    report = {"backend": backend_name(), "checks": checks, "api": api, "browser": browser}
    text = json.dumps(report, indent=2)
    if len(sys.argv) > 1:  # the app logs to stdout; give the report its own file
        pathlib.Path(sys.argv[1]).write_text(text)
    print(text)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
