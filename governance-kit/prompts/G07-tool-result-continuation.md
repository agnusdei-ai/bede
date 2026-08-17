# G07: Tool-Result Continuation

## What it prevents

The agent greeting or praising a person for something they did not do.

This is a small bug with an outsized effect on trust, and it appears the moment
you add a multi-round tool loop. The sequence: the model emits some text, calls
a tool, receives the `tool_result`, and continues generating in the same turn.
From the model's position, what just arrived is *a new message in the
conversation*. It is not. Nothing happened on the user's end: they have not
spoken since the turn began, and they are watching a single response stream.

So round two opens the way a reply to a person opens: "Great thinking!" "That's
a really good point." "Let me know if that helps!": praise attached to a
silence. Users notice this immediately and read it, correctly, as the system not
tracking who said what.

The same failure has a second trigger worth handling in the same rule: an
idle-timeout or silence sentinel. If you send something like `[CONTINUE]` when a
user goes quiet, the model treats that as their turn and affirms it. Same shape,
different cause: one is a pause on the user's side, one is a pause of the
model's own making.

## The block

```text
Sometimes, after you call a tool, you receive its result back and keep speaking
in the same turn: this can happen more than once before your reply is done.
That result is the OUTCOME of your OWN tool call, never a new message from the
person: they have not spoken since this turn began, and nothing has happened on
their end while you waited for it. Keep the reply moving forward as one
continuous thought rather than opening fresh: never a new greeting, and never
praise or react as though they just said something.
```

And the sentinel variant, if you use one:

```text
When the message is exactly "{SENTINEL}", the person went quiet after your last
turn and said NOTHING. Never mention the pause, never ask if they are still
there, never repeat your last question verbatim, and, just as important, never
open as though they just answered: no "great start", no "that's thoughtful", no
praising, affirming, or reacting to a response, because there is not one to react
to. Instead move the conversation forward yourself: rephrase what you asked more
concretely, offer a specific detail that opens a new angle, or move on to the
next thing.
```

## Adaptation notes

**Write both rules and cross-reference rather than duplicate.** They are the
same principle applied to two triggers. State the distinction explicitly and
point at the sentinel rule by number rather than restating its wording, which is
only safe because operating rules are numbered and never renumbered
([G02](G02-operating-rules.md)).

**"Never open as though they just answered" is the load-bearing clause.**
"Do not greet again" is the obvious instruction and it is insufficient: the
failure is usually an affirmation rather than a greeting. Name affirmation
specifically.

**Consider whether you need this at all.** If every tool in your loop is
non-reactable, so the loop always exits after one round, this rule costs
prompt tokens for a case that cannot occur. Add it when you add your first reactable
tool, not before.

## How to test it

You cannot verify model behavior with a unit test, so verify the guardrail's
*presence*:

- **String-pin the rule text** in the built prompt. This is the entire test, and
  it is worth having: guardrail prose is exactly what a prompt-tidying refactor
  removes, and no functional test anywhere will go red.
- **Assert the cached block is identical across rounds.** If you rebuild the
  system prompt per round, assert round 1 and round 3 produce byte-identical
  text. A rule that is present in round 1 and absent in round 3 governs nothing
  at the moment it is needed.
- **Behaviorally**, run a fixture that forces a reactable tool call and inspect
  the round-2 opening. Score it by hand a few times; it is obvious when it is
  wrong.
