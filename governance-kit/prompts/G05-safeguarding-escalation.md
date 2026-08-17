# G05 — Escalation and Crisis Handling

## What it prevents

An agent continuing to perform its task through a disclosure that should have
stopped it. The user says something that indicates harm, danger, coercion, or
crisis — and the agent, which is very good at its job, acknowledges it warmly in
one sentence and returns to the task in the next. This is the single worst
failure mode available to a conversational agent, and it is a *default*
behavior, not an edge case: every gradient in a helpful assistant points toward
continuing to help.

There are three sub-failures worth separating:

**Detection that runs only in one language.** Bede's safeguarding patterns were
English-only while the product shipped a live Spanish locale. A Spanish-speaking
child's actual distress language would not have matched anything. This is a
predictable defect in any regex-based crisis detector, and it is invisible in
testing because your test cases are written in your language. Note the fix: the
Spanish patterns are checked *unconditionally*, not gated behind the configured
locale, because a family can be multilingual in an English deployment.

**Detection that depends on a service.** If your only crisis detection is an LLM
classifier, then a classifier outage — timeout, rate limit, malformed response —
is a period during which crisis detection is off. Classifiers must fail open so
they never break the product; that is correct, and it means you need a
deterministic layer underneath that has no dependencies at all.

**A response that is generated rather than fixed.** If the crisis response is
composed by the model, it varies. Some variants will hedge, some will add
caveats, some will try to help with the underlying problem, and at least one
will be subtly wrong in a moment where wrong is expensive. This is the clearest
case in the whole kit for a fixed string.

## The block

```text
<escalation>
If the person expresses distress, fear, harm, danger, abuse, self-harm, or being
unsafe — at any point, in any language, however briefly or indirectly — STOP the
task immediately. Do not finish the current step. Do not add a caveat and
continue. Do not attempt to solve, counsel, assess, or explore the underlying
situation: you are not qualified and the attempt delays them reaching someone
who is.

Say only this: "{FIXED ESCALATION TEXT — short, warm, non-clinical, naming a
specific human destination and a concrete next action}"

Then stop. Do not resume the task in the same session.
</escalation>
```

Bede's fixed text, as a shape reference:

> "I hear you. Please find a parent or a trusted adult right now — your safety
> matters most. You can stop this session and go to them."

Four properties, all deliberate: it *believes them* first, it names a **specific
human**, it gives a **concrete action**, and it does not diagnose, reassure, or
ask a follow-up question.

## The detection layer

The prompt block is the last line, not the first. Escalation needs three
independent detectors because each fails differently:

| Layer | Mechanism | Fails when | Cost |
|---|---|---|---|
| 1 | Deterministic patterns, checked pre-model | Phrasing nobody enumerated | Free, instant, no dependencies |
| 2 | Classifier category, medium+ confidence | Service is down, prompt injected | One call, must fail open |
| 3 | The prompt block above | Model is under adversarial pressure | Free |

Layer 1 is the one people skip. It is the only layer with no dependency and no
inference, and it is the only one that still works during an outage. Write it
conservatively — **false positives are far cheaper than false negatives here**,
which inverts the tuning advice everywhere else in this kit.

See [`reference/adversarial_detection.py`](../reference/adversarial_detection.py)
for the pattern structure and
[`prompts/G12`](G12-moderation-classifier.md) for the classifier.

## Adaptation notes

**Enumerate your languages, then check them all unconditionally.** If your
product can be used in a language, crisis detection must exist in that language,
and it must not be gated behind a configured locale. Translate the *categories*
rather than the idioms — Bede's Spanish set deliberately excludes ambiguous
phrases that also mean something ordinary, because a crisis detector that
misfires on lesson content gets disabled by whoever is on call.

**Localize the response too.** A crisis is the worst possible moment to hand
someone a reply in a language they read less fluently than the one they just
reached for. Fall back to your primary language for locales you have not
translated — a correct response in the wrong language beats no response.

**Name a real destination for your users.** "A trusted adult" is right for a
child. For an employee-facing agent it may be a named internal function; for a
consumer product, a specific hotline. Get this reviewed by someone who actually
knows your user population. Do not put a generic crisis line in a workplace tool
and consider it handled.

**Separate crisis from ordinary content moderation.** Bede has two responses:
the escalation text above, and a much gentler redirect for a user who was
testing a boundary rather than in danger ("Let's keep our time focused on
today's subject — what would you like to explore next?"). Using crisis framing
for a boundary test is both inaccurate and needlessly alarming, and it teaches
users that the escalation response is noise.

## How to test it

- **Pattern coverage per language**, with a fixture per category per language.
  Assert on the *matcher*, not on model behavior.
- **String-pin the fixed response** in every locale you ship.
- **Test the bypass, not just the match.** The important assertion is that a
  matched message never reaches the model at all. Verify by asserting the model
  client is not called.
- **Test that a classifier failure does not break detection.** Force layer 2 to
  raise; assert layer 1 still stops the turn.
- **Audit for silent narrowing.** A test that the pattern list has at least N
  entries per language catches the well-meaning cleanup that removes "noisy"
  patterns.
