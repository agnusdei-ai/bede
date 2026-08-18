# Bede and MCP (Model Context Protocol)

MCP is an open standard for connecting AI assistants to tools and data. Bede
uses it in two directions, and they are set up separately:

1. **Bede's progress data, read by an assistant you already use.** Point
   Claude Desktop, Claude Code, or any MCP-capable assistant at your Bede and
   ask "how is Ada doing in math?" without opening the parent dashboard. Most
   of this page is about this direction.
2. **Your own MCP servers, consulted by Bede** — a book library, a file
   server — while you work in the parent sandbox ("Ask Bede"). Never in a
   child's lesson. See "The other direction" near the end.

Both are off unless you set them up, and each can be used without the other.
Direction 1 adds nothing listening on your network. Direction 2 lets Bede make
outbound calls to servers you name, and nothing else.

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
Yes, in the parent sandbox ("Ask Bede") only, never in a child's lesson. See
the next section.

---

## The other direction: Bede consulting your MCP servers

Bede can also connect *out* to MCP servers you run, so that while you are
working in "Ask Bede" it can consult your own book library or file server.

This is off by default, and turning it on takes both variables:

```
MCP_EXTERNAL_ENABLED=true
MCP_EXTERNAL_SERVERS=[{"name":"books","url":"http://192.168.1.20:9000/mcp"}]
```

Each server needs a name (letters, numbers, dashes, underscores) and an
http(s) URL the Bede container can reach. Bede speaks the Streamable HTTP
transport; it never launches a program on your server for this.

### Where it can and cannot be used

**Only in your own sandbox.** Not in any child's tutoring session, and not in
the public demo preview — which shares the same underlying code path, so this
is worth being precise about. Three separate things keep it there:

1. A child's tutoring session is only ever given Bede's own internal tools.
   External tools are not in that list, so the tutor cannot call one even if
   a server is connected.
2. The sandbox receives external tools as something the caller passes in, and
   the default is none.
3. The demo route never passes them, and there is a test that fails if it
   ever starts to.

That is more redundancy than it sounds like it needs. It is there because the
thing being prevented — a child, or an anonymous visitor, reading text an
outsider wrote in Bede's voice — is the sort of failure you only find out
about afterwards.

### What Bede does to a result before reading it

In order: credential-shaped text is redacted, prompt-injection phrasing is
stripped, the result is truncated if it is very long, and what remains is
wrapped in a label telling Bede it is information from outside to consider
and report, never instructions to follow.

That last part is guidance to a model rather than a guarantee, and it is
worth being honest about the difference. A determined attacker who controls
one of your MCP servers can write persuasive text. What makes that survivable
is the confinement above: the person reading it is you, in a sandbox that
saves nothing, not your child mid-lesson.

Every external call is written to the audit log as its own event, separate
from ordinary tool use, so you can see exactly when outside content entered a
conversation. Repeated use in a short window raises the same kind of alert
other unusual activity does.

**A tool from one of your servers cannot impersonate one of Bede's.** External
tools are renamed `mcp__<server>__<tool>`, so a server advertising something
called `assess_narration` gets `mcp__books__assess_narration` and cannot be
confused for the real thing.

**Bede offers your server nothing in return.** It connects declaring no
capabilities — in particular not sampling, which would let your MCP server ask
Bede's own model for completions and spend your API budget.

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
apart from `homeschool-api/requirements.in`, so the API image never carries a
dependency it doesn't use.
