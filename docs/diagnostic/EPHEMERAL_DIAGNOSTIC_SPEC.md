# Measuring Mastery Without Keeping a File on a Child

**A proposal for how Bede assesses learning, and what it should keep afterward.**

> **Status: proposed.** Nothing described here is built. What Bede does
> today is the persistent approach described in
> [DIAGNOSTIC_ENGINE_DESIGN.md](DIAGNOSTIC_ENGINE_DESIGN.md). This document
> exists to be accepted, amended, or rejected.

---

## Summary

Bede can assess a child's mastery with genuine rigour. The question this
document settles is what it should keep once it has.

Today Bede keeps two different kinds of record. One is a **statement about
your child**: an estimate that they have, say, a 47% probability of having
mastered multi-digit multiplication. The other is a **record of what
happened**: that on the third of August, a multi-digit multiplication task
was completed without help.

The second is ordinary. It is the kind of note any tutor keeps. The first
is a psychological profile, and it is the kind of record that follows a
person.

**The proposal is to stop keeping the first and continue keeping the
second.** Bede would still run the full assessment, still report what it
found, and then let the estimate go when the session ends.

There is a real cost, and Section 5 states it plainly rather than leaving
it to be discovered later.

---

## 1. Where a family's data actually lives

Worth establishing first, because it is often the real concern behind the
question.

Bede runs on your own computer. The database is yours, on your hardware,
encrypted, in your house. **Agnus Dei has no connection to it and never
receives your child's assessments.** That is already true today, on every
sign-in path including a child's PIN. Nothing in this proposal is needed to
achieve it.

The one exception is the public demo on our website, which necessarily runs
on our servers. There, a visitor's practice session is held briefly and
deleted when the code expires or they log out.

So this document is not about what Agnus Dei can see. It is about a
narrower and more interesting question: **whether a lasting psychological
estimate of a child should exist at all, on anyone's computer, including
your own.**

---

## 2. What Bede keeps today

| What is stored | What it actually says | Kept for |
|---|---|---|
| Mastery profile | "This child probably has or has not mastered X" | Indefinitely |
| Evidence log | The reasoning behind each change to that estimate | Indefinitely |
| Work ledger | "This task was completed on this date, unaided" | Indefinitely |
| Narration assessments | Scores for a specific piece of work the child produced | Indefinitely |

The distinction between the first two rows and the last two is not new. The
work ledger was built precisely because a record of *what a child did* is
safe to keep, while a judgment about *what a child is* is not. This
proposal follows that same reasoning one step further.

---

## 3. The proposal

Bede would assess exactly as it does now, with one change: the estimate
lives only for the length of the session.

1. A session begins. Bede starts from what is typical for the child's grade,
   because there is no stored profile to load.
2. Throughout the session, everything the child demonstrates feeds the
   estimate. A two-hour morning informs one assessment.
3. At the end, the parent's summary reports what Bede observed.
4. The estimate is discarded.
5. The record of work completed continues exactly as before.

---

## 4. What a family would notice

**Unchanged.** The lesson itself, the questions Bede asks, the session
summary, the record of work completed, the learner's guarantee, and the
mastery cycle that reports movement over four weeks.

**Changed.** The mastery cards on the Progress page would describe the most
recent session rather than the term. The "Math Skill Growth" note would
show movement within a morning rather than across weeks. Long-run trends
would no longer be available, because showing a six-week arc requires
keeping a six-week record of the child.

---

## 5. What it costs

This is the part that decides whether the proposal is worth adopting.

A mastery estimate becomes reliable through accumulation. Bede treats a
learner as "still calibrating" below a threshold of five pieces of
evidence, and that threshold is marked in our own code as provisional and
not yet tuned against real families.

Set against that: mathematics is a twenty-minute block of the day, and
Bede gathers evidence only when a skill genuinely comes up in conversation.
It never quizzes for it. **A single session therefore produces evidence in
roughly the same range as the calibration threshold itself.**

The consequence is direct. Discarding the estimate between sessions removes
the accumulation that makes it meaningful, and a family may often see "still
getting to know your learner" rather than a confident picture.

**This proposal buys a privacy position with statistical power.** It is a
genuine trade, not a free improvement, and it should be adopted with that
understood.

---

## 6. What this would cost elsewhere

The mastery profile is shared by more than mathematics. Composition,
phonics, reading and spelling, and language exposure all use it.

The most significant loss is **phonics**. A picture of a young child's
decoding built steadily across a term is arguably the most useful record
Bede produces for a family in the early years, and it is exactly the kind
that depends on accumulation. It would become a snapshot.

---

## 7. Decisions still open

| | Question | Recommendation |
|---|---|---|
| **D1** | Is this a whole-installation setting, a per-child setting, or a per-session choice? | **Whole installation.** A privacy position should be a property of the software a family installed, not a checkbox to remember. Per-child can follow later. |
| **D2** | Do narration assessments fall under this too? | **No, and the reason should be published.** They score a piece of work, not the child. That is the distinction being drawn, rather than the word "assessment." |
| **D3** | What happens to profiles that already exist? | **Delete them when the setting is turned on**, with clear confirmation. Leaving records in place while the software claims none are kept is the worst outcome available. |
| **D4** | Does the public demo change? | **No.** It is already temporary. |
| **D5** | How is "still calibrating" explained? | **Plainly, as a design choice.** The summary should say the estimate covers today by design, so it reads as intended behaviour rather than a fault. |

---

## 8. The question this leaves unresolved

There is a third option, and it is better than either of the two above if
it can be made to work.

Keep a factual record of what happened, including the attempts that did not
succeed, and calculate the estimate only when someone asks for it. Nothing
describing the child would ever be stored, and accumulation across sessions
would be preserved. The best of both.

The obstacle is real. The work ledger deliberately does **not** record
unsuccessful attempts, on the grounds that a missed attempt is not
completed work and that the ledger should not become a record of a child's
failures. A statistical estimate needs those attempts; they carry much of
the information.

So the third option trades one privacy protection for another, and that is
a decision about what kind of record a family should live with rather than
a technical problem to solve. It is the most interesting open question in
this area and it is not settled here.

---

## Appendix A. Implementation notes

*For the engineering team. Everything above is readable without this.*

**The engine is already split correctly.** `mastery.new_vector`,
`mastery.apply_evidence`, and `mastery.build_summary_view` are pure
functions; `services.diagnostic.process_evidence` is the thin layer adding
load, decrypt, apply, encrypt, and store around them.
`services/diagnostic_demo.py` already proves the engine runs and renders a
real summary without touching `mastery_profiles`.

**The change is a third branch** in `_record_skill_evidence`
(`services/ai_service.py`), which already branches twice:

| Condition | Backend | Status |
|---|---|---|
| `demo_code is not None` | Demo single-session store | Exists |
| `db is not None` | `process_evidence` → `mastery_profiles` | Exists |
| Ephemeral mode | In-session accumulator | **New** |

**Accumulator constraints.** `services/streaming_transcription.py` is both
the precedent and the warning: single-process, in-memory, does not survive
routing to another instance under horizontal scaling. Acceptable here for
the same reason (a tutoring session is pinned to one process by its SSE
stream), but it must be documented rather than discovered.

- Key by session, never by `student_name`. A student key outlives the
  session and quietly recreates what is being removed.
- TTL sweep for abandoned sessions, mirroring the 180-second idle eviction
  in `streaming_transcription.py`.
- Bounded in size, so a long session cannot grow memory without limit.

**Numbers behind Section 5.** `mastery.CALIBRATION_THRESHOLD = 5`, carrying
its own `"placeholder, not yet tuned against real sessions"` comment
against the design document's `[to verify final N]`.
`SUBJECT_DURATIONS[Subject.mathematics] = 20` minutes.
`_MAX_TOOL_CALLS_PER_TURN = 6` bounds a single turn.

**Confirmed unaffected.** Term Mastery Outcomes and the mastery cycle both
read `NarrationAssessment.term_topic_level`, a different store from the
vector. `kst.fringe()` operates on the current vector, so `next_steps`
continues to work session-scoped.

---

## Appendix B. Test requirements

Every test below asserts a **refusal**, because the failure mode is silent
persistence rather than a visible error.

| # | Must prove |
|---|---|
| 1 | A full session of evidence leaves `mastery_profiles` empty. Real table, not a mock. |
| 2 | The same for `diagnostic_evidence_log`. |
| 3 | The work ledger is unaffected: same events, same counts. |
| 4 | Two sessions cannot see each other. Session B cold-starts, with no leakage through a shared student name. |
| 5 | Accumulation works *within* a session: evidence at minute 5 and minute 95 reach the same estimate. This is the efficacy claim and needs a test of its own. |
| 6 | Abandoned sessions are evicted, and eviction frees the estimate. |
| 7 | With the setting off, the persistent path behaves exactly as it does today. |
