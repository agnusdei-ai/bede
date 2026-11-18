# Native FAQ export verification

This checklist addresses native export behavior not established by the
Firefox/WebKit automated print-media tests. It is **not a completed test report**.
Do not publish or push changes to obtain a test environment without approval.
Use the owner-approved staging build of the actual static FAQ.

## Record the environment

- Browser brand and full version, OS and version, device, and build/revision.
- State whether this is branded Firefox, macOS Safari, or iOS/iPadOS Safari.
  Playwright's WebKit engine does not count as branded Safari.
- Whether Clipboard API access is available, permitted, unavailable, or denied.
  Do not infer denied-permission coverage from an insecure-origin test.
- Screenshot/evidence locations, result for each check, and explicit limitations.

## Complete copy and fallback

1. Start with one topic open and the curriculum/other topics closed. Record the
   topic URL and which disclosures are open.
2. Click **Copy FAQ**, paste into an external plain-text editor, and compare the
   complete answers to the actual source FAQ, including all 14 curriculum
   subjects, 42 facts, learning goals, limitations/caveats, and the canonical
   URL. Confirm no question or initially closed answer is missing.
3. Verify the reader did not navigate or change disclosure state.
4. Where the actual browser/OS exposes a clipboard denial control, deny access
   and retry. Record the real control used and permission state. Do not replace
   `navigator.clipboard`, its methods, or permission APIs in developer tools.
5. If copying is genuinely unavailable/denied, verify the **Complete FAQ text**
   field is visible, read-only, focused, fully selected and contains the same
   complete text. Copy manually using the platform's native copy control.
   Automatic success must not be announced on this path.
6. Restore real access if supported and retry. Verify success removes the
   fallback field and leaves the reader controls enabled.

## Actual print, cancellation and PDF

1. Restore mixed disclosure states and note the current topic URL.
2. Click **Print FAQ**, not a mocked print command. Verify the actual browser/OS
   preview contains the full FAQ, including closed answers and all caveats.
   Controls, navigation and preview-only illustrations must not print.
3. Use the native **Cancel** control. Check that the same disclosures, topic
   URL and links remain unchanged and the reader buttons work. Repeat.
4. Repeat with a different initial disclosure combination to catch stale
   snapshots. Record whether native `beforeprint`/`afterprint` occurred if
   observable; CSS print-media events alone are not equivalent.
5. Use the native Save as PDF/OS PDF control, when supported. Inspect the first,
   middle and last pages, complete paragraph retention, page boundaries and
   clipping. Compare extracted full source blocks using genuine raw/normal/layout
   text extraction orders; do not replace completeness with unordered word hits.
6. After saving, verify reader state restoration again.
7. On iPhone/iPad record the platform print/share sheet behavior separately.
   Desktop Safari results do not establish iOS selection, copying or AirPrint
   behavior. No physical printer/driver compatibility is implied by PDF checks.

## Reporting

Mark each item **passed**, **failed**, **blocked**, or **not supported on this
platform**, with evidence. Never convert a blocked/unsupported item to passed
or substitute synthetic print events, a stubbed clipboard, or a Chromium PDF.
Keep failures and native screenshots/PDFs in the release evidence, outside Git.
