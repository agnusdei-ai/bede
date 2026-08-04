"""
Unit 5.1 — the end-to-end real math session the simulator cannot stand in for.

WHAT THIS ANSWERS THAT tests/diagnostic/test_convergence.py CANNOT.

5.2 measured the ESTIMATOR: given N evidence points, how accurate is the
vector? It had to assume a value for N. This script measures the thing that
assumption rests on — whether a real Claude-driven tutoring block actually
produces evidence at all, and at what rate. If a 20-minute math block yields
one evidence point rather than four, the tuning still holds but the coverage
story a parent is told changes completely.

It also checks the three invariants Phase 3 claimed and nothing has re-verified
against a live model since: evidence flows, the vector moves, and the child
sees nothing.

COSTS REAL MONEY. Each turn is a real Sonnet call with the full cached system
prompt. A default run is a handful of turns — cents, not dollars — but it is
not free and it is not part of the test suite, exactly like
scripts/adversarial_probe.py.

USAGE
    export ANTHROPIC_API_KEY=...          # never paste this into a transcript
    export DATABASE_URL=postgresql+asyncpg://postgres@/bede_e2e?host=/tmp&port=5433
    python scripts/phase5_live_session.py

NOTE ON WHAT "REAL" MEANS HERE. The child's answers are scripted — written to
be the kind of thing a real 4th grader says, including a wrong one and a
hesitant one, because an all-correct run would repeat Phase 1's own blind
spot. What is real is Bede: the prompt, the model, the tool definitions, and
its own unprompted decision whether to record evidence. That decision is the
measurement.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A realistic 4th-grade multiplication block. Deliberately mixed: a confident
# answer, a wrong one, a hesitant one, and a real-world application — the
# spread a diagnostic needs in order to have anything to distinguish.
CHILD_TURNS = [
    "[START]",
    "I think 7 times 8 is 56.",
    "Um... 6 times 9 is 52? I'm not sure.",
    "Oh wait, I counted wrong. It's 54 because 6 times 10 is 60 and you take away 6.",
    "If there are 4 rows of 12 chairs that's 48 chairs, because 4 times 10 is 40 and 4 times 2 is 8.",
    "I don't really get long division yet.",
]

STUDENT = "Phase5TestStudent"


async def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set — this script needs a live model.")
        return 2
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL is not set — this script needs a live database.")
        return 2

    from core.database import AsyncSessionLocal, create_tables
    from models.schemas import ChatMessage, GradeStage, SessionConfig, Subject
    from services import ai_service
    from services.diagnostic import get_mastery_summary

    await create_tables()
    session_factory = AsyncSessionLocal

    config = SessionConfig(
        student_name=STUDENT,
        grade="4",
        grade_stage=GradeStage.core_mastery,
        subjects=[Subject.mathematics],
        current_unit="multiplication facts and multi-digit multiplication",
    )

    # Count what Bede actually chooses to record, without changing what it
    # does. Wraps `_record_skill_evidence` itself rather than a generic
    # dispatcher: that is the exact call whose rate 5.2 had to assume, and
    # wrapping it means the count cannot drift if the dispatcher is renamed
    # (which it already has been once since the design doc was written).
    evidence_payloads: list[dict] = []
    real_record = ai_service._record_skill_evidence

    async def counting_record(db_, demo_code_, config_, subject_, tool_input, *a, **k):
        evidence_payloads.append(dict(tool_input) if isinstance(tool_input, dict) else {})
        return await real_record(db_, demo_code_, config_, subject_, tool_input, *a, **k)

    ai_service._record_skill_evidence = counting_record

    history: list[ChatMessage] = []
    leaked: list[str] = []
    DIAGNOSTIC_WORDS = ("mastery", "probe", "posterior", "skill_id",
                        "diagnostic", "record_skill_evidence", "secure",
                        "evidence")

    async with session_factory() as db:
        before = await get_mastery_summary(db, STUDENT, "mathematics")
        print(f"BEFORE: {'no profile yet' if not before else json.dumps(before)[:160]}\n")

        for turn_index, child_message in enumerate(CHILD_TURNS):
            reply_text = []
            async for chunk in ai_service.stream_tutor_response(
                config=config, subject=Subject.mathematics, history=history,
                child_message=child_message, db=db, role="child",
                session_id="phase5-live", ip="127.0.0.1", user_agent="phase5",
            ):
                if not chunk.startswith("data: "):
                    continue
                try:
                    payload = json.loads(chunk[6:])
                except json.JSONDecodeError:
                    continue
                if payload.get("type") == "text":
                    reply_text.append(payload.get("content", ""))
                # INVARIANT: nothing diagnostic may reach the child's stream.
                blob = json.dumps(payload).lower()
                for word in DIAGNOSTIC_WORDS:
                    if word in blob:
                        leaked.append(f"turn {turn_index}: {word} in {blob[:120]}")

            reply = "".join(reply_text)
            shown = child_message if child_message != "[START]" else "(opener)"
            print(f"--- turn {turn_index}  child: {shown}")
            print(f"    bede : {reply[:180]}{'…' if len(reply) > 180 else ''}")
            if child_message != "[START]":
                history.append(ChatMessage(role="user", content=child_message))
            history.append(ChatMessage(role="assistant", content=reply))

        after = await get_mastery_summary(db, STUDENT, "mathematics")

    evidence_calls = evidence_payloads
    print("\n" + "=" * 78)
    print("UNIT 5.1 RESULT")
    print("=" * 78)
    print(f"  turns run ....................... {len(CHILD_TURNS)}")
    print(f"  record_skill_evidence calls ..... {len(evidence_calls)}")
    for payload in evidence_payloads:
        print(f"      recorded: {payload}")
    print(f"  child-stream leaks .............. {len(leaked)}")
    for entry in leaked:
        print(f"      LEAK: {entry}")
    print(f"  vector moved .................... {before != after}")
    if after:
        print(f"  evidence_count after ............ {after.get('evidence_count')}")
    print()
    print("  THE NUMBER 5.2 WAS ASSUMING: evidence points per block.")
    print(f"  This run produced {len(evidence_calls)} over {len(CHILD_TURNS)} turns.")
    print("  test_one_sitting_decides_only_a_fraction_of_the_map assumes ~4.")

    ok = not leaked and len(evidence_calls) > 0
    print(f"\n  GATE: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
