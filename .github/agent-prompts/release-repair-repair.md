# Release repair: repair

Read `release-repair-common.md` first.

Make the smallest repair in scope, on `assignment.branch`, starting from
`revision.base_sha`. Reuse Bede's existing recovery mechanisms where they
apply (`docs/RELIABILITY.md`). Add a regression test that fails without your
fix and passes with it; the controller checks both, on the base and on your
branch. Run the repo's fast checks for what you touched before pushing.

You have at most two attempts per task in total. If you cannot fix it inside
the rules, report `blocked` rather than stretching them.

`status`: `patch_pushed` (with `branch`) or `blocked`.
