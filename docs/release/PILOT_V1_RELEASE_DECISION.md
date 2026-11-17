# Bede v1.0 production pilot release-candidate packet

**Recommendation: HOLD. Deployment is not authorized.** This packet records
the current evidence and the remaining owner decisions for a customer-
environment pilot release candidate (RC). It is neither a release nor a
customer-installation approval. A sample-only qualification is useful
evidence, but does not complete the requested customer-environment endpoint.
Real learner data remains blocked until applicable school authorization and
legal obligations are met.

The teacher-review capabilities remain bounded by the existing pilot
agreement
([VALOR_TEACHER_REVIEW_CONTRACT](../institutional/VALOR_TEACHER_REVIEW_CONTRACT.md))
and evidence checklist
([PILOT_RELEASE_EVIDENCE_CHECKLIST](../institutional/PILOT_RELEASE_EVIDENCE_CHECKLIST.md)).
This packet does not treat unrelated practice features as included.

```yaml
release:
  name: Bede
  version: "1.0"
  target: production pilot RC for customer-environment implementation
candidate:
  source_sha: null
  source_sha_reason: owner has not selected a candidate; working tree is not a candidate
  target_platform: unknown for the customer deployment; the pilot Mac is the physical acceptance target, not evidence of the server host or topology
  target_architecture: unknown; owner confirmation required
  package_digest: null
  package_status: not built
  qualification_manifest: null
gates:
  agent_review: prior read-only reviews recorded; follow-up of proposed print fix pending
  automated_qualification: not run on a selected candidate
  customer_installation: not run
  physical_mac_safari_acceptance: NOT_RUN; owner-operated
  real_learner_data: not authorized by this packet
  production_rc_ready: false
  deployment_authorized: false
decision:
  status: HOLD
  owner_approval_ref: null
```

## Current evidence

**Source and dependencies.** The reviewed PR #837 tree is
`60dff17f19cdcb9ed4f42fa55c2efaec11e7d30a`; it is not current `main` and
is not an immutable candidate selected by the owner. Current `main` was
`30c9f3231a561be626109dfd1269a122021ba840` when these states were checked.
PRs #857 and #864 were merged; #824, #851, and #865 remained open, and #862
has an explicit owner hold. PR #851 adds arm64 DMG provenance only; it does
not make the existing engineering DMG distributable. No PR was merged for
this packet. Reconcile required dependencies on a deliberate integration
tree; do not silently package the older reviewed SHA.

**Current PR checks.** The latest PR #837 browser-journey run,
`44158031812`, and sample-qualification run, `44158031588`, both target
`60dff17f19cdcb9ed4f42fa55c2efaec11e7d30a` and report
`action_required` with zero jobs. They provide no test result; no failed-job
logs exist for either run. The available record does not identify which
approval is required. The owner must authorize the exact workflow run or
provide an approved compatible route before these checks can close. The
separate browser run `44161273052` passed 36/36 checks on PR #857's
`e581b077fd171b42ffb953843eef3e362a70dd0e`, including the restart/reopen
journey on macOS 15.8.2 arm64 with Playwright 1.63.0/WebKit 26.6. It is
useful evidence about that stack and journey, not qualification of this
candidate or of real Safari.

**Agent reviews.** The `security-review` agent session
`0991951b-2452-47e8-907b-0aba3f86ef97` recommended HOLD and identified
deployment-security and operations gaps. The `code-review` agent session
`b861f920-7cf8-46f3-a452-247d42f8fa07` found that the official-record
printout omitted the proposal rationale. Both reviewed the PR #837 tree
above; neither model identity was exposed. Their reviews were read-only and
are not educator, human, counsel, school-administrator, or installed-build
certification. The proposed rationale fix is in the current working tree;
its API and frontend tests could not run because this checkout has neither
`pytest` nor `vitest`. A follow-up review of the revised committed source
remains required.

**WebKit evidence.** The controlled diagnosis run `43757437010` reported
macOS 15.8.2 arm64, Node 24.22.2, Playwright 1.56.0/WebKit 26.0, with
variants B, F, G, and I crashing 3/3. The same variants had zero crashes
in three attempts each on Playwright 1.63.0/WebKit 26.6. Product browser
run `44161273052` tested
PR #857 head `e581b077fd171b42ffb953843eef3e362a70dd0e` on the latter
Playwright/WebKit version and passed 36/36 checks, including the journey
that restarts the API during a tutor turn and reloads the child page. The
relevant journey/runtime source matched current `main` except for
`.github/audit-allowlist.json`. This narrows the known failure to the older
WebKit/Playwright stack; it does not establish real Safari or physical Mac
acceptance, and it is not evidence on a selected final candidate.

**Print finding.** The proposed fix returns the rationale from the proposal
linked by the approved teacher decision and passes it to the existing
escaped “Based on” print section. It also checks the proposal's assessment,
campus, and learner association. The targeted API and UI tests were added
but not run here. Until they run on the selected integrated candidate, the
official-record print gate is not met.

## Owner decisions required

Please answer these before selecting a candidate. Recommendations are
included to make each choice concrete, not to make it on the owner's behalf.

1. **Actual deployment target and topology:** provide the host OS, exact
   hardware/chip and architecture, and whether the teacher uses the same
   machine or a second LAN client. Available records do not establish the
   customer's actual target. Recommendation: use the simplest topology that
   satisfies the agreed pilot, and do not infer arm64 from prior runner
   evidence.
2. **Inference and data flow:** name the permitted provider, exact model,
   runtime and endpoint; specify whether any learner message, assessment
   record, or other learner data may leave the customer network; and state
   credential provisioning. Recommendation: keep educator pilot inference
   local-only with no cloud fallback unless the owner explicitly approves
   the provider and corresponding data flow. No model download or paid call
   is authorized here.
3. **Learner-data scope:** state whether the initial customer environment
   will use sample records or real learner data. The current school notice
   is sample-data scoped. Real data requires applicable school-administrator
   authorization and counsel's review of the notice; this packet cannot
   waive either.
4. **Teacher-facing language and feature scope:** confirm English-only or
   Spanish teacher screens. Recommendation: keep this RC English-only unless
   Spanish use is required by the customer. Decide whether Teacher Quiz
   Studio and model-drafted quizzes are in scope; recommendation: defer both
   because neither is in the stated agreement. Model-drafted quizzes would
   additionally require qualification against the approved local model.
5. **Number Time boundary:** Decision 40(g) permits the already-built,
   direct-entry public-demo activity only. It does not authorize tutoring
   invitations or other practice areas. Recommend deferring it from the
   teacher-only pilot; decisions 40(c)-(f) remain outside this RC and should
   be explicitly deferred, not decided by implementation.
6. **Exact workflow approvals:** after source and target are selected,
   authorize or decline the exact workflow/ref/SHA/inputs in the approval
   request below. The existing candidate run IDs target an obsolete SHA and
   must not be approved as a substitute. No workflow dispatch, package
   publication, notarization, or release/deployment workflow is authorized
   by this packet.

### Exact package and check workflow request

The available Mac build is
`.github/workflows/build-bede-operator.yml` (`workflow_dispatch`, no inputs).
For a manual run, the selected workflow ref determines `github.sha`; the
workflow packages that commit. Its package job has `packages: write`, builds
and pushes the Linux runtime images to GHCR, and the API Dockerfile downloads
faster-whisper `base` weights. The arm64 Mac job then creates an ad hoc-signed,
unnotarized engineering DMG, marks it **not for distribution**, and uploads
it with a 30-day retention. Its current provenance describes a sample-only
teacher-directed evaluation and `pilot_go: HOLD`; neither that artifact nor
the current workflow is a production customer package. PR #851 only adds the
arm64 provenance file alongside that same engineering DMG.

To use this workflow, the owner must first select the full source SHA and
target architecture, then explicitly authorize the exact
`build-bede-operator.yml` run, including model-weight download and GHCR image
publication. This approval has not been given, so no build was dispatched.
If those effects are not approved, the accountable release engineer must
propose and review a package path that avoids them; omitting the model or
substituting another runtime would not qualify the actual product.

Trusted macOS distribution is a separate workflow,
`.github/workflows/macos-trusted-distribution.yml`, and is restricted to a
successful source build on `main`. Its required inputs are
`source_run_id`, the matching full `source_sha`, and `architecture`
(`arm64` or `amd64`). It imports the configured Apple Developer ID identity,
submits the DMG to Apple's notarization service, staples and assesses it, and
uploads a 30-day artifact. This performs an external notarization submission
and requires the `mac-trusted-distribution` environment and Apple signing/
notarization credentials. The owner must separately authorize that exact
workflow/ref/run/SHA/architecture and its external effects. It cannot run
for this unmerged PR candidate, and no credentials were requested or used.

PR #837 runs `44158031812` (browser journeys) and `44158031588` (sample
qualification) are both `action_required`, have zero jobs, and target
`60dff17f19cdcb9ed4f42fa55c2efaec11e7d30a`. The available record does not
name the required approval, and these runs are not the selected candidate.
Do not approve or retry them as release evidence. After the owner selects an
integrated SHA, the qualification engineer must identify that SHA's exact
check runs and request any required GitHub approval before interpreting
results. The existing macOS runner can build arm64; the Intel runner is
`macos-15-intel`. Neither runner establishes the customer's architecture.

## Engineering and qualification blockers

Each item has an accountable role, next action, and evidence required to
close it:

| Blocker | Accountable role and next action | Closure evidence |
| --- | --- | --- |
| Candidate source and open dependencies | Owner selects the source scope; integration engineer reconciles required PRs without merging on the owner's behalf. Preserve #862's hold. | One committed, clean, full 40-character SHA with a reviewed dependency list. |
| Customer OS, architecture, topology, provider/model, and data scope | Owner supplies the choices above; release engineer records them without inference. | Approved scope record tied to the candidate. |
| Database runtime privilege | Deployment engineer separates the API's runtime database role from the Postgres bootstrap superuser and checks the actual grants. | Packaged-deployment test proves the API role has only required application/schema privileges and cannot create roles or databases. |
| Production recovery | Deployment engineer provides encrypted backup, key custody, offsite policy if required, and a destructive restore rehearsal. | Dated backup/restore evidence with measured RTO/RPO on the selected deployment. |
| Package and provenance | Release engineer finds an authorized compatible runner and an approved packaging route. The existing operator image build downloads faster-whisper `base` weights and publishes to GHCR; that path is not authorized here. | Customer-installable package, exact source and target provenance inside/alongside it where supported, SHA-256 from final bytes, and a separate verifier report. No model download or publication without separate approval. |
| Installed-build security and access | Release engineer qualifies TLS, passkey setup, teacher/campus/learner isolation, persistence, provider connectivity, health, diagnostics, and rollback on the selected topology. | Requirement-mapped results tied to exact candidate and artifact; failures resolved or explicitly left blocking. |
| Functional and language qualification | Qualification engineer runs the required teacher journeys and isolation/recovery cases, including synthetic Spanish E2E only if Spanish is approved. | Complete exact-candidate matrix and evidence manifest. Synthetic tutor results must be labeled synthetic. |
| Number Time acceptance | Qualification engineer uses temporary synthetic math attempts in an isolated test environment; must not access household data or write to existing demo progress stores. The merged #857 PR's unit/component checks and its statement that demo files were untouched are not this full acceptance matrix. Recommendation: defer Number Time from the teacher-only pilot unless the owner includes it in scope. | If included, record the full acceptance matrix, prove the test used no household database, and compare demo progress-store state before/after. Otherwise record the explicit deferral and do not package it as pilot functionality. |
| Physical Mac and Safari | Owner alone operates the pilot Mac; engineering prepares one bounded session and exact install/rollback steps. | Actual owner-recorded results. Until then every physical row remains `NOT_RUN`. |
| School data authorization and notice | School administrator supplies required authorization; counsel reviews the school notice before real learner data. | Current notice hash and required authorization/review evidence; no wording here claims those occurred. |

These are not a permanent stop list: each names the person or role who can
act and what evidence closes the gap. If a prerequisite needs a workflow
permission or runner, request the exact workflow, ref, SHA, inputs, and
approval rather than claiming delivery.

## Not reopened

#834 (ending a lesson turn when the chat screen goes away) is merged and its
regression tests remain. This packet does not claim that it changes or closes
the separate physical-browser acceptance requirement.

## Readiness decision

The evidence supports **HOLD**, not `PRODUCTION PILOT RC READY`. No final
candidate, customer platform, production configuration, installable
artifact, artifact digest, or exact-candidate qualification exists. Resolve
the owner choices, integrate only the approved scope, and complete the
evidence table before the owner makes a dated readiness decision. A future
`PRODUCTION PILOT RC READY` finding will still be distinct from
`DEPLOYMENT AUTHORIZED`; only the owner may authorize customer installation.
