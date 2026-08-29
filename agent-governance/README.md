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
  02-ethical-boundaries.md   The agent's limits, and what stops it.
  03-action-safety.md        Limits on actions the agent itself originates.
  04-operating-rules.md      Honesty and turn-shape rules.
  05-tool-guidance.md        How tools may be spent.
prompts/optional/            Opt-in, by name — see "Extending it" below.
  10-untrusted-content.md    For an agent reading anything it did not author.
  11-local-peer-connector.md For an agent another program on the same machine can call.
profiles/                    Filled-in placeholder sets for a real agent.
  openclaw.values.json       A starting point for OpenClaw. Read before using.
  openclaw.runbook.md        Deploying packaged OpenClaw with this layer, in order.
  openclaw.hardened.json5    The config that runbook copies. Every key checked.
reference/
  governance.py / .ts        ~100-line builder: verify digest, assemble, resolve placeholders.
  parity_check.ts            Renders via the TS builder so a test can diff it against Python's.
  limits.py                  The constants a prompt cannot argue with.
  test_governance.py         Guards, each verified by breaking what it guards.
tools/harden-openclaw.sh     One command: hardened config, prompt installed, result checked.
tools/build_pdf.py           Builds the whole package into one PDF (optional).
tools/verify_openclaw_profile.test.ts
                             Checks the profile against OpenClaw's real registry. By hand.
assets/contributor.jpg       Contributor photo, used by the README and the PDF.
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

You do not need `tools/build_pdf.py` to use the package. It exists so you can
hand the same content to someone who will not clone a repository:
`pip install reportlab && python3 tools/build_pdf.py` writes
`dist/Agent-Governance-Prompts.pdf`. It reads the package files directly, so
the document cannot drift from the package — change a prompt, re-run it, and
the handout matches. `dist/` is deliberately **not** committed. A generated file
in git becomes a fresh binary blob on every rebuild, kept forever.

## Deploy it in one command

If you are setting up OpenClaw on your own machine and would rather not read
the rest of this first:

```bash
bash tools/harden-openclaw.sh
```

It writes a hardened configuration with a fresh access token, installs the
governance prompt where OpenClaw reads it, and then checks its own work and
tells you what it found. It backs up anything it replaces, it is safe to run
twice, and it stops with an error if the result is not actually hardened. When
it finishes it prints the two things left for you to do by hand: list who is
allowed to message the agent, and approve them once.

Everything below explains what that command did and why.

## What it does not do

**Nothing here reports anywhere.** No telemetry, no analytics, no version ping,
no usage counter, no callback of any kind. The package reads files and writes a
prompt. Someone adopting a governance layer is handing it their agent's entire
context, so that property is checked rather than promised:
`test_nothing_here_calls_home` scans every shipped Python, TypeScript and shell
file for a network call and fails on one.

**Nothing here carries a product name.** This started as one company's internal
governance layer, and the extraction is what makes an Apache-2.0 grant possible
over a proprietary codebase. `test_no_file_names_the_proprietary_product`
enforces that in both directions, and it checks itself as well, which is why
the name it looks for is assembled from fragments rather than spelled out.

Both guards were confirmed by breaking them: a file naming the product fails,
an installer running `curl` fails, and a Python helper opening a URL fails.

## What has been verified

- **40 automated guards** ship with the package and run in CI, 82 cases once
  parametrized over the files they scan. Each one was confirmed to fail when
  the thing it guards is broken, which is the only way to know a test is doing
  anything.
- **8 assertions run inside a clone of `openclaw/openclaw`** at commit
  `07c8b42a`, against that project's own code rather than its documentation.
  Tool names go through `isKnownCoreToolId` and `normalizeToolPolicyName`.
  Config keys are checked against `buildConfigSchemaCore()`, all 4,451 of them.
  The shipped config is parsed and its values asserted.
- **The installer was run end to end**: a fresh install, a second run over an
  existing config, two installs to confirm the access token differs each time,
  and a deliberately weakened config to confirm it exits with an error instead
  of reporting success.

Those checks caught four real defects that reading alone would not have. The
scheduler tool is `automations` and `cron` is an alias for it, so a policy
naming only `cron` denies nothing. The TypeScript builder could not run at all.
The config file is `~/.openclaw/openclaw.json`, not the path the documentation
implied. And `channels.*.allowFrom`, which decides who can reach the agent, was
missing from the hardening set entirely.

**What has not been done:** no live Gateway has been stood up and attacked. The
configuration is verified against the real schema and the prompt against the
real registry, and neither of those tells you how a running agent behaves under
a determined injection attempt. That test is worth doing and is the next one.

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
class of failure that is documented in detail. Personal agents get wired to
messaging apps and given shell access. Through 2026, [OpenClaw](https://github.com/openclaw/openclaw)
accumulated 138 CVEs, and researchers reported
[more than 40,000 instances exposed on the internet](https://www.infosecurity-magazine.com/news/researchers-40000-exposed-openclaw/)
— a deployment pattern the project itself advises against, since its security
guide tells operators to bind the Gateway to loopback. Independent researchers
demonstrated [prompt injection and data exfiltration](https://thehackernews.com/2026/03/openclaw-ai-agent-flaws-could-enable.html)
through ordinary inbound messages, and PromptArmor showed link-preview
metadata working as a way to move data out. The agent is talked into building
a URL the attacker controls, and the preview fetch delivers the payload.

**The project's own position states where this package sits, better than this
README did.** OpenClaw's `SECURITY.md` says plainly that *"the model/agent is
not a trusted principal"*, and that security boundaries come from host and
config trust, auth, tool policy, sandboxing, and exec approvals. It also puts
prompt injection out of scope as a vulnerability class unless an attack crosses
one of those boundaries. That is the right call for a threat model. It is also
why a governance layer complements those boundaries and cannot replace them.
The boundaries do the enforcing. This shapes the judgment exercised inside
them.

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
| A local program treated as the operator because it is on the same machine | Covered | `11`, `peer_is_authorized()` |
| A peer request answered by a near-match capability nobody agreed to | Covered | `11`, `resolve_peer_capability()` |
| Peer content relayed to a hosted model or an outbound request | Covered | `11` |
| An attacker-controlled frame length allocated against | Covered | `MAX_PEER_FRAME_BYTES` |

**Against the published advisories, this package patches nothing.** The
[jgamblin/OpenClawCVEs](https://github.com/jgamblin/OpenClawCVEs) tracker lists
157 advisories as of 2026-08-21, 51 with a CVE id and 106 awaiting one. Of the
113 carrying CWE tags, 62 are authorization or access control defects and 12
are command execution. Every one of those is fixed by running a fixed version
of OpenClaw. What the shipped config changes is who can reach them, since
`bind: "loopback"` and an auth token take the unauthenticated network attacker
out of the picture. `profiles/openclaw.runbook.md` breaks the numbers down and
puts the upgrade check first, because the largest class of defect is closed by
upgrading and by nothing in this directory.

**What it cannot cover, and no prompt can.** The largest failures of this kind
were never behavioural. A system prompt has no effect on a Gateway listening on
a public interface without authentication.
[CVE-2026-25253](https://www.betterclaw.io/blog/openclaw-security-2026) —
taking a `gatewayUrl` from a query string, opening a WebSocket to it and
sending a stored token — is a bug in how input is checked, in code that runs
before any model sees anything. Credentials in plaintext on disk, an unauthenticated
pairing flow, a missing sandbox, an unvetted skill marketplace: all of these
are fixed in the deployment or not at all.

## What this covers when another program on the machine calls the agent

`prompts/optional/11-local-peer-connector.md` is for the case where a second
program on the same machine can send the agent requests over a local socket or
pipe. That arrangement is usually built for good reasons — a companion app, a
desktop client, a device daemon — and it quietly changes who can ask the agent
for things. Being on the same machine is not authorization, and a connector
that treats a local caller as an extension of its own operator has no boundary
left to enforce.

The block says four things. The peer is a separate party and carries none of
the operator's authority. Everything it sends is untrusted content under the
block above, including any field it labels as an instruction or a policy. The
agent answers only the specific capabilities it was built to answer, and does
not improvise a close equivalent or widen one to fit — refusing is the correct
outcome, not a failure to be helpful. And content that arrives this way stays
on the machine: it is not summarized to a hosted model, quoted into an outbound
request, or used to build one.

The enforcement lives in the connector, not here. A closed registry of named
capabilities with no default handler, a peer credential check at accept time,
a hard size bound read from the frame header before anything is allocated, and
a model resolver that fails closed rather than falling back to a hosted API.
The prompt block covers the judgment left over once those hold.

## Deploying it

`profiles/openclaw.runbook.md` connects the two halves: installing packaged
OpenClaw and applying this layer, in the order that matters. Install, close the
network **before anything listens**, cut back the tools the agent can reach,
pair deliberately, and only then render the prompt into the workspace `AGENTS.md`
that OpenClaw loads at the start of every session.

It ships the config instead of describing it. `profiles/openclaw.hardened.json5`
is a real file an operator copies to `~/.openclaw/openclaw.json`, and the
runbook's control table says what each key buys instead of restating its value.
The by-hand verifier checks three things at once. Every key exists in the real
schema, the config actually sets what the table promises, and the Gateway really is
unreachable from the network (`bind: "loopback"`, `gateway` denied, a sandbox
on). Eight assertions, each verified by breaking it.

The ordering is the content. Steps 2-4 are enforcement and hold whatever the
model does. Step 5 shapes judgment, and a determined input can argue with it.
Installing the prompt while skipping the config produces something that only
feels governed, which is why the runbook puts `gateway.bind: "loopback"` ahead
of anything about prompts.

One trap worth naming here because it is silent:
`agents.defaults.bootstrapMaxChars` defaults to 20,000 and oversized bootstrap
files are **truncated on injection, not rejected**. A governance prompt that
overflows loses its tail and nothing says which rules stopped loading. The
rendered profile is ~12,200 characters, and the runbook has you check with
`wc -c` after every edit.

## Profiles

`profiles/openclaw.values.json` fills all 17 placeholders for a single-operator
messaging agent, written against OpenClaw's documented model. The operator is
the only principal. A message on a connected channel is a request from whoever
sent it, and it carries none of the operator's authority. Skills are code
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
pinned commit, and each one was confirmed to appear in `src/` instead of being
taken from the documentation alone. Tool names change:
`test_every_profile_records_where_its_facts_came_from` requires each profile to
cite the commit it was checked against, since a stale name in a governance
prompt is worse than no rule at all — the rule attaches to nothing and reads as
though it does.

Treat it as a starting point. Nobody should paste a profile written by someone
who has never seen their deployment and treat it as finished. `test_every_profile_fills_every_placeholder` keeps it honest, and a
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
text the process did not author, it becomes a way for someone else's words to
reach your model. For an agent that browses, this line carries the most risk in
the file.

**5. Confine external content by construction, not by setting.** The original
uses three independent mechanisms: a tool registry containing only
internal-trust specs, a function parameter that defaults to none instead of
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
keep them as constants instead of config, and check the cap *before* executing
instead of after, so the expensive or irreversible thing never happens at
all.

## Contributors

<img src="assets/contributor.jpg" alt="JK Gonzalez" width="120" align="left"
     style="margin: 0 16px 8px 0; border-radius: 8px;" />

**JK Gonzalez** — security practitioner. Commissioned this package, reviewed
every layer of it, and is putting it in front of a real OpenClaw deployment.
The direction that shaped it came from practice rather than from theory: check
the running registry instead of the documentation, ship the config instead of
describing it, and say plainly which failures a prompt cannot touch.

<br clear="left" />

## License

Apache License 2.0. Use it in commercial or closed products, modify it, and
redistribute it. Keep the notice and state your changes. Full text in
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
