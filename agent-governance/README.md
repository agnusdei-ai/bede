# Agent Governance Prompts

A portable governance layer for LLM agents that take real actions: an
immutable constitution, four prompt blocks, and the code backstops that make
them more than advice.

Extracted from a production agent and stripped of everything domain-specific.
Nothing here names a product, persona, or subject matter — every such point is
a `{{PLACEHOLDER}}`.

```
constitution.template.json   The immutable layer. Copy to constitution.json, fill in, hash it.
placeholders.json            Every placeholder, documented. The builder refuses to leave one unresolved.
prompts/
  02-ethical-boundaries.md   What the agent is not, and what stops it.
  03-action-safety.md        Limits on actions the agent itself originates.
  04-operating-rules.md      Honesty and turn-shape rules.
  05-tool-guidance.md        How tools may be spent.
reference/
  governance.py / .ts        ~100-line builder: verify digest, assemble, resolve placeholders.
  parity_check.ts            Renders via the TS builder so a test can diff it against Python's.
  limits.py                  The constants a prompt cannot argue with.
  test_governance.py         Guards, each verified by breaking what it guards.
tools/build_pdf.py           Builds the whole package into one PDF (optional).
LICENSE / NOTICE             Apache-2.0. Use it, ship it, change it — see below.
```

## Quick start

```bash
cp constitution.template.json constitution.json   # fill in every {{PLACEHOLDER}}
$EDITOR constitution.json prompts/*.md
python3 - <<'PY'
import hashlib; print(hashlib.sha256(open('constitution.json','rb').read()).hexdigest())
PY
# paste that digest into EXPECTED_DIGEST in reference/governance.py (or .ts)
python3 reference/governance.py values.json > system_prompt.txt
```

`values.json` is a flat `{"PLACEHOLDER": "text"}` map. Rendering fails loudly
if any placeholder is missing — a shipped prompt containing the literal string
`{{PRINCIPAL}}` is worse than a missing rule, because it looks configured.

`tools/build_pdf.py` is not needed to use the package. It exists so the same
content can be handed to someone who will not clone a repository:
`pip install reportlab && python3 tools/build_pdf.py` writes
`dist/Agent-Governance-Prompts.pdf`. It reads the package files directly, so
the document cannot drift from the package — change a prompt, re-run it, and
the handout matches. `dist/` is deliberately **not** committed: a generated
artifact in git is a fresh binary blob on every rebuild, kept forever.

## The six layers, and which ones carry weight

| # | Layer | Where | Can an input argue with it? |
|---|---|---|---|
| 1 | Constitution | `constitution.json`, digest-verified at boot | No, but only because layer 6 verifies it |
| 2 | Ethical boundaries | `prompts/02` | Yes — it is text |
| 3 | Action safety | `prompts/03` | Yes |
| 4 | Operating rules | `prompts/04` | Yes |
| 5 | Tool guidance | `prompts/05` | Yes |
| 6 | Code backstops | `reference/limits.py` | **No** |

Layers 2-5 shape behavior in the overwhelmingly common case. Layer 6 is what
holds when they do not. Porting the prompts without the constants gives you
the appearance of governance and none of the enforcement.

## Six things worth understanding before adapting this

**1. Put the constitution in verified JSON, not in the prompt file.**
Rules as data can be tested, versioned, and proven unmodified at runtime. A
paragraph in a prompt file is editable by anyone with commit access and
nothing notices. `load_constitution()` refuses to start on a digest mismatch —
that refusal is the whole point.

**2. Render it into every prompt on the same identity.** Not just the main
persona: the summarizer, the planner, every sub-agent. An agent that is
governed in one code path and ungoverned in another is ungoverned.

**3. Action safety needs two branches and a tiebreaker.** `(a)` a risky but
ordinary action on the principal's own resources gets "state the risk, propose
the reversible alternative, ask." `(b)` anything that harms a third party,
evades a control, or conceals what was done gets a hard stop. A single
undifferentiated "redirect" under-escalates the second case, and that gap is
invisible until you write both branches out. The explicit tiebreaker — *when
in doubt, treat it as (b)* — is what makes the fork usable at runtime rather
than a classification problem.

**4. Tool results are data, never instructions.** `TRIVIAL_TOOL_RESULT` is a
fixed constant for exactly this reason. The moment a tool result carries free
text the process did not author, it is a prompt-injection vector into your own
context. For an agent that browses, this is the highest-risk line in the file.

**5. Confine external content by construction, not by setting.** The original
uses three independent mechanisms: a tool registry containing only
internal-trust specs, a function parameter defaulting to none rather than
reading config, and a call site that never passes it. The redundancy is
deliberate — the failure being prevented is one you learn about afterwards.
`assert_all_internal()` is the first of the three.

**6. Verify each guard by breaking the thing it guards.** Every test in
`test_governance.py` was confirmed to fail when its subject regresses. A test
that stays green through the regression is decoration.

## Two refusals worth copying whatever your domain is

**Never quantify what you have no standing to quantify.** Pick the thing your
product must not reduce to a number — and enforce it with a test that fails
when such a field appears, not with a review comment someone has to remember.

**A blank must never look like a low score.** Wherever the agent reports what
it observed, "not measured" and "measured poorly" must render differently.
Collapsing them turns an absence of evidence into a verdict.

## Adapting the numbers

`MAX_TOOL_CALLS_PER_TURN = 6` and `MAX_TOOL_LOOP_ROUNDS = 3` come from an
agent with ten tools, most of them trivially resolving. An agent with a
broader tool surface will want higher values — but pick them deliberately,
keep them constants rather than config, and check the cap *before* executing
rather than after, so the expensive or irreversible thing does not happen at
all.

## License

Apache License 2.0. Use it in commercial or closed products, modify it, and
redistribute it; keep the notice and state your changes. Full text in
`LICENSE`, attribution in `NOTICE`, and `SPDX-License-Identifier: Apache-2.0`
on each reference source.

Two things the licence does not do. It grants no trademark rights, and it
carries no warranty — the prompt text is a starting point, not an assurance
that an agent governed by it will behave. Governing an agent that takes real
actions stays the deployer's responsibility: fill every placeholder
deliberately, port the code backstops as well as the prose, and verify each
guard by breaking the thing it guards.

**`prompts/*.md` carry no licence header on purpose.** The builder reads those
files verbatim into the system prompt, so anything added at the top of one is
shipped into the model's own context. `test_no_license_header_leaks_into_the_rendered_prompt`
fails if a header ever reappears there.
