# Evidence and reuse inventory

## Identity and freshness

Read-only `ls-remote origin HEAD refs/heads/main` and `fetch --no-tags origin main`
resolved `agnusdei-ai/bede` to
`b36daf78c98d9c5184a650da70d09cc41f1f1233` on November 12, 2026. This
isolated detached worktree uses the actual Bede repository's common Git object
database. Freshness is as of that observation, not a continuing synchronization.
The older checkout at `5970574` has dirty site files and
`demo/src/audienceDiscovery.test.ts`; none were modified, staged, or committed.
The separate Grade 8 baseline worktree at `d8d9127` is retained unchanged.

Current `AGENTS.md`, `docs/ENGINEERING_RULES.md`, LICENSE, constitutional guidance
in `CLAUDE.md`, and the curriculum design/review docs were inspected. Newer
governance remains intact: curriculum PRs require human review before merge,
merge is not release, and sample-only Pilot HOLD is not lifted.

## Existing implementation (source inspected, not deployed certification)

| Reuse | Integration boundary / gap |
| --- | --- |
| `homeschool-api/services/curriculum/models.py` | Preserve source/objective/skill IDs and campus/version/visibility. No authoritative Grade 8 outcome taxonomy was found; fixture objective IDs are explicitly sample, not replacements. |
| `services/diagnostic/skill_map.py`, `services/content_curation.py` | Reuse `sp.scatter_plots` in the fixture. Reconcile every real objective to existing skills; new skills require separate reviewed change, never rewrite mastery history. |
| `services/curriculum/rights_gate.py` | Bind exact edition/hash, retrieval time, citation and rights evidence. Verbatim requires verified public domain. `licensed` is not a way around that check. |
| `services/curriculum/workflow.py`, `persistence.py` | Reuse staging, encrypted snapshots, campus/version keys, source fingerprint checks, independent review, precommit reauthorization and append-only approved versions. No migrations here. |
| `services/curriculum/local_hybrid_index.py` | Scope, approval and rights filters precede ranking. Existing licensed-source exclusion remains. Deterministic lexical hashing is not a trained semantic embedding. |
| `citation_retriever.py`, `pedagogical_retrieval.py`, `scoped_profile.py` | Objective/evidence annotations, scoped retrieval, literal citations and insufficiency behavior need final factory adapters and affected tests, not a second index. |
| `learner_evolution.py`, `LessonVariant` | Bounded, expiring learner variants retain exact approved parent. Scores are not calibrated placement or causal efficacy evidence. |
| `services/lesson_planner.py`, `services/catalog_service.py` | Existing plans/catalogs are not an independently designed full-year curriculum. Do not copy another publisher's selection structure or teaching notes. |
| `tests/test_curriculum_{models,rights_gate,workflow,persistence,local_hybrid_index,citation_retriever,learner_evolution,scoped_profile}.py` | Retain existing denial, tamper, campus and version cases. New pure checks reuse dataclasses directly. Database/auth suites must run in the factory's configured test environment; they were not executed for this spec. |

Paths abbreviated as `services/` and `tests/` above are under `homeschool-api/`.
The pure reference checker reads the current literal phonics/literacy/composition/
language/music vocabularies without importing their database dependencies.
This mirrors the inspected `content_curation.known_skill_ids` union; the factory
must use that existing function directly in its full test environment.
`exercises_no_tracked_skill` plus a rationale permits genuine untracked outcomes,
as the current curation model already does; never invent a math skill for a poem.
The feature reader in `services/curriculum/flag.py` defaults OFF. No runtime
configuration or service state was inspected or changed.

## Current review and rights authority

`workflow._actor` requires an upstream signature-verified session, current enabled
educator/credential version, WebAuthn UV, enabled campus and membership, and an
administrator-issued reviewer grant. `review_staged_lesson` forbids author
self-review, rechecks source fingerprint, encrypts review history, creates a
separate approved version and reauthorizes before commit. Grant issuance/public
review UI is not established by this module. An identity string or model's
`is_human_reviewer` heuristic is **not authentication**.

Rights verifier names/evidence references remain assertions until independently
verified. No source or rights approval was issued here. A compatible licensed
asset needs a separately reviewed pathway for the exact use; do not mark it
public domain or relax verbatim/retrieval checks. Original content can still
contain third-party quotations and must be checked.

## Available milestone artifacts and gaps

Outer-workspace `curriculum/grade-8/` contains the baseline research, capability
inventory, rights guide/register, operating model and checks; the baseline
worktree retains its committed history. Register IDs `G8-LIT-001` and other
`G8-*` IDs must survive eventual import. Most candidates lack selected exact
asset bytes/hash or complete per-use authorization; they are **not ingestion
inputs**. Do not manufacture hashes from catalog pages. The fixture instead
uses a visibly separate `fixture-source-pairs` ID.

Outer `curriculum/grade-9/` and its audit contain a 36-week map, nine authored
weeks, original replacement biology notes, sample project, independent agent
reviews and provisional source IDs including `M01`. Preserve those IDs and
final appended dispositions; older required-human subject-review wording is
historical. None establishes a full year, source ingestion, pilot, or publication.
No separate Grade 10–12 authored outputs were found in the available curriculum
directories. Those queued milestones remain pending, not failed prerequisites.
The current task snapshot shows Grade 8 work active; later grades and the factory
and slice are queued. It does not demonstrate milestone acceptance.

Pending Grade 8 slice inputs: accepted baseline disposition, outcomes and
prerequisites, history/language choices, independently designed sequence, exact
source assets and rights, access/safety review, adult workload/capacity, actual
tool/resource configuration, and independent review evidence. Coaching-hour
allocation/prices are unresolved service assumptions, not invented entitlements.
Do not duplicate baseline education research; consume its evidence with hashes
when it becomes an approved input. Generic specification validation proceeds now.

## Automation / publication: read-only evidence

* `.github/CODEOWNERS` assigns the owner broadly and security paths explicitly.
* `.github/workflows/bede-event-driven-merge.yml` is manual-only with job
  `if: false` and an owner-requested HOLD. Dormant script logic is not an active
  merge safeguard and does not supersede curriculum human-review requirements.
* `.github/rulesets/main-branch-protection.json` is an import template, not proof
  of remotely enforced rules. Live rules, reviews, checks and settings are unknown.
  No administrative inspection or configuration change was performed.
* `deploy-demo.yml` can publish redirect stubs on matching main pushes or manual
  dispatch. `wrangler.jsonc` defines static assets under `publish/`;
  `scripts/build_pages_site.sh` assembles the site and demo. Cloudflare can publish
  on branch push per existing owner warning. Connected branches, live deployment
  settings, and deployed content were not verified.

Therefore **no push at all**, including a proposed draft branch. A passing local
check, disabled merge bot, or open PR cannot authorize publication.
