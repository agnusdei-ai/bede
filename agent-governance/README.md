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
prompts/                     Always rendered.
  02-ethical-boundaries.md   What the agent is not, and what stops it.
  03-action-safety.md        Limits on actions the agent itself originates.
  04-operating-rules.md      Honesty and turn-shape rules.
  05-tool-guidance.md        How tools may be spent.
prompts/optional/            Opt-in, by name — see "Extending it" below.
  10-untrusted-content.md    For an agent reading anything it did not author.
profiles/                    Filled-in placeholder sets for a real agent.
  openclaw.values.json       A starting point for OpenClaw. Read before using.
  openclaw.runbook.md        Deploying packaged OpenClaw with this layer, in order.
  openclaw.hardened.json5    The config that runbook copies. Every key schema-verified.
reference/
  governance.py / .ts        ~100-line builder: verify digest, assemble, resolve placeholders.
  parity_check.ts            Renders via the TS builder so a test can diff it against Python's.
  limits.py                  The constants a prompt cannot argue with.
  test_governance.py         Guards, each verified by breaking what it guards.
tools/build_pdf.py           Builds the whole package into one PDF (optional).
tools/verify_openclaw_profile.test.ts
                             Checks the profile against OpenClaw's real registry. By hand.
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

## Extending it

Adding a block needs no code change. Drop a file in `prompts/` (always on) or
`prompts/optional/` (rendered only when named), document any new
`{{PLACEHOLDER}}` in `placeholders.json`, and that is the whole procedure —
`test_adding_a_block_needs_no_code_change` proves it by creating a block,
rendering, and removing it.

```python
render(values, extra_blocks=["10-untrusted-content"])   # core + one optional
```

Optional blocks are off by default on purpose. A rule that does not apply to
your agent is prompt budget spent teaching it to worry about nothing, and
every block dilutes the ones that do apply. Take what your agent's actual
surface calls for.

## What this covers when the agent reads untrusted input

`prompts/optional/10-untrusted-content.md` exists because of a specific,
well-documented class of failure: personal agents wired to messaging apps and
given shell access. Through 2026, [OpenClaw](https://github.com/openclaw/openclaw)
accumulated 138 CVEs, and researchers reported
[40,000+ internet-exposed instances](https://www.infosecurity-magazine.com/news/researchers-40000-exposed-openclaw/)
— a deployment pattern the project itself advises against, since its security
guide tells operators to bind the Gateway to loopback. Independent researchers
demonstrated [prompt injection and data exfiltration](https://thehackernews.com/2026/03/openclaw-ai-agent-flaws-could-enable.html)
through ordinary inbound messages, and PromptArmor showed link-preview
metadata working as an exfiltration channel — the agent is induced to build an
attacker-controlled URL, and the preview fetch delivers the payload.

**The project's own position is the clearest statement of where this package
sits.** OpenClaw's `SECURITY.md` says plainly that *"the model/agent is not a
trusted principal"* and that security boundaries come from host and config
trust, auth, tool policy, sandboxing, and exec approvals. It also puts prompt
injection out of scope as a vulnerability class unless it crosses one of those
boundaries. That is the right call for a threat model, and it is exactly why a
governance layer is a complement to it and never a replacement: the boundaries
do the enforcing, and this shapes the judgment exercised inside them.

| Failure class | This package | Where |
| --- | --- | --- |
| Direct injection: "ignore previous instructions", persona override | Covered | `02` rules 3-4 |
| Indirect injection: web pages, files, email HTML, skill manifests | Covered | `10`, plus `wrap_untrusted()` |
| Persisted-note injection: text the agent wrote and later reloads | Covered | `10` |
| Secret extraction, including partial or encoded | Covered | `10` |
| Bulk export of history, contacts, credential stores | Covered | `10` |
| Outbound exfiltration via URL, preview, webhook, QR, DNS | Covered | `10` |
| Self-modification: config patch, permission widening, skill install | Covered | `10`, `03` |
| Unbounded tool loops and runaway action counts | Covered | `limits.py` |
| External tools reachable from a sensitive loop | Covered | `assert_all_internal()` |

**What it cannot cover, and no prompt can.** The largest failures of this
kind were never behavioural. A Gateway listening on a public interface without
authentication is not persuaded by a system prompt.
[CVE-2026-25253](https://www.betterclaw.io/blog/openclaw-security-2026) —
taking a `gatewayUrl` from a query string, opening a WebSocket to it and
sending a stored token — is an input-validation bug in code that runs before
any model sees anything. Credentials in plaintext on disk, an unauthenticated
pairing flow, a missing sandbox, an unvetted skill marketplace: all of these
are fixed in the deployment or not at all.

## Deploying it

`profiles/openclaw.runbook.md` connects the two halves: installing packaged
OpenClaw and applying this layer, in the order that matters. Install, close the
network surface **before anything listens**, cut the tool surface, pair
deliberately, and only then render the prompt into the workspace `AGENTS.md`
that OpenClaw loads at the start of every session.

It ships the config rather than describing it: `profiles/openclaw.hardened.json5`
is a real file an operator copies to `~/.openclaw/openclaw.json`, and the
runbook's control table says what each key buys instead of restating it. The
by-hand verifier checks three things at once — every key exists in the real
schema, the config actually sets what the table promises, and the network
surface is genuinely closed (`bind: "loopback"`, `gateway` denied, a sandbox
on). Eight assertions, each verified by breaking it.

The ordering is the content. Steps 2-4 are enforcement and hold whatever the
model does; step 5 shapes judgment and can be argued with. Installing the
prompt while skipping the config produces something that feels governed and is
not — which is why the runbook puts `gateway.bind: "loopback"` before anything
about prompts.

One trap worth naming here because it is silent:
`agents.defaults.bootstrapMaxChars` defaults to 20,000 and oversized bootstrap
files are **truncated on injection, not rejected**. A governance prompt that
overflows loses its tail and nothing says which rules stopped loading. The
rendered profile is ~12,200 characters, and the runbook has you check with
`wc -c` after every edit.

## Profiles

`profiles/openclaw.values.json` fills all 17 placeholders for a single-operator
messaging agent, written against OpenClaw's documented model: the operator is
the only principal, a message on a connected channel is a request from whoever
sent it and never a grant of the operator's authority, and skills are code
someone else wrote. It renders at roughly 3,200 tokens with the
untrusted-content block included.

**The profile has been checked against the running registry, not just read
off the docs.** `tools/verify_openclaw_profile.test.ts` is a vitest test that
imports OpenClaw's own `isKnownCoreToolId`, `normalizeToolPolicyName`, and
`CORE_TOOL_GROUPS` and asserts every tool the profile names actually exists.
It runs inside a clone of that repository, by hand — it imports their modules,
so it cannot run in this package's CI, and pretending otherwise would be worse
than saying so. Last run 2026-08-21 against `07c8b42a`: 4 passed.

That run earned itself immediately. The published tool table lists `cron` in
`group:automation`, and the registry normalizes `cron` to `automations` — a
permanent alias under their RFC 0026, the same contract as `bash` to `exec`.
The profile now names the canonical id and the alias, which reading the
documentation alone would not have produced.

Its tool guidance names **real tools**, not categories — `read`/`write`/`edit`/
`apply_patch`, `exec` (with `bash` as its alias), `message`, `web_fetch`,
`gateway`, `cron`, `sessions_spawn`, `ask_user`, `skill_workshop` — grouped the
way that project groups them, because a rule about "your shell tool" attaches
to nothing a model can act on. The names were read from the repository at a
pinned commit and each was confirmed to appear in `src/` rather than taken from
the documentation alone. Tool names change:
`test_every_profile_records_where_its_facts_came_from` requires each profile to
cite the commit it was checked against, since a stale name in a governance
prompt is worse than no rule at all — the rule attaches to nothing and reads as
though it does.

It is a starting point, not a configuration — nobody should paste a profile
written by someone who has never seen their deployment and treat it as
finished. `test_every_profile_fills_every_placeholder` keeps it honest, and a
second guard requires each profile to say so in its own `_note`.

So treat this package as the layer that governs the agent's own judgment once
it is running, not as a mitigation for how it is exposed. Shipping it beside
an unauthenticated port would be the more dangerous outcome of the two,
because the prompt makes the system feel governed. Layer 6 is where the
enforceable part lives — and even that stops at the process boundary.

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
