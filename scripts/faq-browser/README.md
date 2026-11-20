# FAQ browser regressions

Fast DOM/runtime parity checks: `pnpm --filter @workspace/scripts test:faq`.

Browser checks: `pnpm --filter @workspace/scripts test:faq:browser`.
They run the fast checks too, serve the real `site/` files on an ephemeral
loopback port, and exercise the actual `ProductionFrame` review component.
Start the existing Canvas / Component Preview Server workflow first.

Install Chromium once with `pnpm --filter @workspace/scripts exec playwright install chromium`,
or set `FAQ_CHROMIUM_PATH` to a compatible installed Chromium executable
(in this workspace, `/repl/tools/bin/chromium`).
Set `FAQ_REVIEW_URL` if the review is not at
`http://localhost:80/__mockup/preview/bede-streamlined/Streamlined`.
Missing browser or review server is a failure, never an automatic skip.

The six focused scenarios cover normal and reduced motion. They check actual
keyboard activation, disclosure state, focus and viewport position, native
cross-document and fragment history, same-fragment reopening without duplicate
history entries, shared URLs, review-parent navigation, and a real persisted
`pageshow` from Chromium's back/forward cache. BFCache is deliberately enabled;
the restoration assertion fails if the page was merely reloaded.

Two links are inserted only by the test to reach same-fragment and alternate-topic
paths; neither the runtime nor browser history events are mocked.

## Copy and print regressions

These run separately from navigation and need **no Canvas server**:

```sh
pnpm --filter @workspace/scripts test:faq:reader
FAQ_CHROMIUM_PATH=/repl/tools/bin/chromium pnpm --filter @workspace/scripts test:faq:reader:browser
```

Prerequisites:

- Install dependencies with `pnpm install --frozen-lockfile`.
- Chromium as above, or `pnpm --filter @workspace/scripts exec playwright install chromium`.
- Poppler's `pdftotext` on PATH (`poppler-utils` in Nix).
- A working graphical `DISPLAY` for the native print-preview Cancel check.
  Replit's desktop display works; on a headless CI host use `xvfb-run -a` before
  the browser command. Do not use kiosk printing: it bypasses Cancel.

All four cases serve the actual `site/faq/index.html`, CSS and JS over an
ephemeral loopback HTTP server (a browser-secure context). Missing browser,
display, PDF tools, or print-preview controls **fails**, never skips.

Coverage:

1. Grant actual clipboard permissions, click Copy FAQ, read the system clipboard,
   and compare every FAQ prose block/question plus 14 subject names and 42 facts,
   including initially closed sections. Confirm reading state is unchanged.
2. Deny clipboard writing in the page's actual Chromium browser context (not a
   mocked API), verify the denial, then check the visible, labeled, read-only,
   fully selected fallback and a successful retry that removes it.
3. Generate native A4 PDFs twice with `page.pdf()`. Compare all question/answer
   blocks against real PDF text and every word's coordinates against the page
   margins. Check multi-page output, no toolbar/navigation, native print events,
   and exact restoration of mixed disclosure states, topic URLs, link targets
   and history state/length.
4. Click Print FAQ in headed Chromium, wait for its real `chrome://print/` dialog
   and generated PDF, then click its native Cancel button. Repeat to catch stale
   state snapshots. No replacement of `window.print`, clipboard methods,
   `beforeprint`, `afterprint`, or media-query events.

The native dialog is a separate DevTools target; `print-preview.mjs` reaches its
shadow-DOM Cancel control because Playwright does not expose it as a normal
page. Chromium internal markup changes deliberately fail the test, rather than
silently substituting mock cancellation.

Evidence is written to `generated-artifacts/faq-reader/` (ignored by Git and
deployment): `faq-1.pdf`, `faq-2.pdf`, and `clipboard-denied.png`.
Text checks normalize case (CSS uppercase), whitespace, ligatures and hyphenation,
but require each complete source block to appear in an extraction. PDF painting
order differs from reading order around columns and page breaks, so raw, normal
and layout extractions are checked; geometric bounds are checked independently.
This covers PDF text completeness and clipping, not a pixel-perfect typography
baseline or a physical printer driver.

## Automated release gate

The portable gate is `.github/workflows/faq-reader.yml`. It runs on pull
requests, merge-queue entries, all pushes to `main`, and manual dispatch.
Pull requests deliberately have no paths filter so a required check cannot stay
pending on an unrelated change. The workflow has read-only repository
permissions, no deployment step, no credentials persisted by checkout, and a
15-minute timeout.

It installs the exact `@playwright/test` dependency and transitive packages from
`scripts/faq-browser/package-lock.json`, then installs that version's Chromium,
Poppler, Xvfb and xauth on Ubuntu 24.04. The native tests run under a real Xvfb
display, not kiosk printing. The gate rejects missing prerequisites, version
drift, any skipped tests, or an alternate Chromium binary in CI. A local
`FAQ_CHROMIUM_PATH` remains supported outside CI.

Workspace shortcut, with the existing desktop display:

```sh
FAQ_CHROMIUM_PATH=/repl/tools/bin/chromium pnpm --filter @workspace/scripts test:faq:release
```

On headless Linux, use `xvfb-run -a` before that command. The canonical Bede
repository uses npm-based applications rather than this workspace's pnpm
monorepo. Its CI therefore uses the small, isolated npm package beside the
browser tests; it does not install or replace any application's dependencies.
The runtime unit tests are portable; the separate
`scripts/faq-reader-preview.test.mjs` checks Canvas template parity only in this
workspace and still fails if its expected preview source is missing.

The workflow uploads `generated-artifacts/faq-reader/` after success **or failure**
for 14 days, including installation logs, test logs, environment versions and
`release-check.json`, plus the PDFs and screenshot when those cases reach
evidence capture. Missing uploads fail rather than being ignored. Each gate run
deletes its old PDF/screenshot outputs first so stale files cannot satisfy a
later run. These files remain ignored by Git and deployment.

See [RELEASE-CI.md](RELEASE-CI.md) before activating the workflow in the canonical
repository. Preparing this workflow does not authorize a push or publication.

## Firefox and WebKit export parity

```sh
pnpm --filter @workspace/scripts exec playwright install firefox webkit
pnpm --filter @workspace/scripts test:faq:reader:engines
```

On a supported headless Linux host, install browser system dependencies using
the pinned Playwright CLI and run the gate under `xvfb-run -a`.
`FAQ_EXPORT_ENGINES=firefox` or `webkit` selects one engine; the default runs
both. Empty, unknown, and duplicate engine selections are errors, not skips.
Outside CI only, `FAQ_FIREFOX_PATH` and `FAQ_WEBKIT_PATH` can identify a local
compatible Playwright browser binary. The isolated npm package also exposes
`npm run test:engines --prefix scripts/faq-browser`.

Each engine must pass three real-browser cases:

1. Copy the initially closed answers, paste the actual browser clipboard using
   a trusted keyboard Paste into a separate textarea, and compare every source
   block, 14 subjects, 42 facts, and the canonical URL. No Chromium-only
   clipboard permission grant or replacement clipboard implementation is used.
2. Serve the actual site at a routed, genuinely insecure HTTP origin. Verify
   `isSecureContext === false` and the browser's Clipboard API is unavailable.
   Clicking Copy must expose the complete, focused, read-only, fully selected
   manual-copy field, truthful status text, and an enabled retry control.
   This is **unavailable API coverage**, not a claim to automate a native
   permission-denial prompt. Chromium's separate test verifies an actual denial.
3. Enter actual browser print-media emulation, verify every source prose block
   and every FAQ caveat remains visible, and restore the exact mixed reading
   state twice when leaving print media. These are CSS and `matchMedia` checks,
   not native print transactions. Native print events are observed and must
   remain absent; none are dispatched by the test.

The CI workflow has separate, fail-closed Firefox and WebKit matrix jobs,
installs each pinned browser with its system dependencies, and retains each
engine's logs, screenshots, caveat-visibility JSON and coverage/versions report
under `generated-artifacts/faq-reader/<engine>/`. One engine's failure does
not cancel the other. Missing libraries, binaries, or test evidence fail.

### Coverage limits

| Check | Chromium suite | Firefox/WebKit suite |
| --- | --- | --- |
| Full native clipboard contents | Clipboard API readback | Native keyboard paste readback |
| Actual denied permission | Verified CDP-context denial | Not automated; real unavailable-context fallback instead |
| Every answer/caveat visible in print media | Native PDF plus CSS | Print-media layout and visibility only |
| Native multi-page A4 PDF and clipping | Automated, Poppler-verified | Not claimed |
| Native `beforeprint` / `afterprint` restoration | Automated PDF and headed Cancel | Not claimed by print-media emulation |
| Native dialog Cancel | Real Chromium preview, twice | Requires platform-native verification |
| Branded Safari/macOS or iOS Safari | Not applicable | Playwright WebKit is **not** branded Safari |

The bundled Playwright API restricts `page.pdf()` to Chromium. There is no
portable Firefox/WebKit equivalent of the Chromium DevTools print-preview
target and Cancel control used by this suite. A passing print-media test must
not be reported as successful native printing, PDF generation, or cancellation.
Use [NATIVE-EXPORT-CHECKLIST.md](NATIVE-EXPORT-CHECKLIST.md) on a supported real
browser/OS for those claims.

Local validation in this Replit image passed all three Firefox cases with the
downloaded Playwright Firefox binary and existing native library paths. WebKit
could not launch because its Linux distribution dependencies are missing;
its checks remain unverified here, not skipped or reported as passed.
The Ubuntu CI jobs are prepared but have not been activated or run on GitHub.
