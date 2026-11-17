# Release repair: triage

Read `release-repair-common.md` first.

Classify the failure in your envelope as product, harness, infrastructure or
unknown, from its evidence. Check whether an open PR or a `main` commit
already addresses it. Group related symptoms without merging distinct
causes. A known failure stays a failure.

`status`: `done` when you have a classification and a bounded reproduction
plan (put it in `observations`), or `blocked` with the exact gap.
