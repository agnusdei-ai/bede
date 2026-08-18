# Finding Out Where a Child Is, Without Testing Them

**Principled probing: a specification.**

> **Status: proposed, not built.** Nothing described here exists yet. Four
> decisions are settled (§0); the open ones are listed in §10 and are the
> reason this is a document rather than a branch.

---

## Summary

Bede's mastery estimate is built from evidence gathered **opportunistically** —
`record_skill_evidence` fires when a Socratic exchange happens to reveal
something. That is unpredictable and slow. A family's first weeks therefore
look thin: the card says *still getting to know your learner* while the
parent, reasonably, wonders what they bought.

The fix is to gather evidence **on purpose** at the start. The risk is that
gathering evidence on purpose is what a test is, and the families Bede is
built for are frequently the ones who left institutional schooling because
of testing.

This document specifies a middle path: probing governed by principles, held
inside a boundary of what counts as invasive, that a child experiences as a
lesson and a parent chooses freely.

---

## 0. Decisions already made

| | Decision | |
|---|---|---|
| **D1** | **Scope: mathematics + reading/literacy.** | Maths has the full prerequisite graph; reading has the developmental sequence. Composition needs a written narration to assess at all, which turns a conversation into a battery — excluded. |
| **D2** | **Shape: woven into the first two or three ordinary lessons.** | No session is ever "the assessment". Bede probes more densely than usual while teaching throughout. Slower to converge than a dedicated sitting, and that is the price of not having a test-shaped event in the product. |
| **D3** | **Parent output: a narrative in the session summary; results seed the normal cards silently.** | No scorecard on day one. **Conditional on D3a.** |
| **D3a** | **The Progress page must be unified first.** | ~~It currently renders five separate `MasterySnapshot` cards plus seven more panels.~~ **Done** — `MasteryOverview.tsx` replaced them with one card, a row per area. See §10.1. |
| **D4** | **Ceiling: one subject block, 20 minutes.** | Matches `SUBJECT_DURATIONS[Subject.mathematics]`, so it fits the day the parent already planned and needs no special scheduling. |

---

## 1. Why this is not a computerized adaptive test

The distinction is not stylistic, and it is worth stating precisely because
"adaptive assessment" is the obvious name for what this looks like.

**A CAT selects the next item to maximise information about a latent trait.**
Formally it picks the item whose difficulty sits nearest the current ability
estimate, because that is where Fisher information peaks. In plain terms:
**a CAT deliberately asks questions the examinee has about a 50% chance of
answering.** That is optimal measurement, and it means roughly half of what
a child is asked is engineered to be failed.

That is the invasiveness. Not the data collection — the deliberate
manufacture of failure as an efficiency strategy.

**Principled probing selects the next question from the fringe** — skills
whose prerequisites are solid enough to build on but which are not yet
secure (`kst.fringe`, already built). That is a *pedagogical* criterion, not
an information-theoretic one. It happens to be informative, but what it
actually names is **what this child is ready to learn next**, which is the
same thing a good tutor picks anyway.

| | CAT | Principled probing |
|---|---|---|
| Next item chosen to | maximise information | be the next teachable thing |
| Target success rate | ~50% by design | as high as the child can genuinely manage |
| Stops when | standard error hits a target | any of §5's rules fire, including the child having had enough |
| The child's experience is | instrumental | the binding constraint |
| Optimises | measurement efficiency | a lesson that happens to inform |

A CAT will keep going while a child is drowning, because a wrong answer is
still information. That single behaviour is the whole reason this is
specified separately.

---

## 2. What "invasive" means here

The governing constraint. Probing is invasive when any of these is true:

1. **The child can tell it is happening.** If a child experiences a session
   as being tested, the design has failed regardless of what it produced.
2. **It continues past the child's willingness.** Information is not a
   sufficient reason to continue.
3. **It manufactures failure to learn faster.** See §1.
4. **It goes outside what the parent scheduled.** Placement probes the
   subjects on that student's plan, not a curriculum Bede thinks they
   should be doing.
5. **It produces a record the family did not agree to.** Placement writes
   to the same `MasteryProfile` a normal session does. It creates no new
   category of record, and no new retention question.

Everything in §3–§6 exists to keep all five false.

---

## 3. What the parent chooses

At setup, after subjects are picked, one card — not a settings checkbox:

> **Would you like Bede to spend the first few lessons finding out where
> Wren already is?**
> She won't sit through things she can already do, and you'll see a real
> picture in about a week instead of a month.
>
> **[Yes, start there]**  **[No, just begin teaching]**

Both choices are one tap. Neither is preselected. The word "test",
"assessment", "diagnostic", and "placement" appear nowhere in what a parent
or child sees — they are the vocabulary of the institution these families
left, and using them would cost more in refusals than the feature is worth.

**Re-offerable, not once.** The same card appears for a family joining
mid-year, for a child returning after a long break, and for a parent who
declined and reconsidered. A return after three weeks away is a short
placement pass scoped to what the bookmark says they were doing — the same
mechanism, a different trigger (see §7).

---

## 4. How a probe is chosen

**Mathematics** — walk `kst.fringe(vector)`, which already returns exactly
the right set: skills whose full prerequisite closure clears `prereq_hi`
(0.65) but which are not themselves secure. Among those, prefer:

1. skills the parent's `current_unit`/`lesson_focus` points at, so the
   probing is also the lesson;
2. then the least-secure, so the picture fills where it is thinnest;
3. never a skill two bands below the child's own unless one above it has
   already been missed — a prerequisite failure is the only honest reason
   to go backwards.

**Reading/literacy** — `literacy.DOMAINS` and `phonics.DOMAINS` are
developmental sequences, not graphs, so `next_steps` already walks them in
order rather than by probability. Placement walks the same order and stops
descending once two consecutive domains are answered securely.

**In both cases the probe is a question inside a lesson**, drawn from the
existing probe archetypes, asked Socratically. There is no separate item
bank and no separate delivery mode.

---

## 5. Stopping rules

Placement ends when **any** of these fires. They are deliberately not
ranked, because each of them is sufficient on its own.

| Rule | Fires when |
|---|---|
| **The child has had enough** | three consecutive misses in one strand, a visible drop in answer length, or the child saying anything that reads as done. |
| **The block is over** | 20 minutes in this subject (D4). |
| **The picture is good enough** | the fringe has narrowed below a threshold, or evidence count has passed `CALIBRATION_THRESHOLD` for the area. |
| **The parent ends it** | at any point, from the session view. |
| **It has run its course** | two or three sessions in, whatever it has is what it gets. |

**The distress rule is the important one, and it is also the statistically
correct one.** A demoralised child guesses, and guessing is what inflates
false-secure — the error that sends a family past a gap, and the one
`new_vector`'s prior fix just cut from 13.1% to 1.9% at band 6-8. Being kind
and being accurate point the same direction. Bede stops probing and simply
teaches for the rest of the block.

**Whatever it gathers, it keeps.** A pass abandoned after eight minutes
leaves eight minutes of real evidence and Bede is better off than before.
There is nothing to complete and nothing to fail.

---

## 6. What the child experiences

A lesson. That is the whole specification.

Bede teaches Socratically as it always does. The questions skew toward the
fringe rather than toward wherever the conversation drifted, and there are
somewhat more of them. Bede does not announce it, does not explain it, and
does not refer to it afterwards — the same rule `_WORK_SCORING_NOTE`
already applies to scoring and `_learning_support_note` applies to
accommodations.

Correct answers are celebrated as they always are. A missed question is
followed by the same Socratic scaffolding as any other missed question,
not by "let's try an easier one," which is the tell.

---

## 7. Interaction with what already exists

- **`LessonBookmark`** — a placement pass writes bookmarks as any session
  does. A return-from-break pass reads the bookmark first and scopes itself
  to that subject rather than starting from the whole map.
- **`travel_mode`** — no interaction. Placement is about the start of a
  relationship; travel mode is about a window on evidence already gathered.
- **`learning_support`** — fully respected. A child who answers aloud is
  probed aloud. Accommodations are not suspended for assessment, which is
  precisely the mistake schools make.
- **`RETAIN_MASTERY_PROFILES=false`** — placement still runs, and its
  results live in the session-scoped estimate like everything else. The
  value is smaller (the picture dies with the session) but not zero: it
  makes that single session's teaching better calibrated.
- **The demo** — out of scope. A fifteen-minute preview has no room for it,
  and `diagnostic_demo.py` is a single-session store by design.

---

## 8. What this deliberately does not do

- **No score, no percentile, no grade-equivalent.** Placement produces the
  same `MasteryProfile` a normal session does. It does not produce a
  number describing the child.
- **No recommendation to move a child up or down a grade.** That is the
  parent's decision, and Bede has neither the standing nor the evidence.
- **No comparison to other children**, including siblings in the same pod.
- **No aptitude claim.** Placement measures what a child has mastered. What
  they are capable of is not a question this software asks.

---

## 9. Why this is worth building

Two reasons, and the second is the one that pays for it.

**It fixes the trial problem honestly.** A family evaluating Bede for a
month currently sees a thin picture, because opportunistic evidence
accumulates slower than their patience. The alternative fixes — lowering
the calibration threshold, or showing an under-evidenced estimate — both
amount to claiming more than is known. Gathering more evidence is the only
honest way to know more.

**It stops wasting the child's time**, which is what a homeschool parent
actually values. Their time is the scarce resource, and re-teaching
material a child already has is the specific thing they resent. A Bede that
knows where a child is on day three teaches better for the whole term.

---

## 10. Open questions

### 10.1 — ~~Blocking: the unified Progress view (D3a)~~ RESOLVED

`Progress.tsx` used to render **five separate `MasterySnapshot` cards**
(mathematics, composition, phonics, language exposure, literacy), each with
its own heading, evidence count, amber calibration banner and set of bars.
A parent scrolled through five near-identical panels to assemble, in their
head, the one picture the page should have shown them.

`MasteryOverview.tsx` is that picture: one card, one row per area, each row
stating where it stands in a line and opening to the detail the whole card
used to be. D3's "seed the normal cards" is now a coherent sentence.

Three properties it carries, pinned by test: **no overall score** across
areas (averaging maths against language exposure would invent a quantity
that does not exist), **no ordering by how well the child is doing** (a list
that reshuffles as a child improves is a ranking of their own subjects), and
an area still **says plainly when it is not calibrated** rather than showing
a confident-looking bar built from four observations.

### 10.2 — How dense is "denser"?

D2 says Bede probes more than usual during placement. How much more? Every
turn is a test in all but name. One in five is barely different from today.
This wants measuring against the simulator rather than choosing: what
probe density reaches `CALIBRATION_THRESHOLD` inside D4's 20-minute block
without the session reading as an interrogation?

### 10.3 — What ends placement mode for good?

§5 says "two or three sessions." Which, and decided by what? A fixed count
is predictable and arbitrary. A convergence criterion is principled and
unpredictable to a parent. A third option: it never formally ends, and the
density simply decays to normal.

### 10.4 — Does a child ever get told?

§6 says no. But a 7th grader who notices they are being asked a lot of
questions and asks Bede directly deserves a true answer. What is it?

### 10.5 — Placement for a child who has been with Bede for a year?

The re-offer in §3 covers a returning child. It does not cover a family who
declines at setup, uses Bede for a year, and then wants a picture. Running
placement against an already-evidenced vector is a different problem —
existing evidence should not be overwritten, but a year-old estimate is
also not current.

---

## Related

| | |
|---|---|
| How the engine works | [DIAGNOSTIC_ENGINE_DESIGN.md](DIAGNOSTIC_ENGINE_DESIGN.md) |
| What is kept afterwards | [EPHEMERAL_DIAGNOSTIC_SPEC.md](EPHEMERAL_DIAGNOSTIC_SPEC.md) |
| What mastery means here | [../MASTERY.md](../MASTERY.md) |
| Why Bede asks instead of telling | [../SOCRATIC_METHOD.md](../SOCRATIC_METHOD.md) |
