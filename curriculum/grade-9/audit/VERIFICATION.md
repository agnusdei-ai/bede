# Verification and local-only integration

## Scope

The source audit targets `agnusdei-ai/bede` at read-only verified main revision `b36daf78c98d9c5184a650da70d09cc41f1f1233`, November 12, 2026. Source code inspection is not live-deployment evidence. Existing source reviews remain attributed to their actual reviewing runs.

## Reproduction

From the Bede repository root:

```sh
python3 -B curriculum/grade-9/audit/build_register.py
python3 -B curriculum/grade-9/audit/verify_audit.py --repo .
python3 -B curriculum/grade-9/validate.py
python3 -B curriculum/grade-9/review_gate.py
python3 -B -m unittest discover -s curriculum/grade-9 -p 'test_review_gate.py'
git diff --check
git diff --cached --check
```

The audit verifier checks complete per-use records, unique IDs, no approvals/training/activation, local audit links, current source hashes and eight mock pure-model controls. It blocks sockets and imports no application/database startup. The package validator checks 36 mapped weeks, 216 subject rows, nine authored weeks, schedules/credit arithmetic, 18 investigation slots and 13 teaching-code tests. The separate review gate checks current report/source hashes, not legal rights or learner outcomes. Its unit suite has 13 tests.

No upstream pytest, database, authenticated service, browser app journey, real student-data, physical lab or deployment suite was executed. This docs-only audit does not modify application behavior. Any prior export claims in the legacy VERIFICATION document belong to prior runs, not this audit.

**Historical audit run:** 61 source records and eight mock pure-model controls passed; the package validator, all 13 teaching-code tests, all 13 evidence-gate tests and the five-subject current-hash gate passed at that time. [Source hashes and named controls](SOURCE-CHECKS.json) retain the inspected source evidence. The terminology revision changes source/report bytes and invalidates affected current-hash approvals; this paragraph is not a claim of current gate passage. The first integration check found a legacy relative policy link; navigation was corrected without changing reviewed instruction or gate rules, and the package check then passed.

`node --check curriculum/grade-9/export.mjs` passed. The audit exporter rendered self-contained HTML and tagged PDF with external requests blocked, checked internal anchors and 390px width, and produced a cover screenshot that was visually inspected. This is document-rendering evidence, not assistive-technology or application testing. The full historical curriculum-book exporter was syntax-checked, not re-rendered in this audit.

**Whitespace exception:** plain `git diff --check` passed on the worktree. The staged import's `git diff --cached --check` returned 2 for 15 existing files with one blank line at EOF; no trailing-space or conflict-marker finding occurred. These existing bytes are deliberately preserved, including hash-bound reviewed instruction/project files. This is a recorded cosmetic import warning, not a clean staged whitespace result; no review hash or acceptance rule was rewritten to hide it.

## Commit safety and retention

The original checkout `release-checkout/bede` contains unrelated demo/site edits on `feat/audience-discovery-evidence`. It is preserved; no reset, stash, revert or broad staging is used. The new worktree `release-checkout/bede-grade9-audit` is detached HEAD, sharing the intended Bede Git object database. There is no new branch or remote write.

Inspect effective Git hooks, attributes and signing before commit; use command-scoped hooks disabled and signing disabled for this local-only documentation commit. Stage only the exact file names in `LOCAL-FILES.txt`, all under `curriculum/grade-9/`. Existing reviewed source files are copied unchanged except navigational/export portability changes outside the review hash scope. No archive, remote textbook, generated PDF/HTML or unrelated site file is committed.

After commit, verify the exact SHA, parent, included path set, clean detached worktree and unchanged original worktree/index hashes. A small incremental Git bundle under ignored generated output retains the local commit; restoration requires the base revision named above. It is not pushed. The downloadable package also contains the actual curriculum files and a commit receipt. Keep the worktree/bundle until the owner has retained it. The release-checkout directory is ignored by the outer workspace repository, so its nested commit is **not** part of the outer task merge; downloadable delivery is important.

The final handoff records actual command outcomes and SHA. Nothing in this audit grants permission to push, publish, activate a corpus or run a pilot.
