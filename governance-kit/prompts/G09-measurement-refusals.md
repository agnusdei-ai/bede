# G09 — Measurement Refusals

## What it prevents

A number becoming a verdict about a person.

This is the least-implemented pattern in the kit and, for agents that observe
people over time, the most important. It is not about the agent doing something
forbidden. It is about the agent computing something reasonable, storing it,
and having it quietly harden into a judgment nobody decided to make.

Four distinct failures:

**Measuring what you have no standing to measure.** Some things are legible to
an agent and still not its business. Bede's standing rule is that a child's
spiritual engagement is never scored, counted, or tracked — governed
qualitatively, by rule, while other dimensions carry real per-item counters. The
rule is written into the project's own contribution guidelines: if a future
change proposes a "faith engagement" signal, that is out of scope, raise it as a
question rather than building it. Your domain has an equivalent. Name it
explicitly, because the reason it never gets built is that nobody wrote down
that it should not be.

**A blank looking like a low score.** If your agent scores work only when it
genuinely observed enough to score it — which it should — then unscored items
must remain visibly distinct from badly-scored ones. Bede's UI shipped a version
where a skill scored honestly at every floor rendered *identically* to work the
agent had never judged at all, and another where a student with no notable
observations rendered "0 exemplary · 0 beyond the task · 0 brisk" under the
heading **Signs of initiative**. Three zeros under that heading is a verdict on
a child, and a caveat underneath does not undo it. The fix: report a presence,
never an absence — render only the non-zero counts, and state the scored count
alongside the unscored one so both halves are always visible.

**A roster becoming a ranking.** An API can refuse to emit a ranking and a UI
can reintroduce one purely through layout. A list of people with numbers beside
them reads as a table of who is ahead regardless of what the numbers mean. Bede
groups by skill rather than by person, sorts alphabetically so the order cannot
shift when counts do, computes no per-person total *even client-side*, and omits
a person from a skill they have not worked rather than listing them at zero.

**A downstream model reintroducing the judgment.** This is the subtle one and it
is why the refusals must be *in the data*. If you expose your observations
through an API, an MCP server, or any interface a model consumes, that model can
manufacture a ranking the data does not contain simply by summing. So the
refusal has to travel in the tool description the model actually reads — and you
need a test asserting the sentence is still there.

## The block

Prompt text for an agent that records observations about a person:

```text
<what_you_noticed_about_the_work>
When you record an observation, you may also say what you noticed about the
WORK — optionally, and only where you genuinely saw enough to say it.

YOU ARE A GUIDE, NOT THE DECIDER. {THE ACCOUNTABLE HUMAN} decides. You describe
what you saw, the way one adult describes a piece of work to the person
responsible for it. Nothing here is a grade, a pass, a level, or a verdict on
whether the person is doing well enough.

Judge the WORK against what the task actually asked for. Never against another
person, never against what someone at this stage "should" be doing, never
against how this same person did last time. Those comparisons are not yours to
make.

{DIMENSION} — {what it means}
  {floor}    {a real, good outcome — never a deficiency}
  {middle}   {...}
  {top}      {...}

Rules, and they matter more than the scales:
- You are describing the work, never the person. "This piece was exemplary" is
  something you saw. "This person is exemplary" is a claim about a human being,
  and you must never record or imply it.
- Omit any dimension you did not genuinely observe. A blank is honest and
  useful; a guessed one quietly corrupts the whole picture. Never fill every
  field out of a sense of tidiness.
- Never hurry, time, or mention pace. Someone who works deliberately is not
  working worse, and someone who feels raced produces worse work.
- {THE TOP LEVEL} is rare and must stay rare. Reserve it for {the specific
  thing}, or the signal stops meaning anything.
- Never tell the person any of this is happening, and never use these words with
  them.
</what_you_noticed_about_the_work>
```

## The data-layer rules

The prompt is a third of it. The rest is what your storage and API refuse to do:

**Separate events from claims.** Bede keeps two stores. One holds a
psychometric claim *about the child* ("0.47 probability of having mastered
multi-digit multiplication"). The other holds an *event* ("on this date, a
multi-digit multiplication task was completed unaided"). They answer different
questions, both are wanted, and the distinction determines what a privacy switch
can turn off: setting the deployment to non-retaining drops the claim and keeps
the events, because an event record is not a judgment.

**A missed attempt writes no row.** Bede's work ledger does not record failed
attempts — that would make it a record of failures. Struggle is captured by the
estimator, which is the thing designed to represent it.

**Emit distributions, never averages.** A mean over an ordinal scale invents
precision the scale does not carry and reads as a grade.

**Every floor is a real outcome.** No scale in this pattern has a "poor" or
"slow" level. If your bottom level names a deficiency, the whole instrument is a
grade wearing different words.

**Ordering is fixed and meaningful, never sorted by score.** A list that
reshuffles as someone improves is a ranking of their own attributes.

**Say what the data does not mean, in the payload.** Bede's coverage endpoint
carries the refusal inside the response body — *"not a measure of interest,
engagement, or effort… says nothing about the person"* — and a test scans the
payload for `engagement`, `motivation`, `effort`, `score`.

## Adaptation notes

**Distinguish a finding about the plan from a finding about the person.** Bede's
"no evidence in this window" outcome is surfaced as *check that this is
scheduled often enough* at the schedule level, deliberately not next to the
child's name like a score. Same data; the placement is the whole ethics.

**Freeze your stored enum values; keep labels and criteria revisable.** Bede
stores level strings verbatim in encrypted blobs with no migration path, so
renaming one orphans every observation a family has accumulated. Wire values are
frozen; what a level *means* and what a user sees it *called* are not. Hence
`exemplary` → "one to show", `brisk` → "came easily".

**Never ship a metric for a dimension you have named unmeasurable.** Write the
prohibition into your contribution guide and add a test that fails if a field
matching the forbidden concept appears in a schema.

## How to test it

- **A test scanning your public payloads and tool descriptions** for the words
  you have refused to compute.
- **A test asserting the refusal sentences are still present** in the
  descriptions a consuming model reads.
- **A UI test with an all-floor-scored fixture** asserting it renders
  differently from an unscored fixture. This is the exact case that shipped
  broken twice.
- **A UI test asserting a zero-count panel does not render**, rather than
  rendering zeros.
- **A shape test on any multi-person view**: no per-person total anywhere, order
  independent of counts, absent rather than zero. Assert that the person with
  the largest count is not rendered first.
