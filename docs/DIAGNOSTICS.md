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
  token, no narration, and **nothing the child said or typed**.
- Nothing is transmitted anywhere. The buffer lives in memory in that one
  tab and dies with it. It is not sent to a server, not persisted, and not
  included in feedback submissions.

**One exception, stated precisely rather than glossed.** The pre-existing
voice tracing in `useTextToSpeech.ts` records a 42-character preview of
**Bede's own generated speech** — `TTS speak() gen=3 text="Now, what do you
notice about…"` — so it can tell two utterances apart and spot the same one
spoken twice. That is lesson content, and it is Bede's half of the
conversation, never the child's. It predates the diagnostics described here
and is unchanged by them.

It matters because `__bedeDebugEntries()` adds a *new way to reach* that
buffer (the on-screen overlay already displayed it). The exposure is not
wider — same data, same tab, same origin, and the CSP permits only
first-party scripts — but "screenshot this and send it to us" may include a
line of what Bede was saying. Worth knowing before you give that
instruction to a family, and worth re-checking if anyone ever adds the
child's transcript to a log line.

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
every 30 minutes against the live demo, across desktop and two emulated
Android viewports — all three in one job, sequentially, because the
journey takes seconds per device and the Playwright install dominates.
It drives a real Chromium through the real first journey — load `/bede/`,
accept consent, click "Generate my code" — and reads back the diagnostics
buffer above.

### When the watchdog is red and the demo is fine

Check this before investigating the demo. On 2026-08-06 the workflow
reported failure for four hours while the demo was healthy: GitHub's
hosted runner pool never assigned a runner, so the jobs sat queued for
one to two hours each and were then cancelled having never started. In
the notification email that is indistinguishable from a real outage. On
the run itself it is unmistakable:

| Runner starvation | A real demo outage |
|---|---|
| Job conclusion `cancelled` | Job conclusion `failure` |
| `runner_id` 0, `runner_name` empty | A real runner is named |
| **No logs at all** — no step ever ran | A failing step, with the report printed |
| Ragged queue times (1h4m, 1h9m, 2h4m) | ~45 seconds |
| Another workflow cancelled in the same window | Only this one is affected |

That last row is the quickest tell: on 2026-08-06 `keep-demo-warm.yml`,
whose entire job is one `curl`, was cancelled the same way at 17:43. No
change to this repository could have caused that.

Nothing here can fix GitHub capacity. What the workflow does about it is
avoid making it worse — one runner request per tick rather than three, a
real `timeout-minutes` on both jobs, and a `check` that is superseded by
the next tick instead of wedging behind a run that never started. The
repair agent is correctly unaffected either way: its gate requires
`needs.check.result == 'failure'`, and a starved job is `cancelled`, so
it stays skipped. Never widen that to `!= 'success'`.

**Why a browser and not another `curl /health`.** `keep-demo-warm.yml`
already curls `/health` every 10 minutes and reported healthy right
through the 2026-08-04 outage. It could not have caught it: curl does not
evaluate CSP, does not send an `Origin` header, and does not enforce
CORS, and the failure lived entirely in those layers.

### Step 4: can picture study actually show a picture?

Added after every picture-study card on the demo was found blank — the
deployed CSP forbade both origins `VisualAidCard.tsx` needs, and the
session-start check could not see it because a session started fine.

**It does not drive Bede into calling `show_visual_aid`.** That would make
the watchdog depend on a model's choice: non-deterministic, several paid
LLM turns every 30 minutes, and flaky in a check whose entire value is
that it only goes red for real. The failure it guards against was
deterministic and had nothing to do with the model. So the probe performs
exactly what the component performs — the same summary lookup, then the
image that lookup returns — **inside the real page**, and is therefore
governed by the real deployed policy. That last part is the point: this
repository's `site/_headers` can be correct while the deployment serves a
stale or overridden header, and only a request made from the deployed
origin can tell the difference.

**One catalog entry, not all 23.** The failures being guarded against (a
policy that forbids the origins, a changed Wikimedia API shape, a changed
image host) show up on any entry. Validating every `wiki_title` is catalog
hygiene and belongs in a test, not in something that runs 48 times a day.

**The distinction that keeps it honest**, and the reason it is safe to run
unattended:

| Observation | Whose problem | Watchdog |
|---|---|---|
| A CSP violation naming wikipedia/wikimedia | **Ours.** No request was sent; waiting fixes nothing. Repairable from this repo (`site/_headers`). | **Fails**, `failedStep: "picture-study-csp"` |
| Lookup or image failed, no violation | Not ours — Wikimedia unreachable, slow, or an article renamed. The demo stays usable; the card falls back to its caption. | **Passes**, and says so in the summary |

Failing on the second row would wake a repair agent for someone else's
outage and teach everyone to ignore the alert. `report.pictureStudy`
carries the full evidence either way — `violations[]` with the exact
directive and blocked URI, plus `imageHost`, so a Wikimedia host change
names itself rather than having to be guessed.

On failure the report goes to an agent driven by
`.github/agent-prompts/demo-repair.md` — a versioned, reviewable file
rather than a string in YAML, because it is the part of an unattended
loop most worth reading in a diff.

**What the loop may and may not do.** A deliberate departure from the
convention every other workflow here follows (`contents: read`,
`workflow_dispatch` only — see `adversarial-probe.yml`), and bounded:

| | |
|---|---|
| **May edit** | `site/_headers`, `homeschool-tutor/nginx.conf`, the check script |
| **May never edit** | the constitution; auth/encryption/identity/policy; moderation and safeguarding; **any test**; the workflow or the prompt |
| **May never** | merge — it opens a PR and stops |
| **May never** | open more than one PR per run |

A failing test is a finding to report, never an obstacle to remove. If a
fix would need anything on the forbidden list, the agent stops and
reports — a correct outcome, not a failure. An unattended agent with
commit rights over child-safety code is precisely the insider-compromise
surface this product exists to defend against.

**It reports even when it changes nothing**, states what it could not
verify from CI, and opens an issue rather than coding a workaround when
the cause lives in Render, Cloudflare, or DNS.

**Operational note:** the repair half needs `secrets.WATCHDOG_API_KEY`
(dedicated and separately revocable). Without it the detector still runs
and still reports; only the automated repair is skipped.

## Related

- **Voice-specific tracing** — `docs/VOICE_SETUP.md` covers the mic/TTS
  pipeline's own log lines, which predate this file and remain the right
  reference for "the microphone is behaving strangely."
- **Server-side** — `GET /health` reports whether the API can actually
  reach its database and returns 503 when it cannot; a failed probe logs
  `Health check FAILED — database unreachable: <ExceptionType>: <detail>`.
  See `docs/DEMO_HOSTING.md`'s health-check section for why an
  always-200 health check hid this same outage.
