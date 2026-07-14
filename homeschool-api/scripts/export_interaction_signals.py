"""
Periodic, human-reviewed export of aggregated demo interaction-pattern
signals — see services/interaction_signals.py for what's actually
recorded (structural signals only: tool-usage counts, turn counts,
subject completions, never conversation content) and why.

Deliberately NOT an API endpoint and NOT a live dashboard — per the
explicit decision behind this feature, someone runs this by hand,
reads the report, and decides for themselves whether anything in it
suggests a prompt change worth making. Nothing here is automated.

Usage (from homeschool-api/, with the same environment as the app itself):

    python -m scripts.export_interaction_signals

Also purges rows older than services.interaction_signals._RETENTION_DAYS,
since this is the one place that runs periodically rather than on the hot
tutoring path.
"""

import asyncio
import statistics
from collections import Counter


async def _load_all_signals() -> list[dict]:
    from sqlalchemy import select

    from core.database import AsyncSessionLocal, DemoInteractionSignal
    from core.encryption import decrypt_json

    signals = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(DemoInteractionSignal))).scalars().all()
        for row in rows:
            try:
                signals.append(decrypt_json(row.signals_enc))
            except Exception:
                # A corrupted row is skipped for reporting purposes — same
                # degrade-don't-crash convention as the rest of this
                # subsystem; one bad row shouldn't block the whole report.
                continue
    return signals


def _build_report(signals: list[dict]) -> str:
    if not signals:
        return "No demo interaction signals recorded yet — nothing to report."

    lines = [
        f"# Demo interaction-pattern report — {len(signals)} session(s)",
        "",
        "Structural signals only (which tools fired, turn counts, subject",
        "completions) — no conversation content is or was ever available here.",
        "",
    ]

    turn_counts = [s.get("turn_count", 0) for s in signals]
    lines.append("## Session length (turns)")
    lines.append(f"- mean: {statistics.mean(turn_counts):.1f}")
    lines.append(f"- median: {statistics.median(turn_counts):.1f}")
    lines.append(f"- min/max: {min(turn_counts)} / {max(turn_counts)}")
    lines.append("")

    tool_totals: Counter = Counter()
    for s in signals:
        tool_totals.update(s.get("tool_counts", {}))
    lines.append("## Tool usage, total across all sessions")
    for tool, count in tool_totals.most_common():
        lines.append(f"- {tool}: {count}")
    lines.append("")

    completed_counts = [len(s.get("subjects_completed", [])) for s in signals]
    visited_counts = [len(s.get("subjects_visited", [])) for s in signals]
    lines.append("## Subject completion")
    lines.append(f"- avg subjects visited per session: {statistics.mean(visited_counts):.1f}")
    lines.append(f"- avg subjects completed per session: {statistics.mean(completed_counts):.1f}")
    lines.append("")

    silence_sessions = sum(1 for s in signals if s.get("silence_continues_fired", 0) > 0)
    lines.append("## Silence handling")
    lines.append(
        f"- sessions where Bede picked the thread back up after silence: "
        f"{silence_sessions}/{len(signals)}"
    )
    lines.append("")

    # A simple, human-inspectable correlation: does using offer_socratic_hint
    # associate with completing more subjects in the same session? Reported
    # as two group means, not a formal statistical test — this is meant to
    # prompt a human's own judgment, not to auto-decide anything.
    hinted = [len(s.get("subjects_completed", [])) for s in signals if s.get("tool_counts", {}).get("offer_socratic_hint")]
    unhinted = [len(s.get("subjects_completed", [])) for s in signals if not s.get("tool_counts", {}).get("offer_socratic_hint")]
    lines.append("## Hint usage vs. subject completion (descriptive only, not a statistical claim)")
    if hinted:
        lines.append(f"- sessions using offer_socratic_hint ({len(hinted)}): avg {statistics.mean(hinted):.1f} subjects completed")
    if unhinted:
        lines.append(f"- sessions not using it ({len(unhinted)}): avg {statistics.mean(unhinted):.1f} subjects completed")

    return "\n".join(lines)


async def main() -> None:
    from services.interaction_signals import purge_old_signals

    signals = await _load_all_signals()
    print(_build_report(signals))

    purged = await purge_old_signals()
    if purged:
        print(f"\n(purged {purged} row(s) past retention)")


if __name__ == "__main__":
    asyncio.run(main())
