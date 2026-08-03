# Session-Scoped Diagnostic — Specification

*Status: **proposed**, not built. This is a design to accept, amend, or
reject. What ships today is the persistent path described in
[DIAGNOSTIC_ENGINE_DESIGN.md](DIAGNOSTIC_ENGINE_DESIGN.md); nothing in this
document is live.*

---

## 1. The position this encodes

Bede should be able to gauge mastery with real diagnostic rigour, and Agnus
Dei should not hold a retained psychometric assessment of anybody's child.

Those are only in tension if you treat "the diagnostic" as one thing. It is
two, and the codebase already separates them:

| | Holds | Example | Retention today |
|---|---|---|---|
| `MasteryProfile` / `DiagnosticEvidenceLog` | A **claim about the child** | "0.47 probability of having mastered multi-digit multiplication" | Indefinite |
| `SkillActivityLog` (work ledger) | An **event** | "on 3 Aug, a multi-digit multiplication task was completed unaided" | Indefinite |

That distinction is not invented here. `services/diagnostic/activity.py`
exists precisely because the second is safe to keep and the first is the
kind of record that follows a person. This spec follows the same line one
step further: **stop retaining the claim; keep the diagnostic.**

### 1.1 What "not stored by us at Agnus Dei" already means

Worth stating plainly, because it changes what this spec is actually for.

For a self-hosted family — the real product — the database is theirs, on
their hardware, encrypted at rest. `DATABASE_URL` points at their Postgres.
**Agnus Dei has no pipe to it on any path, including PIN entry.** Nothing in
this spec is needed to achieve that; it is already structurally true.

The one place Agnus Dei does briefly hold diagnostic data is the public
demo (`services/diagnostic_demo.py` → `DemoCodeSession`, its own table,
TTL-evicted, deleted on logout).

So this spec is not about Agnus Dei's servers. It is about whether a
retained psychometric claim about a child should exist **at all**, on
anyone's disk, including the family's own.

---

## 2. Efficacy — the constraint that shapes the design

The reason this is not simply "stop writing the table."

`mastery.CALIBRATION_THRESHOLD = 5` evidence points, below which a learner
is reported as still calibrating. The constant carries its own honest
caveat: *"a placeholder, not yet tuned against real sessions"*, against the
design doc's `[to verify final N]`.

Against that:

- `SUBJECT_DURATIONS[mathematics]` is **20 minutes**. A two-hour session is
  wall-clock and includes a mandatory ten-minute break per hour, so
  mathematics is one block of it, not the whole.
- Evidence is recorded only when a skill genuinely surfaces in dialogue
  (`record_skill_evidence` is silent and opportunistic, never a quiz).
- `_MAX_TOOL_CALLS_PER_TURN = 6` bounds a single turn.

**A single math block plausibly yields a handful of evidence points — the
same order of magnitude as the calibration threshold itself.** Which gives
the finding this spec has to design around:

> Discarding everything between sessions costs precisely the accumulation
> that makes the estimate meaningful. A purely session-scoped diagnostic
> would frequently report "still getting to know your learner" and never
> progress past it.

This is not an argument against the position in §1. It is the reason the
design below keeps *events* and discards *claims*, rather than discarding
both.

---

## 3. Design

### 3.1 What is retained, explicitly

| Store | Retained? | Why |
|---|---|---|
| `SkillActivityLog` (work ledger) | **Yes** | Events, not traits. Already the safe half. |
| `NarrationAssessment` | **Yes** — see §6 | Scores a work product, not the child. The guarantee depends on it. |
| `MasteryProfile` | **No** | The psychometric claim. This is the thing being retired. |
| `DiagnosticEvidenceLog` | **No** | Per-update deltas; the audit trail *of* the claim. |
| In-session vector | **No** | Lives in process memory for the session, then gone. |

### 3.2 Flow

1. A session starts. A `MasteryVector` is cold-started from grade band via
   `mastery.new_vector()` — no load, because there is nothing stored to load.
2. Evidence accumulates **in memory** across the whole session, hits *and*
   misses, for as long as the session runs. This is where the two-hour
   window does its work: everything the child does that afternoon informs
   one estimate.
3. At session end, `build_summary_view()` renders the snapshot into the
   parent's summary.
4. The vector is discarded. Nothing about the estimate reaches disk.
5. The work ledger continues writing events exactly as it does now.

### 3.3 Why this is small

The engine is already split correctly. `new_vector`, `apply_evidence` and
`build_summary_view` are **pure functions**; `process_evidence` is the thin
layer that wraps load/decrypt/apply/encrypt/store around them.

`services/diagnostic_demo.py` is the existing proof: it runs the real
engine, produces a real summary, and never touches `mastery_profiles`.

So the change is a third branch in a function that already branches twice:

```
_record_skill_evidence(db, demo_code, ...)
    demo_code is not None   -> demo backend            (exists)
    db is not None          -> persistent backend      (exists)
    ephemeral mode          -> in-session accumulator  (new)
```

### 3.4 Where the accumulator lives

**Constraint:** `services/streaming_transcription.py` is the precedent and
the warning. Its own docstring: *single-process, in-memory only — sessions
don't survive routing to a different instance under horizontal scaling.*

The same applies here, and it is acceptable for the same reason: a tutoring
session is already pinned to one process by its SSE stream. It must be
written down rather than discovered.

Requirements:

- Keyed by session, not by student name. A student key would outlive the
  session and quietly become the thing we are removing.
- A TTL sweep for abandoned sessions, mirroring
  `streaming_transcription.py`'s 180-second idle eviction.
- Hard-bounded in size, so a long session cannot grow memory without limit.

---

## 4. What changes for a parent

Stated bluntly, because this is the cost side.

- **The Progress page's mastery cards become a picture of today**, not of a
  term. `MasterySnapshot` currently reads a vector built over weeks.
- **"Math Skill Growth" becomes within-session.** It already computes
  session-start prior vs session-end posterior, so the mechanism survives —
  but the prior is now always a cold start rather than where the child
  actually was last week.
- **Cross-session trend disappears.** There is no honest way to show a
  six-week arc without retaining something that describes the child.
- **`next_steps` still works.** `kst.fringe()` operates on the current
  vector; a session-scoped vector still has a fringe.

---

## 5. What survives, and one thing that does not

**The learner's guarantee survives.** Term Mastery Outcomes reads
`NarrationAssessment.term_topic` / `term_topic_level` — narration rubric
scores, a *different store* from the diagnostic vector. Retiring
`MasteryProfile` does not break the guarantee.

**The mastery cycle survives**, for the same reason: `readCycle()` reads
narration assessments, not the vector.

**The work ledger survives** untouched, and becomes the primary durable
record of what a child has actually done.

**What does not survive: the composition, phonics, literacy and
language-exposure profiles.** They share `MasteryProfile` (by
`subject_area`) and would go session-scoped with it. A K–2 phonics picture
built over a term is arguably the most *useful* retained profile in the
product, and it is the one this costs most. Flagged as a real loss, not
waved past.

---

## 6. Open decisions

These need answers before implementation, and each changes the shape.

**D1 — Scope of the control.** Per-session ("don't keep this one"),
per-student ("never keep mastery for this child"), or deployment-wide
("this instance never retains an assessment")? These are three different
products. *Recommendation: deployment-wide flag first.* It matches the
existing `diagnostic_evidence_log_enabled` precedent, it is the one a
privacy posture actually needs, and per-student can be layered later.

**D2 — Is `NarrationAssessment` in scope?** It is retained and it *is* an
assessment. It scores a work product rather than claiming a trait, which
puts it on the safer side of the line — but if "no retained assessments" is
meant literally, it is in scope, and the guarantee genuinely depends on it.
*Recommendation: out of scope, and say why in the docs* — the distinction
being drawn is trait vs. work product, not the word "assessment."

**D3 — Migration for existing families.** Rows exist today. Does turning
this on delete them, orphan them, or leave them readable until the parent
deletes the student? *Recommendation: delete on enable, loudly and with
confirmation.* Leaving a retained assessment in place while the setting
claims none is retained is the worst of both.

**D4 — Does the demo change?** It is already ephemeral and TTL-evicted.
*Recommendation: no change.*

**D5 — Calibration honesty.** With a cold start every session, the
"calibrating" state will be common. Does the parent-facing copy say so
plainly? *Recommendation: yes, and it should explain the trade rather than
reading as a defect* — the summary should say the estimate covers today,
by design.

---

## 7. Testing requirements

Non-negotiable for a change of this kind. Every one is a "must refuse"
test, because the failure mode is silent persistence.

1. **Nothing reaches `mastery_profiles`.** Run a full session's worth of
   evidence in ephemeral mode against a real test DB and assert the table
   is empty afterwards. Not a mock — the actual table.
2. **Nothing reaches `diagnostic_evidence_log`.** Same shape.
3. **The work ledger is unaffected.** Events still written, same counts.
4. **Two sessions do not see each other.** Session B cold-starts; no key
   collision, no leakage via a shared student name.
5. **Accumulation actually works within a session.** Evidence at minute 5
   and minute 95 lands in the same vector, and the summary reflects both —
   this is the efficacy claim, and it needs a test.
6. **Abandoned sessions are evicted**, and eviction frees the vector.
7. **The flag genuinely toggles**, with the persistent path unchanged when
   off — byte-for-byte the same behaviour as today.

---

## 8. What this does not solve

The estimate is only as good as one session's evidence, and §2 shows that
is close to the calibration floor. **This buys a privacy position at a real
cost in statistical power, and the honest framing is a trade, not a free
win.**

If the diagnostic needs to be genuinely strong, the alternative worth
considering is a *retained event log with on-demand computation*: keep
factual events including misses, compute the vector when asked, store no
claim. That preserves accumulation across sessions with nothing on disk
that describes the child.

The blocker is that the work ledger deliberately **does not record
`incorrect`** — *"a missed attempt isn't completed work"* — and a
psychometric estimate needs the misses. Reversing that would make the
ledger a record of failures, which is the thing it was explicitly built not
to be.

That tension is unresolved and is the most interesting open question in
this area.
