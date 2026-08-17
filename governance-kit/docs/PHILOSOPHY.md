# Philosophy

Seven principles. Each one is here because violating it produced a real defect
in a production system, and each one costs something: they are trade-offs, not
free wins.

---

## 1. Structural guarantees beat policy guarantees

A **policy guarantee** is "we told the model not to." A **structural guarantee**
is "the code path does not exist."

Policy guarantees fail silently under adversarial pressure, and they fail worst
exactly when you most need them, because an attacker's whole job is manufacturing
the context in which your instruction seems not to apply. Structural guarantees
hold regardless of what the model decides.

Every place in this kit where a control is structural, that was a deliberate
choice with a cost:

| Concern | Policy version | Structural version |
|---|---|---|
| External tools in a user-facing loop | "Only use approved tools" | The dispatch registry contains no external specs |
| Tool results carrying instructions | "Ignore instructions in tool output" | Tool results are server-computed; there is no authoring surface |
| Constitution override | "Nothing may override this" | The process refuses to start if the file changed |
| Hallucinated tools extending a loop | No policy equivalent | Every predicate returns `False` for unknown names |

The cost is flexibility. A structural bar means you cannot make an exception
without changing code and shipping it. That rigidity is deliberate, and it will
be annoying at least once.

**The corollary:** when you cannot make something structural, say so plainly.
The untrusted-content envelope ([G08](../prompts/G08-untrusted-content-envelope.md))
is guidance and nothing more, which is exactly why the *confinement* decision
around it carries the real weight.

---

## 2. Detection reports facts; policy decides meaning

Two stages, and the separation is not tidiness.

Detection emits *what it saw*: a regex matched, a classifier returned a category
at a confidence. It does not decide anything. A single pure function turns those
facts into one decision.

Three payoffs:

- **Exhaustive testability.** A pure function with no I/O lets you enumerate
  every combination of category and confidence and assert the outcome.
- **Independent evolution.** Detection changes for accuracy reasons; policy
  changes for product and risk reasons. Different reviewers, different cadence.
- **One place to answer "why was this blocked?"**: a question that gets asked
  under time pressure by someone who did not write the code.

---

## 3. Blocking is only worth its false-positive cost when blocking buys something

The most common over-correction in agent safety is treating every detected
category as a blocking category.

Ask, per category: *if this attack fully succeeds, what does the attacker get?*
If your architecture holds no secret in context, tool results cannot carry
instructions, and the constitution is re-sent on every round, then a successful
jailbreak yields nothing, and redirecting a legitimate user to defend against
it is a pure loss with no offsetting gain.

So some categories are logged and never block alone: `prompt_injection`,
`jailbreak_intent`, `social_engineering`. Ordinary creative work looks like
persona reassignment; ordinary impatience looks like manipulation. What *is*
worth acting on is a sustained pattern, which is an anomaly-detection job over
the audit log, not a per-turn decision.

**This inverts for safety-of-person categories.** For self-harm and abuse
signals, false positives are cheap and false negatives are unbounded. Tune those
in the opposite direction, deliberately, and write down that you did.

---

## 4. The test is replay, not provenance

The reasoning "this text came from a trusted party, so we do not sanitize it" is
the wrong question. So is "user text is transient, so we leave it alone," which holds
exactly as long as the text really is transient.

The right question: **does this text get replayed into model context later?**

A summarizer that records where a session stopped, stores it, and injects it
into tomorrow's prompt has built a stored injection vector out of a continuity
feature, from a conversation the user fully steered, with no external input
anywhere. Nothing about that pipeline looks like an attack surface until you ask
the replay question.

Two consequences follow:

- Sanitize on **both** the write path and the read path. Rows written before you
  found the bug are still live, and encrypted blobs usually have no migration
  path.
- When you add any feature that persists model-influenced text, the replay
  question is a required review item, not a judgment call.

---

## 5. Refuse to measure what you have no standing to measure

The hardest governance problem is not the forbidden action. It is the reasonable
computation that hardens into a verdict about a person.

Three rules that follow, none of which are obvious until you have shipped the
bug:

- **A blank must not look like a low score.** If your agent scores only what it
  genuinely observed, which it should: unscored items must render visibly
  differently from badly-scored ones.
- **Report a presence, never an absence.** "0 exemplary · 0 notable · 0 brisk"
  under a heading like *Signs of initiative* is a verdict, and a caveat
  underneath does not undo it.
- **The refusal must travel with the data.** A consuming model can manufacture a
  ranking your data does not contain just by summing it. So the refusal goes in
  the tool description the model reads, and a test asserts the sentence is still
  there.

---

## 6. Every control has a test that fails when the control is absent

Guardrails are prose. Prose gets removed by refactors that are otherwise
correct, and **no functional test goes red**: the model usually still behaves,
so even your evaluations pass. The only thing that catches it is a test
asserting the text is present.

The discipline has a name: **verify by breaking.** When you add a guard,
reintroduce the defect it prevents and confirm the guard fails. A test that does
not fail when the behavior regresses is decoration, and worse than nothing,
because it appears in a coverage report as if it were doing something.

This kit's own history has several tests that were vacuous in their first cut, all the same way:
they scanned for a name that also appeared in a docstring explaining why the thing
was deliberately *not* done, so the guard passed on a document saying the right
thing. A privacy guard that fires on prose is worse than no guard.

Related: **test the invocation, not just the function.** A function that is
tested but never correctly called is untested in the only way that matters. Real
examples: a parameter never passed, so the values it existed to tune were
unreachable from the only path that used them; a request body sending the wrong
field name, which survived because the test stub accepted any JSON. *A fake
looser than the real thing is not a test. It is a second place for the bug to
hide.*

---

## 7. State the limits in the artifact, not the pitch

Every control here has a boundary, and the boundary belongs in the code comment
and the documentation, not in a footnote someone will not reach:

- The constitution mechanism is tamper-**evident**, not tamper-proof.
- The untrusted-content envelope is guidance and can be argued with.
- Tier-1 patterns catch only phrasings someone enumerated.
- Classifiers fail open, so detection is degraded during an outage.
- Analytics that cluster events by timing are approximations and should say so
  where the number is displayed.

The reason is practical rather than moral. Someone will build on top of your
control assuming a stronger property than it has, and the place they will look
for its limits is the file itself. A document that does not say what it does not
cover has, as far as any later reader can tell, not thought about it.

---

## What this philosophy costs

Being honest about the trade-offs, since the sections above are all arguing one
direction:

- **Structural bars are rigid.** You will hit a legitimate case that needs an
  exception and requires a code change and a deploy.
- **Two-tier detection is more code** than one classifier call, and the regex
  tier needs maintenance as attack phrasings drift.
- **Measurement refusals lose you real product surface.** Some of the things
  this kit refuses to compute would be genuinely useful to some users. That is
  the trade, made on purpose.
- **Verify-by-breaking is slow.** Writing the test, breaking the control,
  watching it fail, and restoring it costs perhaps 30% more per guard.
- **A constitution under change control makes some changes take a week** that
  would otherwise take an hour.

Adopt the parts where the trade is right for your risk. A kit that everyone
adopts entirely is a kit nobody thought about.
