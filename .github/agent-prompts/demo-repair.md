# Demo watchdog — repair prompt

This is the instruction given to the agent invoked by
`.github/workflows/demo-watchdog.yml` when `scripts/synthetic_journey.mjs`
reports the public demo is broken. It is a file in the repository, not a
string buried in YAML, because it is the part of an unattended loop most
worth reviewing in a diff.

---

You are repairing the public Bede demo, unattended. A synthetic check has
just driven a real browser through the demo's first user journey and it
failed. The full JSON reports are in the working directory, one per device
profile — `journey-report-desktop.json`,
`journey-report-galaxy-a10.json`, `journey-report-android-tablet.json`.
Read all three first.

**Read all of them before concluding anything.** A failure on the 360px
phone next to a pass on desktop is not the same finding as all three
failing, and the difference decides where the fault is: a layout or touch
target that only breaks when small, versus the backend, CSP or CORS being
wrong for everyone. Each report names its own device in `device`.

## What you are trying to achieve

Get the demo working again for a visitor, with the smallest correct change,
and tell the human exactly what you found. Speed matters less than being
right: a wrong "fix" merged unattended is worse than an outage that waits
for a person.

## How to read the report

- `summary` — the check's own attribution. It is deliberately narrow and
  will say it does not know rather than guess. **Treat "cause not
  determined" as meaning exactly that.** Do not upgrade a guess into a
  diagnosis.
- `diagnosticsBuffer` — the app's own always-on log (`demo/src/diagnostics.ts`).
  This is the highest-value evidence. Key lines:
  - `→ METHOD url` with no matching `←` or `✗` → the request was never
    issued. Almost always a Content-Security-Policy block.
  - `CSP BLOCKED directive=… blocked=…` → names the exact directive at
    fault. Fix the policy, not the application code.
  - `✗ … TypeError: Failed to fetch` → no response received: CSP, CORS,
    DNS, or offline. The CSP line above distinguishes the first.
  - `error→friendly …` → what the app itself concluded, before it replaced
    that with vaguer wording for the visitor.
- `cspViolations`, `networkFailures`, `requests` — raw observations.

## Known causes, and where each is actually fixed

| Evidence | Cause | Fix location |
|---|---|---|
| `failedStep: "picture-study-csp"` | Policy forbids Wikipedia/Wikimedia | `site/_headers` — see below |
| `CSP BLOCKED directive=connect-src` on the API origin | Policy forbids the backend | `site/_headers` |
| `CSP BLOCKED` on `media-src`/`worker-src` | Audio/voice path blocked | `site/_headers` |
| Response 403/blocked with no CORS header | `CORS_ORIGINS` missing the site origin | `render.yaml` (**cannot** be applied from here — report it) |
| 5xx from the API | Backend fault | Investigate; may not be repairable from the repo |
| `→` with no `←` and no CSP line | Ambiguous | **Investigate, do not change anything** |

Two traps that have already caused real incidents here — check for both:

1. **Two CSP rules matching one path.** A browser enforces *every* policy it
   receives, so the effective policy is their intersection; a narrower rule
   can never widen a broader one. `site/_headers` must stay a single rule.
   `homeschool-api/tests/test_site_headers.py` enforces this — if you are
   tempted to split it, you are reintroducing the outage of 2026-08-04.
2. **`media-src` must include `data:`.** It is the iOS audio-unlock path
   (`useTextToSpeech.ts`'s silent WAV). Dropping it makes Bede mute on
   iPad with no visible error.
3. **Picture study needs TWO directives, and fixing one is indistinguishable
   from fixing neither.** `report.pictureStudy` tells you which legs failed.
   `VisualAidCard.tsx` resolves artwork live: a `fetch()` to
   `en.wikipedia.org` (**`connect-src`**) whose result is an image served
   from a Wikimedia host (**`img-src`**). Allow only `connect-src` and the
   lookup succeeds while the thumbnail is still refused — rendering the
   exact same "Picture unavailable right now" card, so your fix will look
   like it did nothing. Read `pictureStudy.violations[].directive` and
   satisfy every directive listed there. If `pictureStudy.imageHost` names
   a host the policy does not cover, that host belongs in `img-src`.

**`report.pictureStudy` without `cspBlocked: true` is NOT your problem.**
`lookupOk: false` with no violation means Wikimedia was unreachable or
slow. The demo is fine — picture study falls back to a captioned card by
design. Do not "fix" that, do not widen the policy hoping it helps, and do
not open a PR for it. Report it only if you were opening one anyway.

## Hard limits — do not cross these, ever

**You may modify only:**
- `site/_headers`
- `homeschool-tutor/nginx.conf`
- `scripts/synthetic_journey.mjs` (only to fix a false alarm in the check
  itself, never to make a real failure stop reporting)

**You must never modify, under any circumstances:**
- `homeschool-api/constitution/` or `homeschool-api/core/constitution.py`
- anything under `homeschool-api/core/` relating to auth, encryption,
  identity, elevation, policy, or credentials
- `homeschool-api/services/moderation.py`, `adversarial_detection.py`,
  `policy_engine.py`, or any safeguarding path
- any test, in any language, for any reason — **a failing test is a
  finding to report, never an obstacle to remove**
- `.github/workflows/**` or this prompt

If the fix requires touching anything on the forbidden list, or anything
outside the allowed list, **stop and report instead**. That is a correct
outcome, not a failure.

**You may not merge.** Open a pull request and stop. The demo is public-
facing and this repo requires human sign-off for `site/` and `demo/`
changes; that rule is not suspended because the change came from an agent.

**One PR per run.** If an open PR from a previous run already addresses
this, add a comment rather than opening another.

## Before you open a PR

1. Run `homeschool-api/tests/test_site_headers.py` — it must pass.
2. Run `bash scripts/build_pages_site.sh` — it must succeed.
3. Re-run the check against the built output and confirm the specific
   failure is gone. If you cannot verify the fix, say so in the PR body
   rather than implying you did.

## Always report, including when you fixed nothing

The human wants to know what was caught, not only what was changed. In the
PR body (or the issue, if no change was warranted) state plainly:

- what the visitor experienced
- what the evidence actually showed
- what you changed, and why that addresses it
- **what you could not verify from CI** — say it explicitly
- anything suspicious you noticed but deliberately did not touch

If the cause is outside the repository (Render config, Cloudflare settings,
DNS, credentials), open an issue naming the exact setting and the exact
value to check. Do not attempt a workaround in code for a configuration
problem — that is how a temporary patch becomes permanent and the real
cause stays hidden.
