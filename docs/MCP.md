# Bede and MCP (Model Context Protocol)

MCP is an open standard for connecting AI assistants to tools and data. Bede
uses it in exactly one direction today: **Bede's own progress data can be read
by an assistant you already use.**

If you have Claude Desktop, Claude Code, or any other MCP-capable assistant,
you can point it at your Bede and ask "how is Ada doing in math?" without
opening the parent dashboard. That is the whole feature.

This is off unless you set it up. Nothing in the Bede stack changes, and
nothing new listens on your network.

---

## What it can and cannot do

**It can read**, and only these things:

| Tool | What it answers |
|---|---|
| `list_students` | Who is in the pod, their grade, subjects, companion mode |
| `get_mastery_summary` | Bede's current mastery estimate in one subject area |
| `get_work_ledger` | What one student has actually completed, and how much help it took |
| `get_pod_work_roster` | Which students have worked which skills |
| `get_narration_assessments` | Narration rubric history |
| `get_learner_profile` | The synthesized learner profile |

**It cannot write anything.** Not a config, not a session, not a deletion.
This isn't a promise in a policy document — the client module that backs every
one of these tools issues GET requests exclusively, and its test suite asserts
that by watching real request traffic rather than by reading the source. Every
tool is also annotated `readOnlyHint` in the protocol itself, so your
assistant knows it too.

**It cannot reach a child's tutoring session.** These are the same
parent-only endpoints the parent dashboard uses. Nothing here touches
`/tutor`, and nothing a child says is exposed.

**It cannot tell you which child is ahead.** The pod roster is grouped by
skill, not by student, with no per-student totals — and the tool's own
description tells the reading assistant not to construct one. See "The
refusals travel with the data" below.

**You can revoke it.** The MCP server registers itself as a device on login,
so it appears in Bede's device settings alongside your tablets and can be
revoked there like any of them. Revoking it stops both its outstanding token
and its next login attempt. This matters: the process holds your parent
password and can read every child's progress, so it should be as cuttable as
a lost tablet. Sending a device id is optional at Bede's API — a caller that
omits it can never be revoked, which is exactly why this one doesn't omit it.

It identifies itself by hostname, so one entry appears per machine you run it
on. If you run it on two machines that report the same hostname, set
`BEDE_MCP_DEVICE_ID` to any distinct string to tell them apart.

---

## Setting it up

### 1. Install

The MCP server runs on **your own computer**, not inside Bede's containers.

```bash
pip install -r scripts/mcp_server/requirements.txt
```

### 2. Configure your assistant

For Claude Desktop, add this to your MCP settings (Settings → Developer →
Edit Config):

```json
{
  "mcpServers": {
    "bede": {
      "command": "python",
      "args": ["/full/path/to/bede/scripts/mcp_server/server.py"],
      "env": {
        "BEDE_API_URL": "http://localhost:8000",
        "BEDE_PARENT_PASSWORD": "your parent password"
      }
    }
  }
}
```

`BEDE_API_URL` is wherever your Bede API answers — `http://localhost:8000` if
you run it on the same machine, or your LAN address (for example
`https://bede.local/api`) if it runs on another.

`BEDE_PARENT_PASSWORD` is the same password you use to log into Bede as a
parent. It is used to obtain a session token exactly as the web UI does.

### 3. Restart your assistant

Ask it something like "which students are in my Bede pod?" to confirm.

---

## If it doesn't work

**"This Bede deployment has parent MFA enrolled."**
If you've set up a security key or authenticator app for your parent account,
this server cannot log in — completing an MFA challenge needs a browser, and
this process doesn't have one. Your progress data stays available in the
parent web UI. This is a real limitation, not a bug, and it is the correct
trade: an MCP server able to bypass your second factor would be a worse thing
to own than one that can't log in.

**"Bede is rate-limiting login attempts."**
Wait about a minute. Bede limits repeated logins per IP, and the MCP server
shares your machine's address.

**"Bede refused the login."**
If several wrong passwords were tried recently, the parent role locks for 15
minutes. Wait it out rather than retrying.

**"Could not reach Bede at …"**
Check `BEDE_API_URL` from the same machine the assistant runs on:
`curl http://localhost:8000/health`.

**It stopped working after I changed my password.**
It shouldn't — the server re-authenticates automatically when its token is
rejected. Changing the parent password invalidates every existing session
immediately by design, and this recovers from that on the next request.

---

## The refusals travel with the data

Bede is careful about a few things that are easy to lose the moment data
leaves its own screens, so those rules are written into the tool descriptions
your assistant reads:

- **The pod roster is not a ranking.** Bede's API refuses to emit one and the
  parent UI refuses to render one, but any assistant could invent one just by
  adding up a child's work across skills. The tool description tells it not
  to: don't total, don't order children, don't describe one as ahead of
  another. A child absent from a skill hasn't scored zero — they haven't
  worked it yet.
- **Unscored work is a blank, not a low mark.** The two must stay
  distinguishable in anything written about them.
- **Mastery estimates are not test scores.** When `calibration` is true, Bede
  is still getting to know your child and the numbers are provisional.
- **A learning-style label is not a fact about your child.** It's a nudge to
  Bede's own tool choice, and nothing more.
- **Nothing about faith is measured.** There is no spiritual-engagement
  metric in Bede to expose, by constitutional design, and there is a test that
  fails if one is ever added here.

These are instructions to a model, so they are guidance rather than a
guarantee — unlike the read-only property above, which is structural. If you
notice your assistant ranking your children anyway, that is worth telling us
about.

---

## Why it's built this way

**Why does this run on my machine instead of inside Bede?**
Because the alternative is worse. Mounting an MCP endpoint inside the Bede API
would add a new authenticated network surface to the very process that serves
children. This design adds none: your assistant launches the server as a
subprocess, talks to it over stdin/stdout, and it reaches Bede through the
same REST endpoints your browser already uses. No new port, no new endpoint,
no new way in.

**Can Bede use MCP servers of my own — my book library, my own files?**
Not yet, and when it can it will be in the parent sandbox ("Ask Bede") only,
never in a child's lesson. Content from outside Bede is not something to put
in front of a child without a real boundary around it, and building that
boundary is separate work with its own rules. This page will link to it when
it lands.

---

## For developers

- `scripts/mcp_server/bede_tools.py` — the tool layer. No MCP dependency, so
  its logic is testable without one. Every refusal above lives in its
  `TOOL_SCHEMAS` descriptions.
- `scripts/mcp_server/server.py` — transport only. Registers each tool with
  `ToolAnnotations(read_only_hint=True)`.
- `scripts/mcp_server/test_bede_tools.py` — logic, against a stubbed transport.
- `scripts/mcp_server/test_server.py` — the seam between logic and protocol.
  This exists because the first cut of the server was written against the MCP
  SDK's 1.x decorator API, passed every logic test, and could not start at
  all: a unit test of the tool layer cannot see a transport that never comes
  up.
- `scripts/mcp_server/e2e_check.py` — run by hand, not in CI (it imports from
  `homeschool-api`). Speaks real MCP stdio to `server.py` against a stub Bede
  whose login endpoint validates with the API's **own** `LoginRequest` model.
  That strictness is the point: the first cut of `bede_tools.py` sent
  `password` where the API requires `credential`, and both the unit tests and
  an earlier, permissive version of this check accepted it. A fake looser than
  the real thing is a second place for the bug to hide.
- CI runs the two test files (`.github/workflows/test.yml`, `mcp-server-tests`).

The MCP SDK is pinned in `scripts/mcp_server/requirements.txt`, deliberately
apart from `homeschool-api/requirements.txt`, so the API image never carries a
dependency it doesn't use.
