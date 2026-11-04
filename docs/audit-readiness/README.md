# Audit readiness: SOC 2 and AIUC-1

**Status: readiness work in progress. No assessment has started, and nothing
here is an audit opinion, a certification, or a legal conclusion.** These
documents get Bede ready for an independent assessor. Whether a control is
adequate is the assessor's judgment, and whether a privacy obligation is met
is counsel's.

Approved so far (owner, 2026-11-03): scope definition, current-state
verification, policy drafts, and assessor selection. Not approved by this
work: changes to branch rules, merges, closing pull requests, or any public
claim about an assessment. Each of those needs its own explicit approval.

## Three separate goals

| Goal | What it establishes | What it does not establish |
|---|---|---|
| SOC 2 examination | A CPA firm's opinion on the controls of a defined system, for the trust services categories chosen | That every feature is secure, every teaching answer is right, or every legal duty is met |
| AIUC-1 certification | AI-specific assurance, including recurring technical testing of the AI system | A substitute for SOC 2, or proof that Bede teaches well |
| Children's privacy compliance | That obligations for collecting, using, protecting and deleting children's information are met | Anything that either assurance above establishes on its own |

A Type 1 report looks at controls on one date. A Type 2 report also looks at
whether they operated over a period, so a newly written policy or a newly
enabled control cannot show operating history by itself.

## 1. Proposed system boundary (draft for the assessor)

The assessor confirms the final boundary. This is the starting proposal.

| Component | Proposed | Reason |
|---|---|---|
| Public demo (`bede-demo-api` and its database on Render) | In scope | The operator runs it and it processes visitor and child-entered data |
| Static site and demo assets (Cloudflare Worker for `agnusdei.ai`) | In scope | The operator runs it; security headers are part of the control set |
| License server (Cloudflare Worker and D1) | In scope if live during the period | It holds customer and licence records |
| Source repository, CI and release pipeline (GitHub, Actions, installer builds) | In scope | It produces what families and schools install, so change management applies here |
| AI and email providers (OpenAI, Mistral, Anthropic, Resend) | Subservice organizations | Covered through vendor management (carve-out method), not tested directly |
| Hosting providers (Render, Cloudflare, GitHub) | Subservice organizations | Same |
| A family's self-hosted server | Out of scope | Runs on the family's own hardware and is operated by the family; no data reaches the operator. The installer and update path stays in scope through the release pipeline |
| School pilot deployments | Open question | Depends on who operates the machine and holds the data. Decide with the assessor and counsel before the period starts |

Trust services categories to propose: Security (required), Confidentiality,
and Availability for the demo and license server. Privacy and Processing
Integrity are options to discuss with the assessor.

## 2. Current-state evidence (verified 2026-11-03)

Main was at `13677032`. Each row says what was checked and how. Re-check each
row before relying on it; this is a dated snapshot, not a live status.

| ID | Area | What was found | How it was checked |
|---|---|---|---|
| E1 | Change control | The `main` ruleset blocks branch deletion and force-pushes. It has no required review, no required status checks, and no bypass actors | GitHub rulesets API, ruleset "protect main" |
| E2 | Change control | The owner closed issue #709 (required checks) as not planned. `docs/ENGINEERING_RULES.md` records this and says not to require more branch-protection configuration | Read `docs/ENGINEERING_RULES.md` on main |
| E3 | Change control | `CLAUDE.md`'s standing workflow lets the coding agent merge its own pull requests, except changes under `site/` and `demo/`, which need owner sign-off | Read `CLAUDE.md` on main |
| E4 | Change control | `bede-event-driven-merge.yml` is paused (`if: false`, owner hold since 2026-10-15) | Read the workflow on main |
| E5 | Security fixes | #735 (voice fail-closed): fix is on main in `routers/voice.py` (`_require_household_biometric_scope`). #765 (pairing revocation): the PR's patch is already on main. #768 (unreadable PDF objects): fix is on main in `services/practice/upload_safety.py`. All three PRs are still open | Applied each PR's diff against main and compared the changed code |
| E6 | Security fixes | #771 (CodeQL findings) is not on main. Main still has a `Math.random` fallback for session ids in `homeschool-tutor/src/store/sessionStore.ts` and the old email regex in `license-server/src/routes/trial.ts`. The PR conflicts with main | Same method, plus reading both files |
| E7 | Vulnerability alerts | Open CodeQL, Dependabot and secret-scanning alert counts could not be read from this session (HTTP 403). The owner needs to export them | GitHub API |
| E8 | Policies | Present: Information Security (`docs/INFORMATION_SECURITY_POLICY.md`, demo-scoped, last reviewed 2026-08-04), Incident Response, Retention, Data Classification, and the application authorization table (`docs/AUTHORIZATION_POLICY.md`). Drafted with this work: access control, change management, vendor management, risk assessment, business continuity (`policies/`) | File inventory |
| E9 | Vendors | `docs/VENDOR_DATA_FLOW.md` and the security policy's §5 describe each data flow. No per-vendor assessment is on file (COPPA checklist C-11 is `EXTERNAL`) | Read both documents |
| E10 | Independent testing | The environment pentest log (`docs/environment-pentests/README.md`) has no findings. The in-house adversarial probe last ran on 2026-07-17. No outside test has happened | File inventory |
| E11 | Recovery | `production-regression.yml` runs `make db-backup` then `make db-restore` and checks that the API comes back healthy with the data present. It passed on main after #777 | Read the workflow; run results on `89aa2c61` |
| E12 | Incident handling | One recorded incident: `docs/incidents/2026-08-04-demo-outage.md`. No tabletop exercise is recorded | File inventory |
| E13 | AI accuracy | No systematic measurement of factual accuracy across subjects. The quiz drafter cross-checks its own answers; the Grade 1-8 mathematics lifecycle tests use a model stub and say so | Code and test review |
| E14 | Access | The security policy's §6 says one individual holds production access. No access review record exists | Read the policy |

## 3. Exceptions need more than an owner

A documented risk is not the same as one an assessor accepts. For every
control that will not be fully in place, record all of the following in
`docs/audit-readiness/exceptions.md` (create it with the first entry):

- The control and the system it affects.
- Why it is not fully in place.
- Compensating controls, and the evidence that they operate.
- Residual risk, in a sentence.
- The accountable owner.
- A review date.
- The event that would trigger remediation.

Candidates today: optional parent MFA on self-hosted installs, per-process
rate limiting and anomaly detection, advisory voice checks, and change
control (E1 to E4) if the owner keeps the current merge model.

## 4. Work packages

| Package | Deliverable | Done when |
|---|---|---|
| Scope and assessor | System boundary, data-flow inventory, chosen categories, assessor proposal | The assessor confirms what is in, what is out, and what evidence is required |
| Change control | A decided merge model, restricted bypass, emergency-change procedure | A production change can be traced from request through testing and approval to deployment |
| Security fixes | Refreshed issue list; independently tested fixes | Each finding meets agreed closure criteria, or has an exception record |
| Governance and vendors | Approved policies, assigned responsibilities, vendor assessments | Documents match how the company actually operates, with records to show it |
| Children's privacy | Counsel review of real data flows; refreshed COPPA checklist | Notice, consent or school authorization, retention, deletion and vendor duties are addressed |
| AI assurance | Harm-to-control map; agreed accuracy and safety evaluation plan | The configurations families and schools actually use are tested against criteria set in advance |
| Operating evidence | Access reviews, incident exercise, restore results, change samples | Evidence shows the controls operating over the agreed period |

Both assessments can run together. Ask a prospective assessor to scope SOC 2
and AIUC-1 at the same time, before any testing is commissioned, so the tests
produce evidence both engagements accept. See `ASSESSOR_SELECTION.md`.

## 5. Decisions only the owner can make

1. **Change control (E1 to E4).** SOC 2's change-management criterion expects
   changes to be approved by someone other than the author, and the assessor
   samples merged changes to check it. The current model lets the coding
   agent author and merge. Options: require a human approval on `main`; keep
   the current model and record it as an exception with compensating
   controls; or a middle path, such as human approval only for the trust
   boundaries `docs/ENGINEERING_RULES.md` rule 7 already names. This needs a
   decision before the observation period starts, because the period
   measures whatever model is in place.
2. **The three superseded security PRs (E5).** #735, #765 and #768 can be
   closed with a note that their fixes are on main. Closing them needs your
   approval.
3. **#771 (E6).** It needs a rebase onto main and a review before it can
   merge.
4. **School pilot boundary.** Decide who operates a school's machine during
   the observation period.

## 6. Public wording until an engagement is complete

Do not use "SOC 2 certified", "audit passed", "AIUC-1 certified" or
"independently verified" anywhere a customer can read it. SOC 2 is an
attestation, not a certification. Once an engagement has actually started,
this sentence is accurate:

> We are preparing Bede for independent security and AI assurance
> assessments. Those assessments are not yet complete.

## Files in this folder

- `README.md`: this file.
- `ASSESSOR_SELECTION.md`: what to ask a prospective assessor.
- `policies/`: draft policies. Each is marked draft until the owner approves
  it, and each must describe how the company really operates.
- Children's privacy uses `docs/COPPA_READINESS_CHECKLIST.md` (refreshed
  against main on 2026-11-03), `docs/PARENTAL_CONSENT.md` and
  `docs/SCHOOL_DATA_AUTHORIZATION.md`.
