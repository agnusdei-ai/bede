"""Sample children (API clients) for the capacity run's API-client steps.

Each child is its own client address (httpx `local_address`, the
tests/test_demo_concurrency.py technique, or its own relay port on the docker
stack) and its own device, and sends exactly the requests the real app sends
(homeschool-tutor/src/services/api.ts): sign in as role child with the
learner's name and PIN, fetch that learner's config, then lesson turns over
POST /tutor/chat with a per-turn `turn_id`, `local_date` and
`local_time_of_day`, and now and then an answer to an approved practice item.

A turn is `ok` only when its stream carried the stub's reply AND ended with
`{"type":"done"}`; anything else is counted under what went wrong. There are
no retries: the real app retries a dropped connection, and this deliberately
does not, so a dropped turn shows up here rather than being hidden by a retry.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx

REPLY_MARK = "STUB-TUTOR"
MESSAGES = ["The river was the Nile.", "Farmers planted after the flood.", "They wrote on papyrus.",
            "The pharaoh ruled Egypt.", "The pyramids were tombs.", "I think the flood made the soil rich."]


@dataclass
class Child:
    name: str
    pin: str
    base: str                 # e.g. http://127.0.0.1:18402 or https://127.0.0.1:19010/api
    local_address: str | None = None
    verify: bool = True
    ua: str = field(default_factory=lambda: f"bede-capacity/{secrets.token_hex(4)}")
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))


def _time_of_day() -> str:
    h = datetime.now().hour
    return "morning" if h < 12 else "afternoon" if h < 18 else "evening"


def _client(c: Child, timeout: float) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(local_address=c.local_address, verify=c.verify, retries=0)
    return httpx.AsyncClient(base_url=c.base, transport=transport, headers={"User-Agent": c.ua},
                             timeout=httpx.Timeout(timeout, connect=10.0))


def _outcome_for_status(code: int) -> str:
    if code == 429:
        return "429"
    if code >= 500:
        return "5xx"
    return "4xx"


async def one_turn(http: httpx.AsyncClient, token: str, config: dict, history: list, text: str,
                   stall_s: float, timeout_s: float) -> dict:
    body = {"session_config": config, "current_subject": "history", "conversation_history": history[-6:],
            "child_message": text, "local_time_of_day": _time_of_day(), "local_date": date.today().isoformat(),
            "turn_id": "turn-" + secrets.token_hex(16), "session_id": None}
    t0 = time.monotonic()
    first = None
    reply = []
    done = False
    try:
        async with asyncio.timeout(timeout_s):
            async with http.stream("POST", "/tutor/chat", json=body,
                                   headers={"Authorization": f"Bearer {token}"}) as res:
                if res.status_code != 200:
                    return {"outcome": _outcome_for_status(res.status_code), "status": res.status_code}
                lines = res.aiter_lines()
                while True:
                    try:
                        line = await asyncio.wait_for(anext(lines), stall_s)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        return {"outcome": "stall", "status": 200}
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if ev.get("type") == "text":
                        if first is None:
                            first = time.monotonic() - t0
                        reply.append(ev.get("content", ""))
                    elif ev.get("type") == "done":
                        done = True
                        break
    except TimeoutError:
        return {"outcome": "timeout"}
    except httpx.HTTPError as exc:
        return {"outcome": "dropped", "error": type(exc).__name__}
    text_out = "".join(reply)
    if not done:
        return {"outcome": "dropped", "error": "stream ended without done"}
    if REPLY_MARK not in text_out:
        # Bede answered with its own fallback ("try again"): the turn was lost.
        return {"outcome": "error", "error": "fallback reply, not the model's"}
    history += [{"role": "user", "content": text}, {"role": "assistant", "content": text_out}]
    return {"outcome": "ok", "status": 200, "first_s": first, "done_s": time.monotonic() - t0}


async def run_child(c: Child, window_s: float, think_s: float, practice_every: int, stall_s: float,
                    timeout_s: float, start_gate: asyncio.Event) -> dict:
    """Sign in, then hold a steady lesson load for window_s. Returns this
    child's turns and practice answers."""
    out: dict = {"name": c.name, "turns": [], "answers": [], "errors": []}
    async with _client(c, timeout_s) as http:
        r = await http.post("/auth/login", json={"role": "child", "credential": c.pin, "student_name": c.name,
                                                 "device_id": c.device_id})
        if r.status_code != 200:
            out["errors"].append(f"login {r.status_code}")
            out["login_status"] = r.status_code
            return out
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await http.get(f"/pod/configs/{c.name}", headers=h)
        if r.status_code != 200:
            out["errors"].append(f"config {r.status_code}")
            return out
        config = r.json()
        r = await http.get(f"/practice/{c.name}/delivery", headers=h)
        sets = r.json() if r.status_code == 200 else []
        items = [(s["id"], it["index"]) for s in sets for it in s.get("items", [])]
        await start_gate.wait()
        history: list = []
        end = time.monotonic() + window_s
        n = 0
        while time.monotonic() < end:
            turn = await one_turn(http, token, config, history, MESSAGES[n % len(MESSAGES)], stall_s, timeout_s)
            turn["t"] = time.time()
            out["turns"].append(turn)
            n += 1
            if practice_every and items and n % practice_every == 0:
                set_id, idx = items[(n // practice_every - 1) % len(items)]
                try:
                    a = await http.post(f"/practice/{c.name}/sets/{set_id}/outcomes", headers=h,
                                        json={"item_index": idx, "response": "pharaoh"})
                    rec = {"set_id": set_id, "item": idx, "status": a.status_code}
                    if a.status_code == 200:
                        rec["already_recorded"] = bool(a.json().get("already_recorded"))
                except httpx.HTTPError as exc:
                    rec = {"set_id": set_id, "item": idx, "status": None, "error": type(exc).__name__}
                out["answers"].append(rec)
            await asyncio.sleep(think_s)
    return out


async def run_step(children: list[Child], window_s: float, think_s: float, practice_every: int,
                   stall_s: float, timeout_s: float) -> list[dict]:
    gate = asyncio.Event()
    tasks = [asyncio.create_task(run_child(c, window_s, think_s, practice_every, stall_s, timeout_s, gate))
             for c in children]
    # Everyone signs in first, then the steady window starts for all at once.
    await asyncio.sleep(min(30.0, 2.0 + 0.3 * len(children)))
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r if isinstance(r, dict) else {"name": c.name, "turns": [], "answers": [],
                                            "errors": [f"{type(r).__name__}: {r}"[:200]]}
            for c, r in zip(children, results)]


def practice_check(answers: list[dict], recorded: dict[str, set]) -> dict:
    """Did every accepted answer land exactly once? `recorded` maps
    "<learner>/<set_id>" to the item indices the server now holds.

    missing: an answer the server accepted (200) that is not recorded.
    duplicated: more than one answer to one item reported as newly recorded
    (already_recorded false), which a correct idempotent endpoint never does.
    429 and other refusals are counted, not treated as accepted."""
    first_writes: dict[tuple, int] = {}
    out = {"answered": len(answers), "accepted": 0, "missing": 0, "duplicated": 0, "429": 0, "refused": 0}
    for a in answers:
        if a.get("status") == 429:
            out["429"] += 1
            continue
        if a.get("status") != 200:
            out["refused"] += 1
            continue
        out["accepted"] += 1
        key = (a["learner"], a["set_id"], a["item"])
        if a["item"] not in recorded.get(f"{a['learner']}/{a['set_id']}", set()):
            out["missing"] += 1
        if not a.get("already_recorded"):
            first_writes[key] = first_writes.get(key, 0) + 1
    out["duplicated"] = sum(n - 1 for n in first_writes.values() if n > 1)
    out["refused"] = out["refused"]
    return out
