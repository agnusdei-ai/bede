# Upload content check: live verification

What was observed on the deployed public demo for the picture check added in
#814 (`services/content_screen.py`). A merge and a green deploy are not
evidence that live behaviour works; these runs are. Each run is
`.github/workflows/live-upload-check.yml`, sending four sample pictures
drawn by `homeschool-api/scripts/live_upload_check_probe.py`. No harmful
imagery is ever sent; the self-harm and sexual-content paths are tested with
mocked verdicts only (`tests/test_content_screen.py`,
`tests/test_safeguarding_alerts.py`).

The verdict is an AI model's judgement (OpenAI on the demo), so a result can
differ from run to run. Record every run, including failures.

## Deployed commit

| Deployment | Commit | Status |
|---|---|---|
| Render `bede-demo-api`, deployment 7728006692 | `b36daf78` (#814) | success, 2026-11-12 03:59 UTC |
| Render `bede-demo-api`, deployment 7787856693 | `cd66cd58` (#818: the probe and a dnspython patch; no change to the check) | success, 2026-11-14 12:57 UTC |

Both runs below hit `cd66cd58`, whose content check is #814's unchanged.

## Runs

### Run 1: 43598474404, 2026-11-14 13:11 UTC, probe at `cd66cd58`

| Check | Result | Observed |
|---|---|---|
| Worksheet passes the check and is read | pass | 200, 1 section read |
| Game screen upload refused before reading | **fail** | 200: the checker passed the game screen and it was read |
| Lesson drawing reaches the tutor | not tested | 422: the probe's own request was invalid (`grade_stage` sent as `core_mastery`) |
| Game screen in a lesson gets the gentle refusal | not tested | 422, same probe defect |

### Run 2: 43598712148, 2026-11-14 13:14 UTC, probe at `f88cdee9` (request fixed)

| Check | Result | Observed |
|---|---|---|
| Worksheet passes the check and is read | pass | 200, 1 section read |
| Game screen upload refused before reading | pass | 422 "This upload doesn't look like schoolwork. Upload quizzes, worksheets, tests or book pages." |
| Lesson drawing reaches the tutor | pass | 200, Bede talked about the tree drawing |
| Game screen in a lesson gets the gentle refusal | pass | 200 "Bede can only look at pictures that are part of your lesson." |

## Findings

1. **The same game screen was accepted once and refused once.** The check
   called the model with no `temperature`, so on OpenAI it ran at the default
   and its verdict could vary. The miss was in the "not schoolwork" category,
   not a safety category, but the same cause could affect any category. Fixed
   by sending `temperature=0` (safe on every client the check uses; Anthropic
   gets it through `_kwargs_for`). This needs a re-run once deployed.
2. **The probe's first chat request was invalid.** Fixed, and
   `tests/test_live_upload_probe.py` now checks both of its request bodies
   against the API's own models.

## Still to do

- Re-run after the `temperature=0` fix deploys, and repeat the game-screen
  check several times to see whether it is consistent.
- The real-iPhone print check is separate: `docs/release/IPHONE_PRINT_CHECK.md`.
