<!-- SPDX-License-Identifier: Apache-2.0 -->
# Deploying packaged OpenClaw with this governance layer

The order matters more than any single step. Every command and config key below
was read from `openclaw/openclaw` at commit `07c8b42a` and verified against the
running code — tool names via `isKnownCoreToolId`, config keys by walking
`buildConfigSchemaCore()` (4,451 keys). Re-check them against the commit you
are actually installing.

**The governance prompt is the last layer, not the first.** It shapes judgment
inside the boundaries; it does not create them. Steps 2-4 are what actually
stop an attacker, and skipping them while installing the prompt produces
something that feels governed and is not.

---

## 1. Install the package

```bash
curl -fsSL https://openclaw.ai/install.sh | bash     # or:
npm install -g openclaw@latest --allow-scripts=openclaw
```

A container image and `docker-compose.yml` ship in the repo if you would rather
not install onto the host — worth preferring, since step 3 exists because
`exec` runs on the host by default.

**Do not start the Gateway yet.** Onboarding creates config and workspace; the
window between "listening" and "hardened" is the one that produced the exposed
instances found in the wild.

## 2. Close the network surface before anything listens

```json5
{
  gateway: {
    bind: "loopback",              // "auto" | "lan" | "loopback" | "custom" | "tailnet"
    auth: { token: "<random 32+ bytes>" },
  },
}
```

`bind: "loopback"` is the single most valuable line in this file. A Gateway
reachable from the network is the failure class no prompt touches, and it is
how tens of thousands of instances ended up publicly enumerable. If you need
remote access, reach it over a tailnet or an authenticated proxy — never by
widening the bind.

## 3. Cut the tool surface to what this agent actually needs

```json5
{
  tools: {
    profile: "messaging",          // or "coding"; "minimal" is session_status only
    deny: ["gateway", "sessions_spawn"],
    fs: { workspaceOnly: true },
    exec: { applyPatch: { workspaceOnly: true } },
  },
  agents: { defaults: { sandbox: { mode: "non-main" } } },  // default is "off"
}
```

Four facts worth knowing before you choose:

- **`exec` is host-first by default.** `agents.defaults.sandbox.mode` defaults
  to `off` and `tools.exec.host` defaults to `auto`, so commands run on the
  host machine unless you turn a sandbox on. That is a deliberate
  trusted-operator default, not an oversight — but it is the difference
  between a mistake and an incident.
- **`gateway` is the self-modification tool.** Denying it is what makes the
  prompt's self-modification rule enforceable rather than advisory.
- **`sessions_spawn` should stay denied** unless you actually delegate; that is
  the project's own guidance, and it bounds how far one compromised turn
  spreads.
- **`bash` is an alias for `exec`, and `cron` for `automations`** (their RFC
  0026). Denying an alias without its canonical id denies nothing.

## 4. Start, then pair deliberately

```bash
openclaw onboard        # creates config + workspace, seeds bootstrap files
openclaw pairing approve <request>
```

DM-capable channels pair unknown senders by default. Every approval is a person
who can now reach a machine with `exec` on it. Approve individually; never
leave a channel open because it was convenient during setup.

## 5. Install the governance layer

Render the prompt and write it where OpenClaw actually reads instructions —
`AGENTS.md` in the agent workspace, loaded at the start of every session:

```bash
python3 reference/governance.py profiles/openclaw.values.json \
  > ~/.openclaw/workspace/AGENTS.md      # agents.defaults.workspace
```

Render with the untrusted-content block for any agent joined to a channel:

```python
render(values, extra_blocks=["10-untrusted-content"])
```

**Watch the budget — this is the step with a silent failure mode.**
`agents.defaults.bootstrapMaxChars` defaults to **20,000** per file and
`bootstrapTotalMaxChars` to 60,000 across all of them, and oversized bootstrap
files are **truncated on injection**, not rejected. A governance prompt that
overflows loses its tail quietly, and nothing tells you which rules stopped
being loaded. The rendered profile is ~12,200 characters, which fits — but
`AGENTS.md` shares the total budget with `SOUL.md`, `USER.md`, `IDENTITY.md`
and the rest, so check it after every edit:

```bash
wc -c ~/.openclaw/workspace/*.md
```

Put the non-negotiables early in the file for the same reason: if anything is
ever cut, let it be the elaboration rather than the rules.

If you manage these files yourself and do not want them reseeded, set
`agents.defaults.skipBootstrap: true`.

## 6. Verify, and keep verifying

```bash
# the tool names your prompt cites are real, in a clone of openclaw/openclaw
pnpm vitest run src/agents/governance-profile-tool-names.test.ts \
  --config test/vitest/vitest.agents-core.config.ts

# the prompt renders with no unresolved placeholder
python3 -m pytest reference/test_governance.py -q

# nothing is listening beyond loopback
ss -tlnp | grep -v '127.0.0.1\|::1'

# the bootstrap files still fit their budget
wc -c ~/.openclaw/workspace/*.md
```

Re-run all four after any OpenClaw upgrade. Tool ids and config keys are that
project's to change, and a governance rule naming a tool that no longer exists
reads exactly like one that works.

## Every key this runbook sets

Dotted form, so it can be checked mechanically — the JSON5 above nests them.
`tools/verify_openclaw_profile.test.ts` asserts each one exists in the real
config schema, because a key that does not exist is accepted silently by a
JSON5 config and simply does nothing: the hardening step reads as done and is
not.

| Key | Set to | Without it |
| --- | --- | --- |
| `gateway.bind` | `"loopback"` | The Gateway is reachable from the network |
| `gateway.auth.token` | a random secret | Anyone who reaches it is the operator |
| `tools.profile` | `"messaging"` or `"coding"` | Every tool is available to every turn |
| `tools.deny` | `["gateway", "sessions_spawn"]` | The agent can rewrite its own config and fan out |
| `tools.fs.workspaceOnly` | `true` | File tools reach the whole filesystem |
| `tools.exec.applyPatch.workspaceOnly` | `true` | Patches land outside the workspace |
| `agents.defaults.sandbox.mode` | `"non-main"` or `"all"` | `exec` runs on the host (the default is `off`) |
| `agents.defaults.workspace` | your workspace path | You cannot tell which `AGENTS.md` is loaded |
| `agents.defaults.bootstrapMaxChars` | leave at 20000, or raise deliberately | A long prompt is silently truncated |
| `agents.defaults.skipBootstrap` | `true` only if you manage the files | Bootstrap reseeds files you maintain |

## What none of this covers

A live injection attempt has not been run against this configuration. Steps 2-4
are enforcement and hold regardless of what the model does; step 5 shapes
judgment and can be argued with by a sufficiently clever input. Treat the
prompt as the layer that makes good behaviour likely, and the config as the
layer that makes bad behaviour impossible — and never let the first stand in
for the second.
