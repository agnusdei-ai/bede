# The WebKit reload crash: status and release requirement

**Status: release qualification pinned to WebKit 26.6 (owner decision,
2026-11-15). The physical Apple-device sign-off is still required before any
claim that Apple devices are supported.** Tracked as release-repair cycle `webkit-1`, task
`t001-webkit-original-page-reload-crash`
(`config/release-repair.json`).

## The standard

Bede must work reliably in Safari and in its WKWebView-based app. Asking
families to switch browsers is not our mitigation. The fix prevents the
family-facing crash. It never makes the test pass by avoiding the affected
engine or by removing the step that triggers it.

## What is observed, and what is still a hypothesis

**Observed** (macOS 15 runners, Playwright 1.56.0 with its bundled WebKit 26.0,
build 2215; runs 43750343851 and 43751428905):

- the macOS desktop journey's child page crashes on `page.reload()` after the
  API restart, with a release assertion in
  `WebCore::Navigation::initializeForNewWindow`;
- on that page, `navigation.currentEntry` reports URL `/` while the page is on
  `/session` from sign-in onward, and is `null` after the page's first reload;
- the parent WebKit page shows the same stale record, is reloaded once, and
  does not crash; Chromium's record matches real history throughout.

**Isolated in Playwright's WebKit** (run 43757437010, candidate `f59a83af`,
macOS 15.8.2 arm64, Node 24.22.2; three runs per variant, an initial screen):
WebKit 26.0's Navigation API does not record `history.pushState`, a reload
then leaves `currentEntry` null, and a second reload crashes.
`scripts/qualification/browser_journeys/webkit_nav_repro.cjs`, run by the
`minimal` job of `.github/workflows/webkit-reload-diagnosis.yml`, shows it on a
page independent of Bede:

| Variant | Playwright 1.56.0 (WebKit 26.0, build 2215) | Playwright 1.63.0 (WebKit 26.6, build 2359) |
|---|---|---|
| A no `pushState`, 2 reloads | 0/3 | 0/3 |
| B `pushState`, 2 reloads | **3/3 crashed** | 0/3 |
| C `pushState`, 1 reload | 0/3 | 0/3 |
| D `replaceState`, 2 reloads | 0/3 | 0/3 |
| E real navigation instead of `pushState` | 0/3 | 0/3 |
| F `pushState`, 3 reloads | **3/3 crashed** | 0/3 |
| G repair after the first reload | **3/3 crashed** | 0/3 |
| H `pushState`, then an immediate real navigation | 0/3 | 0/3 |
| I `pushState`, then `navigation.reload()` | **3/3 crashed** | 0/3 |

Chromium (141, 153) and Firefox (142, 155) crashed in no variant. Bede's own
journey crashed on WebKit 26.0 with WebKit as child 1 and as child 3, so the
slot path is not the cause.

**Not equivalent:** a Playwright WebKit build is not a Safari release. Every
result records the Playwright version, the bundled WebKit build revision, the
operating system and, for physical checks, the Safari and iPadOS versions.

## Acceptance criteria (owner, 2026-11-15)

| Check | Evidence required |
|---|---|
| Reproduce the defect | The original flow fails under the same environment used to evaluate the mitigation; otherwise a passing variant is inconclusive. |
| Compare variants | Every run, crash, timeout, navigation failure and unexpected reload is recorded against an exact commit. Three runs per variant are an initial screen, not proof of crash-free operation. |
| Preserve child progress | Navigation, reload, backgrounding and reopening do not silently lose completed work, duplicate submissions, or resume the wrong learner. |
| Verify routing behavior | Sign-in, lesson, practice, sign-out, refresh, direct entry, and browser back/forward where supported. |
| Bound startup repair | At most one repair attempt for the defined failure condition; no reload loop, no bypass of authentication, no lost unsaved work. Another reload is not assumed to repair a reload-related defect. |
| Cover parent journeys | Tested now as well. Keeping normal history for parents depends on demonstrated behavior, not on the absence of a child-flow failure. |
| Test Apple delivery modes | Real-device Safari and the installed WKWebView app observed separately, plus the Home Screen web app if Bede supports it. |
| Verify the release candidate | The failing sequence and the essential journeys repeated on the final integrated commit, not only the isolated reproduction. |

**The physical-device check is a required sign-off** for claiming the defect
resolved on Apple devices, not an optional checklist row.

**Release wording:** "no crashes observed in the specified test matrix", with
the matrix and run counts attached. "No family can ever see a crash" is the
engineering goal, not something these runs can prove.

## Choosing the mitigation

The smallest mitigation that removes the reproduced failure while preserving
progress, authentication and expected navigation. In-memory routing, real
document navigation and a bounded startup repair may each address different
conditions; they are not combined without evidence, so that it stays clear
which change fixed the defect.

## Decision: the release qualification pin (owner, 2026-11-15)

Release qualification pins **Playwright 1.63.0**, whose bundled engines are
WebKit 26.6 (build 2359), Chromium 153.0.8010.12 and Firefox 155.0: the most
recent builds with recorded evidence on Bede's reload path. Every workflow that
qualifies a release uses that one version, and
`homeschool-api/tests/test_playwright_pin.py` fails if any of them drifts. The
`minimal` diagnosis job keeps 1.56.0 beside it, so the reproduction of the
26.0 defect stays on record.

What the pin does and does not cover:

- It makes the gate represent a WebKit build in which this defect does not
  occur. It changes nothing in Bede.
- It does not establish which Safari or iPadOS releases carry the defect.
  Families on such a release are not protected by the pin. Variant E (a real
  document navigation at the sign-in hop) remains the candidate product
  mitigation if the physical check finds an affected release in use.
- The physical-device sign-off above is unchanged.
