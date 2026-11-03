# Change Management Policy

**DRAFT for owner approval. Not in effect.** Sections marked
**[OWNER DECISION]** must be decided before approval. This policy must
describe what actually happens; if practice differs, change the practice or
the policy before the observation period, never neither.

Owner: the designated individual in `docs/INFORMATION_SECURITY_POLICY.md` §2.
Review: at least annually, and after any change to how code reaches `main`.

## 1. Scope

Every change to the source repository `agnusdei-ai/bede`, its CI workflows,
and the configuration of the in-scope services: the public demo (Render), the
site and license server (Cloudflare), and the release pipeline for installers.

## 2. How a change is made today

1. Every change is made on a branch and proposed as a pull request against
   `main`. Direct pushes that rewrite `main` are blocked by the "protect main"
   ruleset, which also blocks deleting the branch.
2. CI runs on the pull request: backend and frontend regression tests, CodeQL,
   the dependency audit, the PR security gate, and the qualification suites
   that apply to the files changed.
3. Changes under `site/` or `demo/` are merged only after the owner's explicit
   sign-off (`CLAUDE.md`, "Carve-out for the public-facing demo/marketing
   pages").
4. Changes to authentication, passkeys, consent, learner data, campus
   isolation or authorization require a focused review of that trust boundary
   (`docs/ENGINEERING_RULES.md` rule 7). Curriculum changes under epic #685
   require a human review and are never auto-merged.
5. Other changes may be merged by the author, including the coding agent,
   once CI is green (`CLAUDE.md`, "Standing Workflow: Root-Cause Fixes").
6. After merge, `production-regression.yml`, `site-headers-live.yml` and the
   demo watchdog run against `main`.

## 3. Approval rule **[OWNER DECISION]**

The current model (§2.5) lets the author of a change approve it. Choose one:

- **A.** Every change to `main` needs approval from a person other than its
  author, enforced by the ruleset (required review, plus required status
  checks).
- **B.** Changes touching the trust boundaries in §2.4, CI workflows, release
  pipeline or production configuration need a human approval enforced by the
  ruleset. Other changes keep the current model, recorded as an exception in
  `docs/audit-readiness/exceptions.md` with its compensating controls.
- **C.** Keep the current model for every change, recorded as an exception.

Whichever is chosen, the ruleset must enforce it. A rule that only lives in a
document is not a control.

## 4. Emergency changes

An emergency change (an active incident, or a vulnerability being exploited)
may skip normal approval only if:

- the reason is recorded in the pull request at the time;
- a person other than the author reviews it within **[OWNER DECISION: 2]**
  business days of merge;
- it is listed in the incident record when there is one
  (`docs/INCIDENT_RESPONSE.md`).

## 5. Production configuration

Changes made in a provider dashboard (Render environment variables,
Cloudflare settings, DNS, GitHub settings) are not visible in git. Record each
one in **[OWNER DECISION: location, for example a change log issue]** with
the date, what changed, why, and who made it.

## 6. Evidence an assessor will sample

- The pull request, its CI results at the merged commit, and its approvals.
- The ruleset configuration over the period.
- The production configuration change log.
- Emergency-change records and their follow-up reviews.
