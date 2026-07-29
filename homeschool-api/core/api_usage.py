"""
Token usage + cost tracking for this deployment's own Anthropic API key.

This deployment is BYOK (see .env.example's ANTHROPIC_API_KEY) — Bede
itself is never billed for any of this; Anthropic bills the family's own
key directly, and console.anthropic.com remains the authoritative source
of truth for actual spend. This module is a best-effort, in-app estimate
(per-student on Progress.tsx, household-wide on GET /admin/status) so a
parent can see, without leaving Bede, roughly how a student's session
frequency is translating into usage — never a substitute for Anthropic's
own billing records.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

# $ per 1M tokens, from Anthropic's published pricing for the models this
# deployment actually uses (core/config.py's tutor_model/session_model).
# Anthropic doesn't expose pricing via the Messages API itself, so this is
# a maintained constant, not a live lookup — update alongside either
# model setting if it ever changes. cache_write/cache_read cover prompt
# caching (services/ai_service.py marks the static persona/tools blocks
# `cache_control: ephemeral`), without which a cache-heavy session's
# estimate would look far more expensive than it actually is.
_PRICING_PER_MILLION = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
}
# Falls back to Sonnet's own pricing for an unrecognized model id (a
# rename, a config change this module hasn't caught up with yet) rather
# than raising — a stale price constant must never break the usage
# dashboard, only make one model's estimate slightly less exact.
_DEFAULT_PRICING = _PRICING_PER_MILLION["claude-sonnet-4-6"]


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Best-effort USD estimate for one call's worth of usage — an
    approximation for the in-app dashboard, not a bill."""
    pricing = _PRICING_PER_MILLION.get(model, _DEFAULT_PRICING)
    return (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_creation_tokens * pricing["cache_write"]
        + cache_read_tokens * pricing["cache_read"]
    ) / 1_000_000


async def record_usage(
    student_name: Optional[str],
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """
    Record one API call's token usage. Creates its own short-lived DB
    session so callers don't need to manage transaction boundaries —
    same self-contained convention as core/audit.py's log_event.
    Failures are caught and logged locally, never propagated: a usage-
    logging hiccup must not break a child's actual tutoring turn.

    student_name is None for the parent sandbox (no student context) —
    those calls still count toward the household total on
    GET /admin/status, just never appear on any specific student's card.
    """
    try:
        from core.database import AsyncSessionLocal, ApiUsageEvent

        async with AsyncSessionLocal() as db:
            db.add(ApiUsageEvent(
                student_name=student_name,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
            ))
            await db.commit()
    except Exception:
        log.warning("Usage event logging failed", exc_info=True)


async def get_usage_summary(db, student_name: Optional[str] = None) -> dict:
    """
    Aggregate token totals and a cost estimate, grouped by model, using
    the caller's own request-scoped session (routers/admin.py already has
    one injected via Depends(get_db) — same convention as this router's
    sibling read functions, list_profiles(db)/read_audit_log(db, ...)).
    student_name=None means household-wide — every recorded call across
    every student plus the parent sandbox. Never raises: a query failure
    degrades to an all-zero summary rather than breaking the dashboard
    that's asking for it.
    """
    try:
        from sqlalchemy import func, select

        from core.database import ApiUsageEvent

        query = select(
            ApiUsageEvent.model,
            func.sum(ApiUsageEvent.input_tokens),
            func.sum(ApiUsageEvent.output_tokens),
            func.sum(ApiUsageEvent.cache_creation_tokens),
            func.sum(ApiUsageEvent.cache_read_tokens),
            func.count(ApiUsageEvent.id),
        ).group_by(ApiUsageEvent.model)
        if student_name is not None:
            query = query.where(ApiUsageEvent.student_name == student_name)
        rows = (await db.execute(query)).all()
    except Exception:
        log.warning("Usage summary query failed", exc_info=True)
        rows = []

    by_model = []
    total_cost = 0.0
    total_input = total_output = total_calls = 0
    for model, input_tokens, output_tokens, cache_creation, cache_read, calls in rows:
        input_tokens = input_tokens or 0
        output_tokens = output_tokens or 0
        cache_creation = cache_creation or 0
        cache_read = cache_read or 0
        cost = estimate_cost_usd(model, input_tokens, output_tokens, cache_creation, cache_read)
        by_model.append({
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_tokens": cache_creation,
            "cache_read_tokens": cache_read,
            "calls": calls,
            "estimated_cost_usd": round(cost, 4),
        })
        total_cost += cost
        total_input += input_tokens
        total_output += output_tokens
        total_calls += calls

    return {
        "student_name": student_name,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_calls": total_calls,
        "estimated_cost_usd": round(total_cost, 4),
        "by_model": by_model,
    }


# A gap this short between two consecutive Anthropic calls for the same
# student, on the tutor model, is far more likely to be two rounds of ONE
# turn's tool_result loop (see services/ai_service.py's
# _MAX_TOOL_LOOP_ROUNDS) than the start of an unrelated new turn — a child
# reading, thinking, and typing/speaking a reply takes much longer than
# this in practice. There is no stored turn/round id anywhere in this
# schema (ApiUsageEvent is deliberately just an append-only per-call log —
# see its own docstring), so get_loop_stats below can only approximate
# "which rows belong to the same turn" by this timestamp-gap heuristic,
# not read it back exactly.
_TURN_GAP_SECONDS = 5.0


async def get_loop_stats(db, days: int = 30) -> dict:
    """
    Best-effort estimate of how often stream_tutor_response's bounded
    tool_result loop (services/ai_service.py's _MAX_TOOL_LOOP_ROUNDS)
    actually takes more than one model round-trip in practice, and the
    token cost / added latency attributable to those extra rounds — the
    analytics view behind GET /admin/agentic-loop-stats.

    Approximates which ApiUsageEvent rows belong to the same turn by
    clustering consecutive rows for the same student (ordered by
    created_at) whenever the gap between them is under _TURN_GAP_SECONDS.
    This can misattribute an unusually fast back-to-back pair of separate
    turns as one multi-round turn, or an unusually slow single generation
    as two — it's a trend view for deciding whether the loop is behaving
    as designed, not exact per-turn accounting. The admin UI surfaces this
    same caveat rather than presenting the numbers as precise.

    Scoped to settings.tutor_model rows with a non-null student_name,
    which isolates real child/parent tutoring turns — the only place this
    loop runs — from sandbox chat (student_name is None there),
    session summaries, and learner-profile synthesis (both on
    settings.session_model, a different model entirely — see
    core/config.py). Never raises: a query/computation failure degrades
    to an all-zero result, same convention as get_usage_summary above.
    """
    result = {
        "window_days": days,
        "turns_analyzed": 0,
        "multi_round_turns": 0,
        "multi_round_pct": 0.0,
        "avg_rounds_per_turn": 0.0,
        "max_rounds_seen": 0,
        "round_distribution": {},
        "avg_added_latency_seconds": 0.0,
        "max_added_latency_seconds": 0.0,
        "extra_round_estimated_cost_usd": 0.0,
    }
    try:
        from sqlalchemy import select

        from core.config import settings
        from core.database import ApiUsageEvent

        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = (
            select(ApiUsageEvent)
            .where(
                ApiUsageEvent.model == settings.tutor_model,
                ApiUsageEvent.student_name.is_not(None),
                ApiUsageEvent.created_at >= since,
            )
            .order_by(ApiUsageEvent.student_name, ApiUsageEvent.created_at)
        )
        rows = (await db.execute(query)).scalars().all()
    except Exception:
        log.warning("Loop-stats query failed", exc_info=True)
        return result

    # Bucket consecutive same-student rows into approximate "turns".
    turns: list[list] = []
    current: list = []
    prev_student = None
    prev_ts = None
    for row in rows:
        gap_ok = (
            prev_ts is not None
            and (row.created_at - prev_ts).total_seconds() <= _TURN_GAP_SECONDS
        )
        if current and row.student_name == prev_student and gap_ok:
            current.append(row)
        else:
            if current:
                turns.append(current)
            current = [row]
        prev_student = row.student_name
        prev_ts = row.created_at
    if current:
        turns.append(current)

    if not turns:
        return result

    round_counts = [len(t) for t in turns]
    multi_round = [t for t in turns if len(t) > 1]
    distribution: dict[int, int] = {}
    for n in round_counts:
        distribution[n] = distribution.get(n, 0) + 1

    latencies = [(t[-1].created_at - t[0].created_at).total_seconds() for t in multi_round]

    # "Extra" round cost: every round after a multi-round turn's first —
    # the first round would have happened regardless of this loop, the
    # rest are what the loop itself added.
    extra_cost = 0.0
    for t in multi_round:
        for row in t[1:]:
            extra_cost += estimate_cost_usd(
                row.model, row.input_tokens, row.output_tokens,
                row.cache_creation_tokens, row.cache_read_tokens,
            )

    result.update({
        "turns_analyzed": len(turns),
        "multi_round_turns": len(multi_round),
        "multi_round_pct": round(100 * len(multi_round) / len(turns), 1),
        "avg_rounds_per_turn": round(sum(round_counts) / len(turns), 2),
        "max_rounds_seen": max(round_counts),
        "round_distribution": distribution,
        "avg_added_latency_seconds": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "max_added_latency_seconds": round(max(latencies), 2) if latencies else 0.0,
        "extra_round_estimated_cost_usd": round(extra_cost, 4),
    })
    return result
