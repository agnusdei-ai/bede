# Local-only Grade 8 integration

## Status and service boundary

This is baseline/source research, not complete Grade 8 lessons, approved rights, a finished operating system, an activated corpus or a live offering expansion.

Standard family service is **parent-directed and Bede-orchestrated**, with optional human coaching subject to separately approved staffing/terms. Adults retain consequential decisions. Complete Grade 8 end to end before separately approving Grades9→10→11→12. The Grade 9 draft remains provisional and is excluded from this commit.

Before full-year authoring, require the proprietary production specification, development-only factory, three-lesson Grade 8 verification slice and explicit independent human slice review. Rights, academic/access/safety, implementation, pilot/data, publication and activation approvals remain distinct and version-bound. No default model training.

## Freshness and checkout handling

The earlier baseline inspected feature HEAD `597057406489880a1abe3fb57ac1beaafc48e776`. Its source hashes and15 sample check names are preserved in `source-evidence.json`; they are not reinterpreted as current-main tests.

For this integration, a **read-only** remote heads query resolved `agnusdei-ai/bede` main to `e0e57d1bd45d83c0b422410c58395d9a9b0b3f7b`. That exact object was fetched without writing FETCH_HEAD or branch refs, and a separate detached local worktree was created from it:

`/home/runner/workspace/release-checkout/bede-grade8-local`

This is an actual worktree of the same Bede Git repository, sharing its object database with `/home/runner/workspace/release-checkout/bede`. The original dirty feature checkout remains untouched. **Detached HEAD means no local or remote branch was created.** The local commit remains accessible through this retained worktree/commit SHA; it is not on GitHub.

No push, GitHub API mutation, PR, merge, deployment or publication is authorized or performed. Read-only freshness checks do not grant release permission. Hooks/signing are disabled only on the local commit command to avoid automation; repository policies/configuration are not rewritten.

## Historical source drift

Seven files hashed in the earlier baseline differ at the integration base:

- `homeschool-api/services/curriculum/models.py`
- `homeschool-api/services/curriculum/citation_retriever.py`
- `homeschool-api/services/student_deletion.py`
- `homeschool-api/routers/practice.py`
- `homeschool-api/services/practice/store.py`
- `homeschool-api/services/practice/extract.py`
- `homeschool-api/core/deps.py`

They are **not changed or freshly behavior-audited** in this documentation task. Inventory conclusions must be rechecked against the implementation milestone's authorized exact head. In particular, do not use the historical auth/deletion/processing findings as a current security verdict or permission to weaken a gate.

## Commit scope and exclusions

Allowlist: the eight Grade 8 baseline Markdown documents, this integration note, source register/template, historical source evidence and `validate.py`—13 small text files under `curriculum/grade-8/`.

The repository uses sparse checkout. Staging uses command-scoped `git add --sparse` with that explicit13-file allowlist; it does not expand/disable sparse-checkout policy or stage unrelated paths.

Excluded: Grade 9 draft; unchanged `homeschool-api/data/catalog/year8.json`; runtime code/config/flags; dependencies; real learner data; secrets; copied external books/curriculum text/media; generated PDF/HTML/ZIP/images; authoring-workspace-specific verifier/export tooling.

Checks: portable schema/status/rights/link/source-evidence/secret-pattern checks; manual staged rights/privacy/scope review; `git diff --cached --check`; exact commit file inventory; clean target staging/worktree; byte-for-byte preservation of the original unrelated diff. No full upstream pytest, database, UI or deployed test is claimed.

## Remaining work

Gate 0 owner acceptance; Grade 8 standards/history/language choices; authenticated source/academic/access/safety approvals; specification/factory/reviewed slice; whole-year design/cost/authoring; implementation testing; separately authorized pilot/evaluation and completion review. Existing downstream tasks cover these; this local commit does not start or close them.
