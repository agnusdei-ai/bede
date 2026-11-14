# Real-iPhone print check

**Status: NOT OBSERVED.** This is a physical-device check. It passes only
when someone has printed on a real iPhone and recorded what they saw below.
Chromium runs, unit tests and a merge are not evidence for it.

What it checks: that a quiz and its answer key print correctly from Safari on
an iPhone, through the app's own print path (`utils/printDocument.ts`, the same
file in `demo/src/printDocument.ts`). See `docs/PRACTICE_COACH.md`, "Printing".

## What to compare against

A reference copy, rendered by Chromium from the real `buildPrintHtml` with a
fixed sample quiz of eight questions (four with pictures: a fraction bar, a
clock, a number line, a dot array), US Letter:

- page 1: title, Name and Date lines, questions 1-3
- page 2: questions 4-8
- page 3: "Answer key" heading, questions 1-4 with answers
- page 4: questions 5-8 with answers

The reference PDF is not committed (a generated binary). Rebuild it by
bundling `buildPrintHtml` and `diagramMarkup` with esbuild and printing the
result with Playwright's `page.pdf`. Your iPhone quiz will have different
questions, so compare the layout, not the words.

## Steps

Use the public demo, the route a phone can reach without a local install.

1. On the iPhone, open Safari and go to the demo. Start a session (any first
   name, any grade).
2. Open **Practice Coach**, choose the **Make a quiz or exam** tab, and set
   Subject Mathematics, Grade 2, Type Quick check, Questions 8. In **What to
   cover** enter: `adding to 20, shaded fractions of a bar, telling time to
   the half hour, points on a number line`. If a box naming the AI provider
   is shown, tick it. Then tap **Draft quiz**.
3. When the draft appears, tap **Print quiz**. The iOS print sheet should open
   on that tap, not after a second tap.
4. In the print sheet, look at the preview pages, then print to a real printer
   if one is available.
5. Back in the app, tap **Print answer key** and repeat.
6. From the print sheet, tap Share, then **Save to Files**, and open the saved
   PDF from Files.
7. Repeat steps 3-6 with the phone turned sideways.

## Expected result

Record each line as seen, not seen, or not tried.

| # | Expected | Observed |
|---|---|---|
| 1 | The print sheet opens on the first tap of Print | not yet observed |
| 2 | Only the quiz prints: no app header, chat, buttons or menus | not yet observed |
| 3 | Title, then Name and Date lines, on the first page of the student copy | not yet observed |
| 4 | Choices lettered A) B) C); open questions have three answer lines | not yet observed |
| 5 | No question, choice list or picture is split across two pages | not yet observed |
| 6 | Pictures print in full; every number on them is readable at arm's length | not yet observed |
| 7 | Question text looks like ordinary 12 pt body text, not shrunk to fit | not yet observed |
| 8 | The answer key prints separately, headed "...: Answer key", with each answer in bold under its question | not yet observed |
| 9 | Save to Files gives a PDF with the same pages as the preview | not yet observed |
| 10 | After closing the print sheet, the app looks and works as before | not yet observed |
| 11 | Sideways: same pages as upright (the print layout does not follow the screen) | not yet observed |

## Record

| Field | Value |
|---|---|
| Date | |
| iPhone model | |
| iOS version | |
| Demo frontend commit (Cloudflare deployment record) | |
| Paper size | |
| Printer, or Save to Files only | |
| Result | NOT OBSERVED |
| Notes | |

If any line fails, keep the saved PDF and a screenshot of the print preview.
Those show whether the problem is the page Bede built or the way iOS printed
it.
