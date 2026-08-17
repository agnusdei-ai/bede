# Field Notes

Five defects that produced patterns in this kit. Each one shipped, in
production, in a system whose team was paying attention. They are here because
a pattern with an incident behind it gets adopted and a pattern without one gets
skimmed.

Systems and domains are not named. What matters is the shape, and every one of
these shapes is domain-independent.

---

## 1. The stored injection vector, built out of a continuity feature

**What the rule was.** Operator-supplied configuration fields were sanitized,
because they sit in a cached prompt block for a whole session. Live user chat
text was not, because it was transient and there was no secret in context to
extract. Both halves were defensible and both were written down.

**What shipped.** A continuity feature. At the end of each session a summarizer
wrote one sentence recording where the work had stopped, stored it, and replayed
it into the next session's prompt so the following day could pick up mid-thread.

**Why it was a vulnerability.** Both halves of the assumption broke at once. The
sentence was written from a conversation the user had fully steered, and it was
replayed into prompt context in every future session. A stored injection vector,
assembled out of a feature nobody would think to threat-model, from a trusted
party, with no external input anywhere in the pipeline.

**The generalization.** The test is not provenance, it is **replay**. Asking
"where did this text come from" gives the wrong answer here, because the honest
answer is "from our own summarizer." Asking "does this get replayed into model
context later" gives the right one.

**The second-order lesson.** The fix had to run on both the write path and the
read path. Rows written before the bug was found were still live in deployed
databases, and encrypted blobs typically have no migration path. Sanitizing new
writes fixes the future and leaves the past sitting there.

Pattern: [G08](../prompts/G08-untrusted-content-envelope.md).

---

## 2. The guardrail that under-escalated a distress signal

**What shipped.** A physical-safety block for an agent that legitimately suggests
hands-on activity. Its hazard list named objects and environments: heights, fire,
sharp objects, water. Its instruction for handling a user-proposed risky activity
was single and sensible: redirect warmly to a safe alternative.

**What was missing.** Nothing in the hazard list named a person directing risk at
their **own body**: holding their breath, restricting food or water, extreme
temperature exposure, testing pain tolerance. Framed as part of the task, that is
exactly the shape a self-harm impulse can take. The single "redirect to a safe
alternative" instruction would have substituted a prop and continued the task
cheerfully past a distress signal.

**The fix.** Fork the response by risk type. Object and environment risk gets the
warm redirect. Anything targeting the person's own body routes to the escalation
path instead. Add an explicit tiebreaker for the ambiguous case, defaulting to
the safer branch: *when in doubt, treat it as the stop.*

**The generalization.** Two situations that look identical in the request can
require opposite responses. When you write a handling instruction, enumerate what
else matches its trigger. This was caught by a design-verification pass, not by
a test and not by a user, which is the only reason it is in this document rather
than an incident report.

Pattern: [G04](../prompts/G04-physical-safety.md).

---

## 3. The zeros under the encouraging heading

**What the rule was.** In a UI reporting observations about a person's work, only
the *top* of each scale earned a visible note. The floors are real outcomes
rather than deficiencies, so displaying them would read as marks against the
person. Sound reasoning, and it created the exact inversion of the thing it
protected.

**What shipped.** Two defects, both of which look fine until you construct the
right fixture:

- Work scored honestly at every floor earned no notes, produced no "not yet
  scored" line either, and so rendered **identically to work the agent had never
  judged at all.** A low mark passing for a blank, which is the mirror image of
  the rule "a blank must not look like a low mark."
- A panel gated on *zero scored activities*, so a person with no notable
  observations rendered `0 exemplary · 0 beyond the task · 0 brisk` under the
  heading **Signs of initiative**. Three zeros under that heading is a verdict on
  a human being, and the caveat underneath does not undo it.

**The fix.** State the scored count alongside the unscored one, so both halves
are always visible. Gate the panel on the counts themselves being zero, so it
reports a presence and never an absence.

**The generalization.** A rule protecting against one misreading routinely
creates its mirror image. Test the inverse case explicitly. An
all-floors-scored fixture is now a permanent test in that system, because no
amount of reading the code surfaces this.

Pattern: [G09](../prompts/G09-measurement-refusals.md).

---

## 4. The parameter that was tested and never passed

**What shipped.** A tuned estimator with a `params` argument carrying the
values a whole calibration phase existed to determine. Unit tests covered the
estimator thoroughly, passing `params` directly and asserting the results.

**What was wrong.** The one call site that actually used the estimator never
passed `params`. The tuned values were unreachable from the only path in
production that consumed them. Every test passed, because every test called the
function rather than the caller.

**The generalization.** A function that is tested but never correctly invoked is
untested in the only way that matters. Assert the **call site**: pass a sentinel
and observe it arrive downstream, rather than handing the function the value
yourself and confirming it uses what you handed it.

Two sibling cases from the same codebase, same shape:

- A client sent `password` where the schema required `credential`. A guaranteed
  422 against any real deployment. It survived because the unit tests stubbed
  the transport and the end-to-end stub accepted any JSON body. **A fake looser
  than the real thing is not a test, it is a second place for the bug to hide.**
  The stub now validates against the real schema object.
- A server was written against the wrong major version of an SDK's API and
  **could not start at all**. Every unit test passed.

Pattern: [`PHILOSOPHY.md`](PHILOSOPHY.md) §6.

---

## 5. The guard that fired on prose

**What shipped.** Privacy guards scanning source for the names of tables and
functions, to assert that certain categories of data were handled correctly.

**What was wrong.** Three of them were vacuous, all in the same way. The codebase
carries long explanatory docstrings, so a scan looking for a name *anywhere in
the file* matched the name inside a comment explaining why the thing was
deliberately **not** done. One guard read a model as user-scoped off a sentence
saying it deliberately cannot be joined to a user. Another read a table as
holding conversation content off the words "never a transcript." A third kept
passing after the `delete()` call it guarded was removed, because the function's
docstring still listed what it cleared.

**The fix.** Scan declarations, calls, and structured rows specifically, not free
text. A privacy guard that fires on a document saying the right thing is worse
than no guard, because it appears in a coverage report as though it were working.

**The generalization.** Verify every guard by breaking the thing it guards. All
three of these were found by doing exactly that, and none would have been found
by reading them.

Pattern: [`PHILOSOPHY.md`](PHILOSOPHY.md) §6, and the test-review section of
[`../checklists/PR_REVIEW_CHECKLIST.md`](../checklists/PR_REVIEW_CHECKLIST.md).

---

## What these have in common

None of them was caught by a benchmark, an evaluation suite, or a model. Four of
the five were found by someone deliberately trying to break a control they had
just written, and the fifth by a design review asking what else matched a
trigger.

That is the entire argument for the testing discipline in this kit. The failures
that matter in a governed agent are not the ones where something errors. They
are the ones where everything passes and the system quietly does something other
than what its own documentation says.
