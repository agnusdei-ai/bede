"""The capacity run's arithmetic: percentiles, per-step verdicts, the supported
session count, which limit binds, and the written report.

Pure functions over plain dicts, no I/O except `write_evidence`, so every rule
that decides a number in the report is testable on a stated situation
(homeschool-api/tests/test_capacity_report.py). Report only: nothing here gates
anything.

Fail-closed rules this module owns:
  * A step that errored, never started, or produced no turns is never counted
    as supported, and nothing above it is either (supported counts are a
    contiguous run from the smallest step: a passing 12 above a failing 8 is
    noise, not capacity).
  * The required browser point (10 sessions) is PASS only when that exact
    step ran and passed; absent or unrun it is NOT_RUN, never PASS.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

FAILURE_CLASSES = ("response", "io", "memory", "threads_fds", "client_side")
LIMITS = ("db_pool", "rate_limit", "cpu", "memory", "model_stub")


def percentile(values: Iterable[float], q: float) -> float | None:
    """Nearest-rank percentile (the journeys' `pct`): the smallest value with at
    least q of the sample at or below it. None for an empty sample."""
    s = sorted(v for v in values if v is not None)
    if not s:
        return None
    if not 0 < q <= 1:
        raise ValueError("q must be in (0, 1]")
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def latency(values: Iterable[float]) -> dict:
    v = [x for x in values if x is not None]
    return {"n": len(v), "p50": percentile(v, 0.5), "p95": percentile(v, 0.95), "max": max(v) if v else None}


def summarize_turns(turns: list[dict]) -> dict:
    """Counts and latencies from one step's turn records. A turn record has an
    `outcome` (ok, 5xx, 4xx, 429, timeout, stall, dropped, error) and, for a
    completed turn, `first_s` and `done_s`."""
    outcomes: dict[str, int] = {}
    for t in turns:
        outcomes[t["outcome"]] = outcomes.get(t["outcome"], 0) + 1
    ok = [t for t in turns if t["outcome"] == "ok"]
    return {
        "turns": len(turns),
        "completed": len(ok),
        "outcomes": outcomes,
        "first_token_s": latency(t.get("first_s") for t in ok),
        "full_turn_s": latency(t.get("done_s") for t in ok),
    }


def baseline_first_token(steps: list[dict]) -> float | None:
    """The one-session step's median first-token time: the stub's own fixed
    delay plus Bede's uncontended overhead. Excess over it is contention."""
    for s in sorted(steps, key=lambda s: s["sessions"]):
        if s.get("status") == "ran" and s["sessions"] == 1:
            return s.get("summary", {}).get("first_token_s", {}).get("p50")
    return None


def _n(d: dict | None, *keys, default=0):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
    return default if d is None else d


def step_verdict(step: dict, th: dict, baseline: float | None) -> dict:
    """Whether one step met every threshold, why not, and which failure classes
    appeared. Unknown data never passes: a missing baseline, a missing
    summary, or a step that did not run all fail."""
    reasons: list[str] = []
    classes: set[str] = set()
    if step.get("status") != "ran":
        return {"passed": False, "reasons": [f"step {step.get('status', 'missing')}: {step.get('error', '')}".strip()],
                "classes": []}
    summ = step.get("summary") or {}
    oc = summ.get("outcomes", {})

    def bad(cls, msg):
        classes.add(cls)
        reasons.append(msg)

    n5 = oc.get("5xx", 0)
    if n5 > th["max_5xx"]:
        bad("response", f"{n5} server errors (5xx)")
    n429 = oc.get("429", 0) + _n(step, "practice", "429")
    if n429 > th["max_429"]:
        bad("response", f"{n429} refused by the rate limit (429)")
    if oc.get("timeout", 0) > th["max_timeouts"]:
        bad("response", f"{oc['timeout']} turns timed out")
    if oc.get("stall", 0) > th["max_sse_stalls"]:
        bad("response", f"{oc['stall']} reply streams stalled")
    dropped = (oc.get("dropped", 0) + oc.get("error", 0) + oc.get("4xx", 0)
               + _n(step, "practice", "missing") + _n(step, "practice", "refused"))
    if dropped > th["max_dropped_turns"]:
        bad("response", f"{dropped} dropped turns or answers")
    dup = _n(step, "duplicated_turns") + _n(step, "practice", "duplicated")
    if dup > th["max_duplicated_turns"]:
        bad("response", f"{dup} duplicated turns or answers")
    if step.get("session_errors"):
        bad("response", "session errors: " + "; ".join(step["session_errors"][:3]))
    short = [k for k, v in (step.get("turns_per_session") or {}).items() if v < th["min_turns_per_session"]]
    if not summ.get("completed") or short or len(step.get("turns_per_session") or {}) < step["sessions"]:
        bad("response", f"not every session completed a turn ({len(short)} short)")
    p95 = _n(summ, "first_token_s", "p95", default=None)
    if p95 is None or baseline is None:
        reasons.append("no first-token measurement or no one-session baseline")
    else:
        if p95 - baseline > th["first_token_p95_excess_s"]:
            bad("response", f"first-token p95 {p95:.2f}s is {p95 - baseline:.2f}s over the one-session median")
        if p95 > th["first_token_p95_max_s"]:
            bad("response", f"first-token p95 {p95:.2f}s over the {th['first_token_p95_max_s']}s ceiling")

    cont = step.get("container") or {}
    if not th.get("allow_oom_or_restart") and (cont.get("oom_killed") or cont.get("restarts", 0) > 0 or step.get("api_restarted")):
        bad("memory", "the API container was OOM-killed or restarted")
    rss_frac = _n(step, "api", "rss_fraction_of_limit", default=None)
    if rss_frac is not None and rss_frac > th["rss_fraction_of_limit_max"]:
        bad("memory", f"API memory at {rss_frac:.0%} of its limit")
    logs = step.get("log_errors") or {}
    for cls in ("io", "memory", "threads_fds"):
        if logs.get(cls):
            bad(cls, f"{logs[cls]} {cls.replace('_', '/')} errors in the API log")
    host = step.get("host") or {}
    if _n(host, "cpu_fraction_p75") > th["client_host_cpu_fraction_max"]:
        bad("client_side", f"the runner's CPU stayed at {host['cpu_fraction_p75']:.0%} or more for a quarter of the step")
    if _n(host, "mem_fraction_max") > th["client_host_mem_fraction_max"]:
        bad("client_side", f"the runner's memory reached {host['mem_fraction_max']:.0%}")
    passed = not reasons
    return {"passed": passed, "reasons": reasons, "classes": sorted(classes)}


def supported_sessions(steps: list[dict]) -> int:
    """Largest step count such that it and every smaller step ran and passed.
    0 when the smallest step did not pass (or nothing ran)."""
    best = 0
    for s in sorted(steps, key=lambda s: s["sessions"]):
        if not (s.get("verdict") or {}).get("passed"):
            break
        best = s["sessions"]
    return best


def required_point(steps: list[dict], required: int) -> dict:
    """PASS/FAIL/NOT_RUN at the required session count, with the reason."""
    s = next((s for s in steps if s["sessions"] == required), None)
    if s is None or s.get("status") != "ran":
        why = "no step at this count ran" if s is None else f"the step did not run: {s.get('error', s.get('status'))}"
        return {"sessions": required, "result": "NOT_RUN", "reason": why}
    v = s.get("verdict") or {}
    if v.get("passed"):
        return {"sessions": required, "result": "PASS", "reason": "every threshold met"}
    return {"sessions": required, "result": "FAIL", "reason": "; ".join(v.get("reasons") or ["no verdict"])}


def first_failure_by_class(steps: list[dict]) -> dict:
    out: dict[str, int | None] = {c: None for c in FAILURE_CLASSES}
    for s in sorted(steps, key=lambda s: s["sessions"]):
        for c in (s.get("verdict") or {}).get("classes", []):
            if out.get(c) is None:
                out[c] = s["sessions"]
    return out


def utilisation(step: dict, pool_wait_s: float = 0.25) -> dict:
    """Each limit's use at one step as a fraction of what it allows. None where
    the run could not see it (for example no stub calls were logged)."""
    api = step.get("api") or {}
    pool = None
    if api.get("pool_capacity"):
        pool = api.get("pool_checkedout_max", 0) / api["pool_capacity"]
        if _n(api, "pool_wait_p95_s") > pool_wait_s:  # requests queued for a connection: the pool is full
            pool = max(pool, 1.0)
    rate = None
    for bucket, used in (step.get("rate", {}).get("busiest_client_per_min") or {}).items():
        lim = (step.get("rate", {}).get("limits") or {}).get(bucket)
        if lim:
            rate = max(rate or 0.0, used / lim)
    if step.get("rate", {}).get("refused_by_bucket"):
        rate = max(rate or 0.0, 1.0)
    stub = None
    st = step.get("stub") or {}
    if st.get("p95_s") and st.get("configured_s"):
        # 1.0 means the stub's calls ran 50% slower than configured: the stub
        # itself is then the bottleneck, not Bede.
        stub = max(0.0, (st["p95_s"] / st["configured_s"] - 1.0) / 0.5)
    return {
        "db_pool": pool,
        "rate_limit": rate,
        "cpu": api.get("cpu_fraction_p75"),
        "memory": api.get("rss_fraction_of_limit"),
        "model_stub": stub,
    }


def binding_limit(steps: list[dict], supported: int, pool_wait_s: float = 0.25) -> dict:
    """The limit closest to binding: judged at the first failing step if there
    is one (what actually broke), else at the supported step (what is nearest).
    The model stub is reported as binding only when its calls ran at least 50%
    slower than configured (see `utilisation`)."""
    ordered = sorted(steps, key=lambda s: s["sessions"])
    failing = next((s for s in ordered if s["sessions"] > supported and s.get("status") == "ran"), None)
    at = failing or next((s for s in ordered if s["sessions"] == supported), None)
    if at is None:
        return {"limit": None, "at_sessions": None, "utilisation": {}, "basis": "no step ran"}
    u = utilisation(at, pool_wait_s)
    scored = {k: v for k, v in u.items() if v is not None}
    limit = max(scored, key=scored.get) if scored else None
    basis = "first failing step" if failing else "supported step (nothing failed)"
    return {"limit": limit, "at_sessions": at["sessions"], "utilisation": u, "basis": basis}


def judge(steps: list[dict], th: dict, required: int | None = None) -> dict:
    base = baseline_first_token(steps)
    for s in steps:
        s["verdict"] = step_verdict(s, th, base)
    sup = supported_sessions(steps)
    out = {"baseline_first_token_s": base, "supported_sessions": sup,
           "first_failure_by_class": first_failure_by_class(steps), "binding": binding_limit(steps, sup, th.get("pool_wait_p95_max_s", 0.25))}
    if required is not None:
        out["required"] = required_point(steps, required)
    return out


def _public(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _f(v, fmt="{:.2f}"):
    return "-" if v is None else fmt.format(v)


def markdown(report: dict) -> str:
    """The human report. Says plainly what kind of run this was."""
    meta = report["meta"]
    lines = [f"# Bede capacity run: {meta['sha'][:12]}", "",
             f"- Target: **{meta['target']}** ({meta['layout']})",
             f"- Model: {meta['model']}; stub delays {_public(meta.get('stub', {}))}",
             f"- Settings: {'**NON-DEFAULT** ' if meta.get('non_default') else 'shipped defaults '}{meta.get('settings', {})}",
             f"- Client addresses: {meta.get('client_addresses', 'not recorded')}",
             f"- Reference: Family Membership seats = {meta.get('reference_seats')} (a line, not a gate)",
             "- Report only. This run gates nothing.", ""]
    for kind in ("browser", "api"):
        part = report.get(kind)
        if not part:
            lines += [f"## {kind}: NOT_RUN", "", f"{report.get(kind + '_not_run', 'not requested')}", ""]
            continue
        j = part["judgement"]
        lines += [f"## {'Real Chromium sessions' if kind == 'browser' else 'API clients'}", ""]
        if "required" in j:
            r = j["required"]
            lines += [f"**At {r['sessions']} sessions: {r['result']}** ({r['reason']})", ""]
        b = j["binding"]
        lines += [f"Supported sessions: **{j['supported_sessions']}**. "
                  f"Closest limit: **{b['limit'] or 'none observed'}** at {b['at_sessions']} sessions ({b['basis']}).", "",
                  "First step each failure class appeared: " + ", ".join(
                      f"{c}={v if v is not None else '-'}" for c, v in j["first_failure_by_class"].items()), "",
                  "| sessions | status | turns ok/all | first token p50/p95/max s | full turn p50/p95/max s | 5xx | 429 | dropped | dup | API RSS MB | API CPU | threads | fds | pool peak demand/cap | pool wait p95 s | host CPU/mem | verdict |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        seats = meta.get("reference_seats")
        for s in sorted(part["steps"], key=lambda s: s["sessions"]):
            sm = s.get("summary") or {}
            oc = sm.get("outcomes", {})
            ft, fu = sm.get("first_token_s", {}), sm.get("full_turn_s", {})
            api, host, v = s.get("api") or {}, s.get("host") or {}, s.get("verdict") or {}
            mark = " (seats)" if s["sessions"] == seats else ""
            lines.append("| " + " | ".join([
                f"{s['sessions']}{mark}", s.get("status", "-"), f"{sm.get('completed', 0)}/{sm.get('turns', 0)}",
                f"{_f(ft.get('p50'))}/{_f(ft.get('p95'))}/{_f(ft.get('max'))}",
                f"{_f(fu.get('p50'))}/{_f(fu.get('p95'))}/{_f(fu.get('max'))}",
                str(oc.get("5xx", 0)), str(oc.get("429", 0) + _n(s, "practice", "429")),
                str(oc.get("dropped", 0) + oc.get("error", 0) + oc.get("4xx", 0)
                    + _n(s, "practice", "missing") + _n(s, "practice", "refused")),
                str(_n(s, "duplicated_turns") + _n(s, "practice", "duplicated")),
                _f(api.get("rss_mb_max"), "{:.0f}"), _f(api.get("cpu_fraction_p75"), "{:.0%}"),
                str(api.get("threads_max", "-")), str(api.get("fds_max", "-")),
                f"{api.get('pool_checkedout_max', '-')}/{api.get('pool_capacity', '-')}", _f(api.get("pool_wait_p95_s"), "{:.3f}"),
                f"{_f(host.get('cpu_fraction_p75'), '{:.0%}')}/{_f(host.get('mem_fraction_max'), '{:.0%}')}",
                "PASS" if v.get("passed") else ("FAIL: " + "; ".join(v.get("reasons", []))[:160]),
            ]) + " |")
        lines.append("")
    lines += ["## What this does not measure", "",
              "- The model is a loopback stub with fixed delays, not a real model: real model latency is not in these numbers.",
              "- A CI runner is not a family's server (a Raspberry Pi or a mini PC): read the shape of the curve, not the absolute count.",
              "- Voice was not exercised, so the transcription queue (VOICE_TRANSCRIPTION_MAX_CONCURRENCY) is not measured here.", ""]
    return "\n".join(lines)


def write_evidence(out: Path, report: dict) -> None:
    """report.json, report.md and SHA256SUMS over every file in the directory."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True, default=str), encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    sums = []
    for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(out).as_posix()}")
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
