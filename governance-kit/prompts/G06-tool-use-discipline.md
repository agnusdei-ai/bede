# G06 — Tool-Use Discipline

## What it prevents

Agentic loops fail in ways that single-turn chat does not, and prompt text alone
cannot prevent any of them. This block is half prompt, half enforcement — and
the enforcement half is the part that actually works.

**Unbounded consumption.** A model that can call tools in a loop can call tools
in a loop forever. Not usually maliciously — usually because a tool returned
something ambiguous and retrying looked reasonable. The cost lands on you, and
on the user waiting for a response that never streams.

**The hallucinated tool.** A model emits a tool name that does not exist. If
your dispatcher's default for an unknown name is anything other than "drop it
and grant nothing," a hallucinated tool can buy itself extra model round-trips —
which means the model can extend its own loop budget by inventing a callee.
Every predicate in your registry must default to `False` for unrecognized names.

**Tool results as an injection channel.** This is the important one. The moment
you feed a tool result back to the model as `tool_result`, you have created a
path from wherever that result originated straight into model context, on the
inside of your prompt, after all your guardrails. If a tool's output can contain
text authored by anyone outside your process — a search result, a database field
a user filled in, an MCP server, a scraped page — then that text is now
competing with your instructions.

**Facts about tools scattered across the codebase.** Whether a tool ends the
loop, whether its result is worth another round-trip, whether it renders
silently: encoded as `if name == "..."` checks buried in a streaming loop 1200
lines from the tool's schema. Nothing can be verified, and a tool added without
a matching branch silently does nothing at all.

## The enforcement layer

Prompt text is the weakest part of this control. These are the real ones:

**1. A trust tier on every tool, declared as data.**

```python
ToolSpec(name="lookup_reference", trust="internal",  reactable=True)
ToolSpec(name="mcp__books__search", trust="external", reactable=False)
```

`internal` means the result is computed by your process from its own state — a
lookup hit or miss, an already-persisted record, a fixed acknowledgment. It
cannot carry an instruction because there is nowhere in its provenance for an
instruction to have been authored. `external` means it came from outside.

The registry the untrusted-user-facing loop dispatches from contains **only
internal specs**. That is a structural guarantee: the loop cannot call an
external tool even if the model asks, even if the tool is registered elsewhere
in the same process, even if a prompt injection succeeds completely. External
tools live in a separate loop with a different audience — see
[G08](G08-untrusted-content-envelope.md).

Pair it with a test that fails if any tool in the user-facing registry is ever
marked external. That test is the control; the tier is just how you express it.

**2. Two independent caps.**

- `MAX_TOOL_CALLS_PER_TURN` (Bede: 6) — spans every round combined, never
  resets per round. A call past the cap is **dropped silently**: never executed,
  never rendered, the user's turn never interrupted. Log it as its own audit
  event and alert on it, because hitting this cap is either a bug or an attack.
- `MAX_TOOL_LOOP_ROUNDS` (Bede: 3) — how many model round-trips one response may
  take. Independent of and subordinate to the call cap.

One subtlety that bites everyone: if you suppress a `tool_use` block for
exceeding a cap, you can never send a matching `tool_result` — and the API
requires every `tool_use` in a turn to be answered before the next request. So
hitting the call cap must also end the loop. Do not try to be clever here.

**3. Only genuinely dynamic results extend the loop.** Most tool calls resolve
to a fixed acknowledgment, so an ordinary turn is a single round-trip, exactly
as it was before you added a loop. Only tools whose outcome the model could not
have predicted — a lookup that can miss, a computation that returns a value —
earn `reactable=True`. This keeps latency and cost flat for the common case and
shrinks the surface where round-2 reasoning happens at all.

**4. Audit every dispatched call.** Not attempted — dispatched. Tool name, actor,
context, timestamp. This is your only durable record of what the agent actually
did, and it is what turns "something weird happened" into an answerable question.

**5. Guard against within-turn repetition.** A successful reactable call buys
extra rounds, and those rounds re-send the *cached* system block — so any
"already done this" state computed once per turn is stale by round 2. Bede's
visual-aid tool showed the same image three times in one turn for exactly this
reason. Track it turn-scoped in the dispatch branch, and answer a repeat
honestly (`{"found": true, "already_shown": true}`) rather than suppressing it
silently or faking a miss, which sends the model hunting for a different id to
fix a failure that never happened.

## The block

```text
<tool_use>
You have these tools: {NAME} — {when to use it, in one clause}; {NAME} — {...}.

Say each thing once per turn. If a tool renders content the person can see,
never restate or closely paraphrase the same content in your prose in the same
turn. Choose the tool output or the prose, not both.

{TOOL} and {TOOL} render output that carries no next step of its own. Never let
one of these be the last thing in a turn — continue with your own text and a
genuine next step immediately after, per operating rule 3.

{TOOL} ends the current task and hands off. Never use it as a shortcut around
the work itself; {THE ALTERNATIVE TO TRY FIRST}.

Do not call a tool to look busy. A turn with no tool call is a normal turn.
</tool_use>
```

## Adaptation notes

**Put the prose next to the schema.** Models read the description field
adjacent to each tool's JSON schema far more reliably than a rule far away in
the prompt. The block above is for cross-tool discipline; per-tool guidance
belongs in the tool's own description.

**"Do not call a tool to look busy" is not filler.** Models reach for tools to
signal effort. If any of your tools writes data, that tendency is a data-quality
problem as well as a cost one.

**Silent tools need an explicit contract.** Bede has four tools that emit
nothing to the user at all — they persist a record and return nothing. Mark them
in the registry and test the contract, or someone will "fix" one by making it
return a status and change its behavior for every caller.

## How to test it

- **Every registered tool has a dispatch branch, and every branch is
  registered.** Set equality both directions. This is the test that catches the
  tool that silently does nothing.
- **Every tool in the user-facing registry is `internal`.** The structural
  guarantee, asserted.
- **Unknown names grant nothing.** Assert every registry predicate returns
  `False` for `"tool_that_does_not_exist"`.
- **Caps hold across rounds.** A test that drives 3 rounds × 3 calls and asserts
  exactly `MAX_TOOL_CALLS_PER_TURN` were dispatched — the per-round reset bug is
  the easiest one to write and the hardest to notice.
- **Cap-hit ends the loop.** Assert no further model request is made after
  suppression, or you will ship an API error on a real user turn.
- **A turn with no tools is byte-identical to pre-loop behavior.** The
  regression test that lets you keep the loop.
