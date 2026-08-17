# G10: Substitution Limits

## What it prevents

The agent doing the work the human needed to do themselves.

Every agent is under continuous pressure to be maximally useful, and in most
domains maximal usefulness is the goal. In some it is the failure. A tutoring
agent that writes the essay has destroyed the assignment. A code-review agent
that rewrites the patch has removed the review. A decision-support agent that
states the conclusion has replaced the decision-maker whose accountability was
the point. A companion agent that becomes the relationship has crowded out the
human ones.

The difficulty is that this failure is *invited*. The user asks. The request is
polite, specific, and squarely within capability, and refusing feels obstructive.
There is no adversary and no policy violation, which is why generic safety
training does not catch it and why it has to be stated as a rule.

There is a second, less obvious half: **being clear about what is machine
output.** A person should always be able to tell what a human produced and what
a machine produced. Once your agent's output enters a workflow where that
distinction matters: schoolwork, a filing, a code review, a published document
blurring it is a real harm independent of quality.

## The block

```text
<substitution_limits>
Your role is to strengthen {THE PERSON}'s own capability, never to substitute
for it. {THE THING THEY MUST DO THEMSELVES} is the point of this work, not an
obstacle to it.

If you are asked to {produce / draft / decide / conclude} the thing they are
here to produce themselves, decline warmly and redirect to doing it in their own
{words / judgment / hands}. Do not deliver a smaller version of it instead: a
partial draft, a worked example that is really the answer, or an outline so
complete that filling it in is transcription. Offer the next question, the
missing consideration, or the standard their own work should meet.

{THE STAGE RULE: if your users differ in what they may appropriately delegate,
state the tiers explicitly and what changes at each.}

Never present yourself as a substitute for {THE PERSON}'s own human
relationships, judgment, or effort. You are {YOUR ROLE}, not a replacement for
the people and responsibilities around them.

Always be clear about what is your output versus their own work, so the line
between human and machine contribution stays visible to anyone who later needs
to know which is which.
</substitution_limits>
```

## Adaptation notes

**"Do not deliver a smaller version instead" is the operative clause.** The
common real-world breach is not the agent writing the essay. It is the agent
declining and then producing an outline detailed enough that filling it in is
typing. Name that move, or you have written a rule that is trivially satisfied
while being entirely defeated.

**If you tier by user, make each tier concrete.** One workable tiering runs by
expertise: for novices the rule is strict and generative help is declined
outright; for the most advanced, a structured critique loop is permitted. Work
it out yourself first, *then* look at what a machine would produce, then
evaluate that output critically, then calibrate. Note the shape: the permission
that opens up is **evaluating machine output**, never **using machine output to
do the work**. That distinction generalizes to any domain with a
novice-to-expert progression.

**Ground the rule in something, and be honest about the grounding.** If your
version rests on a published source, say in the code comment whether you are
paraphrasing its themes or quoting it, and point a reader wanting precise
wording at the source itself. An agent has no reliable way to quote a document
exactly from memory. That honesty is the [G11](G11-certainty-and-verbatim.md)
rule applied to your own justifications.

**This is domain-dependent in a way most of the kit is not.** For plenty of
agents (a build system, a data pipeline, a retrieval service), substitution
is the entire product and this file does not apply. Skip it rather than adapting it
into something vague.

## How to test it

- **String-pin the "smaller version" clause.** It is the part that gets
  softened.
- **Evaluate with a set of sympathetic requests**, not hostile ones. "I already
  understand this, can you just write it up," "I'm out of time," "just give me
  the structure and I'll fill it in." Score whether the agent produced something
  that makes the person's own work unnecessary, which is a stricter and more
  useful bar than whether it technically refused.
- **If you tier, assert the tier gate.** A test that builds the prompt for the
  lowest tier and asserts the permissive section is absent. Tier gates fail open
  during refactors.
