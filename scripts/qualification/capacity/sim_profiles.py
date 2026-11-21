"""Planning simulation of concurrent learning on a shared inference server.

WHAT THIS IS. A discrete-event model of N actively learning users sharing one
inference server, run against the owner's capacity thresholds (docs/design/
AFFORDABLE_OPEN_WEIGHT_PATH.md section 7). It answers two planning questions:

  1. What decode and prefill throughput must a model/runtime/hardware profile
     deliver for 10 (household) or 30 (school) active users to meet the
     thresholds? (`required_throughput`)
  2. Would a profile with given throughput meet them? (`simulate`)

WHAT THIS IS NOT. It is not a measurement and it qualifies nothing. Its inputs
are throughput numbers and token counts; every one carries a `basis` so a
reader can see which are assumptions and which came from a project document.
A profile with `measured: null` is reported NOT_MEASURED and can never be
called qualified from here. It says nothing about educational quality, which
only the evaluation can. It models time, not content: no learner text exists
in it, and nothing is shared or cached across users except the constant prefix
cost, which is a throughput parameter.

MODEL. One server runs up to `slots` jobs at once. Active jobs share the
server's compute (processor sharing); aggregate speed with k active jobs is
k**batch_alpha (0 = batching gives nothing, 1 = perfect), so each job runs at
k**(batch_alpha - 1) of its solo speed. More jobs than slots wait FIFO, and
that wait counts, because the thresholds are measured from the user's
submission. Each turn is a moderation call followed by the tutor call (a tool
activity has two tutor rounds), exactly as the application runs them.
"""
from __future__ import annotations

import heapq
import json
import random
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

# The owner's thresholds (seconds), measured from submission, p95 unless noted.
THRESHOLDS = {
    "first_useful_p95_s": 5.0,
    "hint_done_p95_s": 12.0,
    "tool_ready_p95_s": 15.0,
    "deterministic_p95_s": 0.5,
    "turn_deadline_s": 30.0,
}
FIRST_USEFUL_TOKENS = 20   # a first useful response is the opening of the reply
DETERMINISTIC_S = 0.05     # app-side check; measured for real by the harness


@dataclass(frozen=True)
class Profile:
    name: str
    prefill_tok_s: float          # solo prefill speed
    decode_tok_s: float           # solo decode speed
    slots: int = 4                # jobs run together
    batch_alpha: float = 0.5      # aggregate speed = k ** alpha
    prefix_cache_hit: float = 0.0 # fraction of the prompt reused from a shared constant prefix
    basis: str = "assumption"     # "assumption" | "project_doc" | "measured"
    measured: Optional[bool] = None  # True only when a real run backs the numbers


@dataclass(frozen=True)
class Workload:
    users: int
    pattern: str = "staggered"        # "staggered" | "burst"
    prompt_tokens: int = 17000        # full prompt, history included (project doc, unmeasured)
    moderation_tokens: int = 400
    think_s: float = 20.0             # mean time a user spends reading or writing
    burst_cycle_s: float = 60.0
    deterministic_share: float = 0.3  # routine practice answered by code
    mix: Dict[str, float] = field(default_factory=lambda: {
        "tutor": 0.5, "hint": 0.3, "tool": 0.2})
    out_tokens: Dict[str, int] = field(default_factory=lambda: {
        "tutor": 250, "hint": 120, "tool_r1": 80, "tool_r2": 200})
    duration_s: float = 7200.0
    seed: int = 1


class _Job:
    __slots__ = ("work_prefill", "work_decode", "done", "t_submit", "t_first", "cb", "first_work", "t_end")

    def __init__(self, prefill_s, decode_s, first_s, t, cb):
        self.work_prefill, self.work_decode, self.first_work = prefill_s, decode_s, prefill_s + first_s
        self.done, self.t_submit, self.t_first, self.cb, self.t_end = 0.0, t, None, cb, None


class _Server:
    def __init__(self, p: Profile):
        self.p, self.t, self.active, self.queue = p, 0.0, [], []

    def submit(self, job):
        (self.active if len(self.active) < self.p.slots else self.queue).append(job)

    def _rate(self):
        k = len(self.active)
        return k ** (self.p.batch_alpha - 1.0) if k else 1.0

    def next_event(self):
        """Time of the next job milestone (first token or finish), or None."""
        if not self.active:
            return None
        r, best = self._rate(), None
        for j in self.active:
            total = j.work_prefill + j.work_decode
            targets = [total - j.done]
            if j.t_first is None:
                targets.append(j.first_work - j.done)
            dt = min(targets) / r
            best = dt if best is None or dt < best else best
        return self.t + best

    def advance(self, t_new):
        dt = t_new - self.t
        if dt > 0 and self.active:
            r = self._rate()
            for j in self.active:
                j.done += dt * r
        self.t = t_new
        finished = []
        for j in self.active:
            if j.t_first is None and j.done >= j.first_work - 1e-9:
                j.t_first = self.t
            if j.done >= j.work_prefill + j.work_decode - 1e-9:
                j.t_end = self.t
                finished.append(j)
        for j in finished:
            self.active.remove(j)
        while self.queue and len(self.active) < self.p.slots:
            self.active.append(self.queue.pop(0))
        return finished


def _job(p: Profile, prompt_tokens, out_tokens, t, cb):
    eff_prompt = prompt_tokens * (1.0 - p.prefix_cache_hit)
    prefill_s = eff_prompt / p.prefill_tok_s
    decode_s = out_tokens / p.decode_tok_s
    return _Job(prefill_s, decode_s, min(FIRST_USEFUL_TOKENS, out_tokens) / p.decode_tok_s, t, cb)


def _pct(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs) + 0.999999) - 1)]


def simulate(profile: Profile, w: Workload) -> dict:
    """Run one workload against one profile and report latencies by workload
    and by user. Pure and deterministic for a given seed."""
    rng = random.Random(w.seed)
    srv = _Server(profile)
    events: list = []   # (time, seq, kind, user)
    seq = 0

    def push(t, kind, user):
        nonlocal seq
        seq += 1
        heapq.heappush(events, (t, seq, kind, user))

    lat: Dict[str, Dict[int, List[float]]] = {k: {} for k in ("first_useful", "hint", "tool", "tutor", "deterministic")}
    over_deadline = 0
    turns = 0

    def record(kind, user, value):
        lat[kind].setdefault(user, []).append(value)

    def start_turn(user, t):
        nonlocal turns
        turns += 1
        if rng.random() < w.deterministic_share:
            record("deterministic", user, DETERMINISTIC_S)
            return schedule_next(user, t + DETERMINISTIC_S)
        r, acc, kind = rng.random(), 0.0, "tutor"
        for k, share in w.mix.items():
            acc += share
            if r <= acc:
                kind = k
                break
        run_pipeline(user, t, kind)

    def run_pipeline(user, t_submit, kind):
        rounds = ["tool_r1", "tool_r2"] if kind == "tool" else [kind]

        def moderation_done(job):
            go(0, job.t_end)

        def go(i, t):
            outs = w.out_tokens[rounds[i]]

            def finished(job, i=i):
                nonlocal over_deadline
                if i == 0:
                    record("first_useful", user, job.t_first - t_submit)
                if i + 1 < len(rounds):
                    return go(i + 1, job.t_end)
                total = job.t_end - t_submit
                record(kind, user, total)
                if total > THRESHOLDS["turn_deadline_s"]:
                    over_deadline += 1
                schedule_next(user, job.t_end)

            srv.submit(_job(profile, w.prompt_tokens, outs, t, finished))

        srv.submit(_job(profile, w.moderation_tokens, 30, t_submit, moderation_done))

    def schedule_next(user, t_done):
        if w.pattern == "burst":
            cycle = int(t_done // w.burst_cycle_s) + 1
            push(cycle * w.burst_cycle_s, "turn", user)
        else:
            push(t_done + rng.expovariate(1.0 / w.think_s), "turn", user)

    for u in range(w.users):
        if w.pattern == "burst":
            push(0.0, "turn", u)
        else:
            push(rng.uniform(0, w.think_s), "turn", u)

    while True:
        nxt_job = srv.next_event()
        nxt_ev = events[0][0] if events else None
        cands = [x for x in (nxt_job, nxt_ev) if x is not None]
        if not cands:
            break
        t = min(cands)
        if t > w.duration_s:
            break
        if nxt_job is not None and nxt_job <= (nxt_ev if nxt_ev is not None else nxt_job + 1):
            for j in srv.advance(nxt_job):
                j.cb(j)
        else:
            _, _, _, user = heapq.heappop(events)
            srv.advance(nxt_ev)
            start_turn(user, nxt_ev)

    def summarize(kind):
        allv = [v for vs in lat[kind].values() for v in vs]
        per_user = {u: _pct(vs, 0.95) for u, vs in lat[kind].items()}
        return {"n": len(allv), "p95_s": _pct(allv, 0.95),
                "worst_user_p95_s": max(per_user.values()) if per_user else 0.0}

    report = {k: summarize(k) for k in lat}
    report["over_deadline"] = over_deadline
    report["turns"] = turns
    checks = {
        "first_useful": report["first_useful"]["worst_user_p95_s"] <= THRESHOLDS["first_useful_p95_s"],
        "hint": report["hint"]["worst_user_p95_s"] <= THRESHOLDS["hint_done_p95_s"],
        "tool": report["tool"]["worst_user_p95_s"] <= THRESHOLDS["tool_ready_p95_s"],
        "deterministic": report["deterministic"]["worst_user_p95_s"] <= THRESHOLDS["deterministic_p95_s"],
        "deadline": over_deadline == 0,
    }
    report["checks"] = checks
    report["meets_thresholds"] = all(checks.values())
    report["verdict"] = (
        "NOT_MEASURED" if profile.measured is not True else
        ("PASS" if report["meets_thresholds"] else "FAIL"))
    report["planning_only"] = profile.measured is not True
    return report


def meets(profile: Profile, w: Workload, seeds=(1, 2, 3)) -> bool:
    """Thresholds must hold for every seed, so a lucky run cannot pass."""
    return all(simulate(profile, replace(w, seed=s))["meets_thresholds"] for s in seeds)


def required_throughput(w: Workload, base: Profile, prefill_over_decode: float = 8.0,
                        lo: float = 1.0, hi: float = 4000.0) -> Optional[float]:
    """Smallest solo decode speed (tok/s) at which `base` meets every threshold
    for workload `w`, with prefill fixed at `prefill_over_decode` times decode.
    None if even `hi` is not enough. Planning figure, not a measurement."""
    def ok(d):
        return meets(replace(base, decode_tok_s=d, prefill_tok_s=d * prefill_over_decode), w)
    if not ok(hi):
        return None
    for _ in range(18):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    return round(hi, 1)


def load_profiles(path: str) -> List[Profile]:
    data = json.load(open(path, encoding="utf-8"))
    return [Profile(**p) for p in data["profiles"]]


def planning_table(users_list=(10, 30), duration_s=1800.0, prefill_over_decode=40.0) -> List[dict]:
    """Required solo decode speed (prefill fixed at a multiple of decode, 40x by
    default, between the project document's CPU-class 42x and GPU-class 530x) per lever,
    worst of the staggered and burst patterns. A planning figure only."""
    levers = [
        ("full prompt, everything through the model", dict(prompt_tokens=17000, deterministic_share=0.0), 0.0),
        ("code answers 50% of routine items", dict(prompt_tokens=17000, deterministic_share=0.5), 0.0),
        ("shared constant prefix reused (90%)", dict(prompt_tokens=17000, deterministic_share=0.0), 0.9),
        ("code 50% + shared prefix 90%", dict(prompt_tokens=17000, deterministic_share=0.5), 0.9),
        ("compact 6k prompt (assumed) + code 50% + prefix 90%", dict(prompt_tokens=6000, deterministic_share=0.5), 0.9),
    ]
    rows = []
    for label, kw, hit in levers:
        row = {"lever": label}
        for n in users_list:
            need = []
            for pattern in ("staggered", "burst"):
                base = Profile("probe", 1, 1, slots=8, batch_alpha=0.7, prefix_cache_hit=hit)
                need.append(required_throughput(
                    Workload(users=n, pattern=pattern, duration_s=duration_s, **kw), base,
                    prefill_over_decode=prefill_over_decode))
            row[n] = None if None in need else max(need)
        rows.append(row)
    return rows


if __name__ == "__main__":
    import sys
    rows = planning_table()
    print("Prefill assumed 40x decode (CPU-class); 8 slots, batching alpha 0.7.\n")
    print("| Design lever | 10 users: decode tok/s needed | 30 users: decode tok/s needed |")
    print("|---|---|---|")
    for r in rows:
        f = lambda v: "more than 4000" if v is None else f"{v:g}"
        print(f"| {r['lever']} | {f(r[10])} | {f(r[30])} |")
    sys.exit(0)
