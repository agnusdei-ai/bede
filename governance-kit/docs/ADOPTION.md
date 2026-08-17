# Adoption Path

Ordered by value per hour, not by topic. Stopping after any phase leaves you
better off than when you started — that is deliberate, because most teams will
stop somewhere.

Total for all four phases: roughly a week of one engineer's time for a system
that already exists.

---

## Phase 0 — Answer three questions (30 minutes, no code)

Do not skip this. Every decision downstream depends on the answers, and teams
that skip it end up adopting controls that do not fit their risk.

**1. Who is harmed if this agent is wrong, and can they tell?**

The second half matters more. An agent advising an expert who can spot a bad
answer is a different risk class from one advising someone who cannot — a child,
a patient, a novice, anyone under time pressure. If your users cannot evaluate
the output, fluency is a hazard rather than a feature, and
[G11](../prompts/G11-certainty-and-verbatim.md) moves up your list.

**2. If a prompt injection fully succeeds, what does the attacker get?**

Walk it through concretely. Is there a secret in context? Can a tool result
carry an instruction? Can the agent take an action with side effects? If the
honest answer is "not much," you can tune detection toward far fewer false
positives — and you should, because every false positive is a real user blocked.
If the answer includes anything with side effects, [G06](../prompts/G06-tool-use-discipline.md)
and [G08](../prompts/G08-untrusted-content-envelope.md) are your priority and
nothing else comes close.

**3. What does this agent compute about a person, and who sees it?**

If the answer is "nothing," skip [G09](../prompts/G09-measurement-refusals.md)
entirely. If it stores anything — a score, a profile, a preference, a summary —
read it first, because that is the pattern teams most often wish they had
adopted before their data model set.

Write the answers down. They are the beginning of your threat model — see
[`THREAT_MODEL_TEMPLATE.md`](THREAT_MODEL_TEMPLATE.md).

---

## Phase 1 — The constitution (half a day)

The highest-leverage single change available, because it converts your values
from prose anyone can edit into an artifact with change control.

1. Copy `templates/constitution.template.json` into your project and fill it in.
   Budget most of your time on `authority_order` and `non_negotiable_rules`; the
   rest is scaffolding.
2. Copy `reference/constitution.py`. Set the path, `EXPECTED_ID`, and your
   structural requirements. **Delete the `try/except` at the bottom** — a failed
   verification must be fatal in your deployment.
3. Pin the digest: `python pin_digest.py constitution.json`.
4. Call the loader at process start, before serving traffic.
5. Render the preamble into **every** prompt that shapes behavior. Grep for
   every place you build a system prompt — the summarizer and the internal tools
   are the ones people miss.
6. Add the four tests from [G01](../prompts/G01-constitution-preamble.md), and
   verify each by breaking it.

**Done when:** corrupting the constitution file prevents startup, and a test
asserts the preamble reaches every prompt builder you have.

---

## Phase 2 — Prompt blocks (one to two days)

Add in this order. Each is independent, so ship them one at a time.

| Order | Block | Skip if |
|---|---|---|
| 1 | [G03](../prompts/G03-ethical-boundaries.md) role limits | Never skip |
| 2 | [G02](../prompts/G02-operating-rules.md) operating rules | Never skip |
| 3 | [G05](../prompts/G05-safeguarding-escalation.md) escalation | Your users cannot disclose personal circumstances to your agent |
| 4 | [G11](../prompts/G11-certainty-and-verbatim.md) certainty | You quote nothing that must be exact |
| 5 | [G04](../prompts/G04-physical-safety.md) physical safety | Your agent never suggests real-world actions |
| 6 | [G10](../prompts/G10-substitution-limits.md) substitution | Substitution is your product |
| 7 | [G09](../prompts/G09-measurement-refusals.md) measurement | You compute nothing about people |

For each: paste the block, replace every `{PLACEHOLDER}`, put it in your
**cached static prompt block**, and add a string-pin test.

The string-pin tests feel pointless and are the whole point. Guardrail prose is
exactly what a prompt-tidying refactor removes, and no behavioral test will
catch it.

**Done when:** every block is present, every placeholder is replaced, and a test
fails if any block disappears.

---

## Phase 3 — The detection pipeline (two to three days)

Only worth doing after Phase 2, since the prompt blocks are what a redirected
turn falls back on.

1. **Tier 1** — copy `reference/adversarial_detection.py`. Extend the patterns
   for your domain. Read the note on why social engineering has no Tier-1
   pattern before adding one.
2. **Tier 2** — take the classifier prompt from
   [G12](../prompts/G12-moderation-classifier.md), adapt the categories, wire it
   to the client you already have. Do not add a vendor. 3-second timeout,
   `temperature=0`, **fail open**.
3. **Policy** — copy `reference/policy_engine.py`. Set your blocking and
   audit-only sets from G12's table, and argue about the assignment now rather
   than during an incident.
4. **Wire the order**: Tier 1 and safeguarding patterns *before* the model call;
   classifier; policy; then the agent.
5. **Audit every decision**, blocking or not, and alert an accountable human on
   a sustained pattern rather than a single flag.

**Done when:** an injection targeting the classifier itself still gets flagged,
a forced classifier outage still leaves Tier 1 working, and the policy function
has a test per category-and-confidence combination.

---

## Phase 4 — The agent loop (two to three days, only if you have tools)

1. Copy `reference/tool_registry.py`. Declare every tool with its trust tier.
2. Add the test that **every tool in the user-facing registry is internal**.
   This is the structural guarantee; everything else here is bookkeeping.
3. Add both caps. Remember that hitting the call cap must also end the loop, or
   you will ship an API error on a real user turn.
4. Add [G07](../prompts/G07-tool-result-continuation.md) if any tool is
   reactable.
5. If you consume external content, copy `reference/external_content.py` — and
   make the confinement decision from
   [G08](../prompts/G08-untrusted-content-envelope.md) *before* you build the
   feature, not after.

**Done when:** a hallucinated tool name grants nothing, the caps hold across
rounds, and a turn with no tool calls is byte-identical to your pre-loop
behavior.

---

## Ongoing

- **Re-run your false-positive corpus when you change models.** Classifier
  behavior is model-specific and moves between versions. So do the known
  misattributions in your domain.
- **Review the audit log for patterns**, not incidents. The single flag is
  rarely the story.
- **Re-read your threat model when you add a feature that persists text.** The
  replay question is a required review item, not a judgment call.
- **When you find a new failure, add the guard and verify it by breaking it** —
  then consider contributing it back.

---

## If you only have one day

Phase 0 (30 min), then Phase 1 (half day), then G03 and G02 from Phase 2. That
combination gets you: values under change control, verified at startup, present
in every prompt, with role limits and a central discipline that has a
no-exceptions clause. It is a small fraction of the kit and most of the
protection.
