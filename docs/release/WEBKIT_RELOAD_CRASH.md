# The WebKit reload crash: status and release requirement

**Status: open. Release-blocking for any claim that Apple devices are
supported.** Tracked as release-repair cycle `webkit-1`, task
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

**Hypothesis** (not yet isolated): WebKit's Navigation API does not record
`history.pushState`; a reload then leaves `currentEntry` null; a second reload
crashes. `scripts/qualification/browser_journeys/webkit_nav_repro.cjs`, run by
the `minimal` job of `.github/workflows/webkit-reload-diagnosis.yml`, tests this
on a page independent of Bede, under each recorded Playwright/WebKit build.
Variants A, E, G, H and I are **candidate** mitigations until that run shows
otherwise.

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
