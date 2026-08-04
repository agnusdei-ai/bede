# Diagnosing a problem you cannot reproduce

This is the "what is actually happening on that device" guide. It covers
the always-on diagnostics both front-ends carry, how to read them, and what
each line means.

It exists because of a specific failure. On 2026-08-04 the public demo
could not start a session, and the only thing anyone could see was:

> Could not reach the server. It may be waking up after being idle.

That message was wrong, and confidently wrong. The server was healthy, the
database was fine, and the request had never been sent — a
Content-Security-Policy mistake meant the browser refused to connect to the
demo's own backend, and refused it *before* issuing the request. Nothing
appeared in the server logs, because nothing reached the server. The
investigation spent hours on DNS, CORS, credentials and the database.

The browser had known the answer the whole time and said so. Nothing in the
app was listening.

## What is collected, always

`demo/src/diagnostics.ts` and `homeschool-tutor/src/hooks/diagnostics.ts`
(twins — see either file's header) install four observers at boot, before
React mounts:

| Line | Meaning |
|---|---|
| `→ POST https://host/path` | A request was issued |
| `← 200 POST https://host/path (123ms)` | …and this was the response |
| `✗ POST https://host/path (12ms) TypeError: Failed to fetch` | …or it failed, with the **raw** error |
| `CSP BLOCKED directive=… blocked=… source=…` | A Content-Security-Policy refused something |
| `UNHANDLED REJECTION …` / `UNCAUGHT …` | An error nothing caught |
| `RESOURCE FAILED <script> https://…` | A script/image/stylesheet failed to load |

**A `→` with no matching `←` or `✗` is itself a diagnosis**: the request
was stopped before it was sent, which almost always means CSP.

This is genuinely always-on. Entries go to `debugBus`'s 100-entry ring
buffer, which nothing reads until you open the panel, so the cost when
unused is one array push per event. Nothing here changes app behaviour —
every handler observes and then re-throws or passes through untouched,
asserted by `demo/src/diagnostics.test.ts`.

## How to read it

**On the device (no tools needed).** In the App, the session header has a
`?`-style debug toggle that opens `DebugOverlay` — a fixed, monospace,
screenshot-able panel. Same in the demo. This is the path to give a parent
or a beta tester: *"tap that, screenshot it, send it to us."*

**From a console**, when you have one:

```js
__bedeDebugEntries()
```

Returns the buffer as structured objects. Added specifically for the
self-hosted case, where a family is on their own LAN, nobody can SSH in,
and the fastest support instruction is one line to paste.

## Privacy — what is deliberately NOT recorded

A debug panel is screenshot-able by design, and this is a children's
product, so the buffer is built to be safe to photograph:

- **Query strings are stripped.** Only `origin + pathname` is logged. A
  request to `/pod/configs?student=Emma` records `/pod/configs`. Pinned by
  test.
- **Headers and bodies are never recorded** — so no `Authorization`
  token, no lesson text, no narration, no child's message.
- Nothing is transmitted anywhere. The buffer lives in memory in that one
  tab and dies with it. It is not sent to a server, not persisted, and not
  included in feedback submissions.

If you extend this, keep that property. The moment the buffer can contain a
credential or a child's words, "screenshot it and email it to support"
stops being safe advice.

## Reading a CSP failure specifically

This is the case that motivated the file, and the one hardest to recognise
without help, because every other symptom points somewhere else: the server
sees no request, the network looks fine, and the app reports a generic
connection error.

```
→ POST https://bede-demo-api.onrender.com/auth/demo-code
✗ POST https://bede-demo-api.onrender.com/auth/demo-code (2ms) TypeError: Failed to fetch
CSP BLOCKED directive=connect-src blocked=https://bede-demo-api.onrender.com/auth/demo-code source=…/index.js:262
```

`directive=connect-src` names the exact policy at fault. The fix is in
`site/_headers` (for the demo and marketing site) or
`homeschool-tutor/nginx.conf` (for a self-hosted deployment), **not** in
application code.

One trap worth knowing, because it is what caused the outage: **a browser
enforces every CSP it receives.** If two policies are delivered, the
effective policy is their *intersection* — a second, narrower rule can
never widen the first, only narrow it. `site/_headers` is therefore
deliberately a single rule covering all paths; see its own comment, and
`homeschool-api/tests/test_site_headers.py`, which fails if a path ever
becomes matched by two blocks setting the same header again.

## The watchdog loop (unattended)

`.github/workflows/demo-watchdog.yml` runs `scripts/synthetic_journey.mjs`
every 30 minutes against the live demo. It drives a real Chromium through
the real first journey — load `/bede/`, accept consent, click "Generate my
code" — and reads back the diagnostics buffer above.

**Why a browser and not another `curl /health`.** `keep-demo-warm.yml`
already curls `/health` every 10 minutes and reported healthy right through
the 2026-08-04 outage. It could not have caught it: curl does not evaluate
CSP, does not send an `Origin` header, and does not enforce CORS, and the
failure lived entirely in those layers. This is the only check here that
fails for the same reason a visitor would.

On failure the report is handed to an agent driven by
`.github/agent-prompts/demo-repair.md` — a versioned, reviewable file
rather than a string in YAML, because it is the part of an unattended loop
most worth reading in a diff.

**What the loop may and may not do.** This is a deliberate departure from
the convention every other workflow here follows (`contents: read`,
`workflow_dispatch` only — see `adversarial-probe.yml`'s reasoning), and it
is bounded:

| | |
|---|---|
| **May edit** | `site/_headers`, `homeschool-tutor/nginx.conf`, the check script itself |
| **May never edit** | the constitution; auth/encryption/identity/policy code; moderation and safeguarding; **any test**; the workflow or the prompt |
| **May never** | merge — it opens a PR and stops; the `site/`/`demo/` sign-off rule is not suspended for automation |
| **May never** | open more than one PR per run |

A failing test is a finding to report, never an obstacle to remove. If a fix
would require touching the forbidden list, the agent stops and reports —
that is a correct outcome. An unattended agent with commit rights over
child-safety code is precisely the insider-compromise surface this product
exists to defend against.

**It reports even when it changes nothing**, including what it could not
verify from CI, and opens an issue (not a code workaround) when the cause
lives in Render, Cloudflare, or DNS rather than the repository.

## Related

- **Voice-specific tracing** — `docs/VOICE_SETUP.md` covers the mic/TTS
  pipeline's own log lines, which predate this file and remain the right
  reference for "the microphone is behaving strangely."
- **Server-side** — `GET /health` reports whether the API can actually
  reach its database and returns 503 when it cannot; a failed probe logs
  `Health check FAILED — database unreachable: <ExceptionType>: <detail>`.
  See `docs/DEMO_HOSTING.md`'s health-check section for why an
  always-200 health check hid this same outage.
