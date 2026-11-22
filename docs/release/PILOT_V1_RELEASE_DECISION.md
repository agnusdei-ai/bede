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
  source_sha: 2eeed597fd90feea0e4592ec77fd79a6be535c00
  source_sha_reason: main at 2026-11-22, proposed for acceptance; not owner-selected until owner_approval_ref is set
  target_platform: macOS on the owner's 24 GB Apple Silicon MacBook Pro, same-machine; customer deployment unknown
  target_architecture: arm64, to be verified on device by owner
  package: bede-mac-engineering-unnotarized-arm64-2eeed597fd90feea0e4592ec77fd79a6be535c00 (Actions run 44980645119, artifact 14737873579, expires 2026-12-22)
  package_digest: NOT_RUN; the DMG's own SHA-256 is in Bede-Engineering-Mac-arm64.dmg.sha256 inside the artifact and has not been read or verified
  package_status: built; ad hoc signed, not notarized, engineering only
  qualification_manifest: Sample qualification run 45022537882 (passed)
gates:
  agent_review: prior read-only reviews recorded; follow-up of proposed print fix pending
  automated_qualification: passed on 2eeed597 (see "Candidate under acceptance")
  customer_installation: NOT_RUN
  published_site_visual_check: NOT_RUN
  physical_mac_safari_acceptance: NOT_RUN; owner-operated
  real_learner_data: not authorized by this packet
  production_rc_ready: false
  deployment_authorized: false
decision:
  status: HOLD
  owner_approval_ref: null
```

## Candidate under acceptance (recorded 2026-11-22)

Candidate: `main` at `2eeed597fd90feea0e4592ec77fd79a6be535c00` (#895).
Three outcomes, kept apart. The first two do not establish the third.

**1. CI passed.** On 2eeed597, 79 check runs: 61 passed, 18 skipped, none
pending, no commit statuses. The 18 skipped are the demo watchdog's
`repair` job, which runs only when the watchdog finds a fault. The three
required checks (the `main` ruleset: FAQ copy, PDF and native print
cancellation; FAQ export parity firefox and webkit) passed on the first
attempt. Production deployment regression (44980645090) passed. Dispatched
against this SHA: sample qualification 45022537882 passed; cross-platform
browser journeys 45022539891 passed in all five jobs (macOS desktop and
mobile, Ubuntu desktop and boundary, Windows desktop).

Two exceptions are recorded rather than rounded off:

- The operator-bundle workflow run 44980645119 concluded failure although
  all nine of its jobs passed. #898 added a matrix `exclude` to the Linux
  DEB/RPM job, whose matrix had only `include`; GitHub created no job and
  failed the run on every push from f4154151. The Mac DMG is unaffected.
  The fix is commit 88a74e56 on #837; run 45022659588 there created and
  passed both Linux jobs. It reaches `main` only with #837 or separately
  on the owner's say.
- The FAQ print-cancellation check failed once on #911's head
  (324d48f1, run 44979575426, job 137076906007) and **passed on rerun**;
  it was not an uninterrupted pass. The failure is in the test harness:
  headed Chromium's native print preview did not appear within 15 s
  (`cancelPrintPreview`), so the FAQ's own restore check never ran. One
  failure in the last 40 runs. The failed log is kept with the session's
  evidence; the attempt-1 artifact expires 2026-12-06. It is not the
  teacher-plan or K-2 print code (`printDocument`/`printTeacherPlan`).
  If it recurs, or anything similar appears on those paths, investigate
  before release.

**2. The site build published.** Cloudflare Workers Builds reported success
for 2eeed597, and the live header check (44980645084) passed. The site
carries no revision marker, so "2eeed597 is what is served" rests on that
build result alone.

**3. The published site and the installed product were exercised.**
NOT_RUN. The agnusdei.ai pages could not be reached from the engineering
environment, and no one has installed this DMG.

### Before the Mac session

- **Licence.** This DMG verifies keys against the public key on `main`.
  The pilot replacement key described in BEDE_MAC_PILOT_INSTALLER.md §1 is
  not on `main`. Without a key signed for `main`'s key, the installed
  product starts gated. Confirm which key will be pasted.
- **Downloads.** The installer pulls the container images it names by
  digest. Local inference (the 2026-11-20 decision) needs an Ollama model
  pulled on the Mac. Docker Desktop, if not already installed. Each one is
  the owner's to approve.
- **Paid speech.** The reference voice is OpenAI's: with `OPENAI_API_KEY`
  set, each spoken line is a paid request and Bede's words leave the Mac,
  which the local-only decision did not cover. Choose: set the key for
  this check, or run text-first and record the voice check NOT_RUN.

### Mac acceptance steps

Record PASS, FAIL or NOT_RUN for each; sample data only.

1. In the unzipped artifact folder: `shasum -a 256 -c
   Bede-Engineering-Mac-arm64.dmg.sha256`. Record the digest; this fills
   `package_digest`.
2. Start Docker Desktop. Open the DMG, Control-click `Bede Installer.app`,
   choose Open, choose **Homeschool**.
3. In the browser setup: read and accept the notice, set the adult
   password, keep the suggested child PIN, choose Local (Ollama) with the
   approved model, set the voice as decided, paste the licence.
4. Sign in as the adult. Add a learner named "Sample Learner", grade 1;
   save.
5. Open the learner on this Mac, sign in with the child PIN, start
   Mathematics, answer two turns, then do one Number Time round to the end.
6. If the voice was chosen: Bede speaks the reply and the round's lines.
7. Adult Progress page: the round and the work appear.
8. Restart: quit Bede and Docker Desktop (or restart the Mac), reopen,
   sign in. The learner, settings and Progress are still there.
9. Upgrade and rollback: not applicable to a first install. If an earlier
   Bede is installed, record that the installer refuses the cross-version
   upgrade rather than overwriting it (it is meant to fail closed).

### Published site (owner, any browser)

- `https://agnusdei.ai/`: loads; no checkout or payment links.
- `https://agnusdei.ai/faq/`: open the curriculum section; Print FAQ opens
  the print dialog; Cancel returns with the same sections open.
- `https://agnusdei.ai/bede/`: start the demo as grade 2; Number Time to
  the end; "Print or save as PDF" gives one sheet with drawn pictures,
  plates of counters for a sharing question, nothing cut off.
- The same print from Sound Time and Map Practice (kindergarten or
  grade 1).
- `https://agnusdei.ai/privacy/`: loads.

Until someone does this, the visual check is NOT_RUN.

## Current evidence

**Source and dependencies.** At the latest check, `main` is
`30c9f3231a561be626109dfd1269a122021ba840`. PR #837 is open at
`da1a4a2413e80402672d042513325c88bde21a03`, based on
`33348a35621b235964397579d37d7fe19e4b818b`; neither SHA is an owner-selected
candidate. GitHub reports 51 changed files and 2,512 additions in the
PR's base-to-head comparison, including AI-provider settings/routing,
provider-error handling, sprint timing, Compose configuration, and
`render.yaml`, in addition to the teacher-content changes. Because the PR's
base SHA predates current `main`, this count is not the net change against
current `main`; the integration engineer must compute that exact diff and
reconcile every retained change with the frozen customer scope before
candidate selection. PRs #857 and #864 are merged. PRs #824, #851, #862, and #865
remain open; #862 has an explicit owner hold. PR #851 adds arm64 DMG
provenance only; it does not make the existing engineering DMG
distributable. PR #865's audit and backend checks passed on its own head
`60cd6f1784a136894be8fbe80327f906b274eb7b`, but it remains unmerged. No PR
was merged for this packet. Reconcile required dependencies on a deliberate
integration tree; do not silently package an older reviewed SHA.

**Current PR checks.** On PR #837 head
`da1a4a2413e80402672d042513325c88bde21a03`, all ten listed Actions runs
created at 2026-11-17 22:34 UTC report `action_required`. The browser
journey run `44191338496` and sample-qualification run `44191338604` each
have zero jobs, so they provide no result and have no failed-job logs. The
available record does not identify which approval is required. These runs
are for the pre-update packet head, not a selected candidate; new commits
also require checks on their exact SHA. The owner or repository
administrator must identify and approve the exact required check run after
the candidate SHA is selected. Do not retry or approve an obsolete-head run
as release evidence.

**Separate PR #824 failures.** The latest available browser run,
`44006123663` attempt 2, tested PR #824 head
`11de74c14ba91b591bfd332f986de5bd54f358a5`, based on the older
`b8f080a419833c5d62b29d362d0b9764474470c0`. Its Ubuntu boundary job
`134297685302` failed four checks: three parent journeys errored at
`locator.fill` because the value was undefined, and the locked-parent
check returned HTTP 422 after the lockout check itself passed. It recorded
21 of 39 expected checks, leaving 18 missing. This is distinct from the
known WebKit reload crash noted on PR #837. PR #824's frontend audit also
failed on that older head in run `44006123581`; the owner-authorized #864
allowlist change is merged, and the audit passed on #865 head in run
`44178150215`. That does not resolve #824's browser failures or qualify
either PR on the current base. The owner-authorized engineering action is
for the #824 builder to fix the exact boundary failures and rerun its
required journeys against current `main`; the integration engineer then
reviews the resulting tree without merging it.

**Related PR status.** PR #857 is merged at
`e581b077fd171b42ffb953843eef3e362a70dd0e`; its general browser run
`44161273052` passed 36/36 checks, including the restart/reopen journey on
macOS 15.8.2 arm64 with Playwright 1.63.0/WebKit 26.6. This is useful
evidence about that stack and journey, not qualification of this candidate
or real Safari. PR #865's audit and backend checks passed on its own head
`60cd6f1784a136894be8fbe80327f906b274eb7b` in runs `44178150215` and
`44178150317`; it remains unmerged. PR #862 remains open under the owner's
hold.

**Agent reviews.** The read-only `security-review` agent task
`0991951b-2452-47e8-907b-0aba3f86ef97` initially reviewed PR #837 at
`60dff17f19cdcb9ed4f42fa55c2efaec11e7d30a`; it recommended HOLD and identified
deployment-security and operations gaps, including a HIGH-severity concern
that the local Compose API uses the same `sage` credential as the official
PostgreSQL image's bootstrap user. The source supports the concern:
`docker-compose.yml` documents that credential for the API and sets
`POSTGRES_USER=sage`; `homeschool-api/core/database.py` runs
`Base.metadata.create_all` at startup. The release contract instead requires
a runtime `bede_app` role without schema DDL and a separate migrator. This
is an architecture conflict, not a credential-only change. The backend and
deployment engineers must design a migration/bootstrap path, then verify
the role flags, grants, startup, upgrades, and recovery on the selected
deployment. The database-role issue is a review finding, not a test of the
customer's installed database. The read-only `code-review` agent task
`b861f920-7cf8-46f3-a452-247d42f8fa07` initially reviewed
`60dff17f19cdcb9ed4f42fa55c2efaec11e7d30a` and found that the official-record
printout omitted the proposal rationale. That fix is committed in
`989af8255b20b3a3f55005c2d267c30341d8f4df`; its targeted API and frontend
tests could not run here because this checkout has neither `pytest` nor
`vitest`. A later code-review pass read the uncommitted packet diff against
source tree `da1a4a2413e80402672d042513325c88bde21a03` and identified
stale run references, review-SHA ambiguity, missing Number Time trace
provenance, and the missing #865 backend run reference. The packet has been
updated for those findings, but the print fix itself still needs an exact
source follow-up review. The code-review agent also posted status-only
comment `6963040217` to PR #837 during its read-only follow-up; no duplicate
comment was posted. Neither reviewer exposed a model or internal session
identity; the listed values are tool agent task IDs. These reviews are not
educator, human, counsel, school-administrator, or installed-build
certification.

**WebKit evidence.** Browser run `43744604620` on head
`885d3dc2d9a23bc8bffe0db1442a1937cb35dd7d` failed the macOS 15 desktop
job: `child3_webkit` crashed during `reopen_after_restart`, and the
dependent lesson/answer checks could not complete. Its summary recorded
35/36 checks; Chrome, Edge, and Firefox completed their corresponding
journeys. The collected crash report identifies
`WebCore::Navigation::initializeForNewWindow` with `EXC_BREAKPOINT`.
The owner's PR comment reports the same failure on `main` and earlier
workflow runs; that cross-run claim is owner-reported, not independently
verified here. The controlled diagnosis run `43757437010` reported
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
acceptance, and it is not evidence on a selected final candidate. The
`action_required` current PR checks have zero jobs, so they neither
reproduce nor clear this failure.

**Print finding.** Commit
`989af8255b20b3a3f55005c2d267c30341d8f4df` returns the rationale from the proposal
linked by the approved teacher decision and passes it to the existing
escaped “Based on” print section. It also checks the proposal's assessment,
campus, and learner association. The targeted API and UI tests were added
but not run here. Until they run on the selected integrated candidate, the
official-record print gate is not met.

**Number Time browser acceptance.** An operator note reports that the
branch preview at
`https://claude-debug-job-failure-l9isb8-bede.agnusdei.workers.dev/` was
blocked from its demo API by CORS, and that the production landing page at
`https://agnusdei.ai/bede/` loaded with `/health` and `/auth/locales`
returning 200. No timestamped browser trace or session record was retained;
these observations are unverified navigation notes, not qualification
evidence. The note reports that no demo session, math attempt, household
data access, progress-store write, or model call occurred. The production
demo's session path may invoke its configured tutor, so it must not be used
for this test unless the path is isolated behind the approved mock tutor and
a dedicated temporary data store.

The existing browser harness at
`scripts/qualification/browser_journeys/run_journeys.py` can run the real
UI and API against a loopback mock provider and a disposable SQLite
database, but its `journeys.cjs` and `model_stub.py` currently cover
history/sample tutoring, not Number Time. PR #857, which added Number Time,
is merged at `e581b077fd171b42ffb953843eef3e362a70dd0e`; it is not in this
PR's local tree, whose base predates that merge. Its recorded responsive
layout checks and unit/API tests are useful but do not supply a
Number-Time-specific browser journey in the qualification harness. The full
matrix is therefore not runnable on this branch as-is. After the owner
selects a candidate based on current `main`, the qualification engineer
must add Number Time-specific mock-provider behavior and browser assertions
to the isolated harness and run them against that exact candidate. The
exploration was read-only; agent role was `explore`, tool agent ID
`913eb3c5-525b-4a40-8069-39ac8185aa0f`; session and model identities were
not exposed. No production demo session was started.

## Owner decisions recorded 2026-11-20

Recorded from the owner's written answers; they narrow the decisions below
and do not close them.

- **Data:** sample records only for the pilot; counsel and school
  authorization are required before any real learner data.
- **Language:** English-only teacher screens.
- **Inference:** local-only, with room to point the `local` adapter at a
  private-network OpenAI-compatible endpoint (`LOCAL_LLM_BASE_URL`, no code
  change). Teacher quiz paths stay on `resolve_local_only()` and never reach
  a cloud provider. A different private-fabric protocol would need its own
  adapter and is not part of v1.0.
- **Quizzes:** Teacher Quiz Studio and model-drafted quizzes are in scope,
  not deferred.
- **Small language models:** Bede will be tested on SLMs.
  `homeschool-api/scripts/slm_pilot_probe.py` is the by-hand check (tutor tool
  call, quiz draft, quiz read from text and from a picture). It refuses a
  public endpoint and any paid provider key, downloads nothing, and reports
  NOT_RUN, ERROR and NO_VISION distinctly. Its result is NOT RUN until the
  owner runs it on the chosen model; a PASS still needs a person to read
  the report.

## Owner decisions required

Please answer these before selecting a candidate. Recommendations are
included to make each choice concrete, not to make it on the owner's behalf.

1. **Actual deployment target and topology:** the recorded physical
   acceptance machine is the owner's 24 GB Apple Silicon MacBook Pro, with
   the runbook selecting same-machine operation
   (`docs/release/BEDE_MAC_PILOT_INSTALLER.md`). This identifies the
   owner-operated acceptance target, not the customer's production server
   or network topology. Confirm whether the customer deployment uses that
   same target or provide its host OS, exact hardware/chip, architecture,
   and whether the teacher uses a second LAN client. Recommendation: use
   the simplest topology that satisfies the agreed pilot; verify the
   physical Mac's architecture on-device rather than infer it from runner
   evidence.
2. **Inference and data flow:** name the permitted provider, exact model,
   runtime and endpoint; specify whether any learner message, assessment
   record, or other learner data may leave the customer network; and state
   credential provisioning. Also decide whether the branch's provider
   selection and provider-check controls are in the customer scope: a
   provider check sends a real request to configured providers and may incur
   cost. Recommendation: keep educator pilot inference local-only, disable
   provider checks and cloud failover unless the owner explicitly approves
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
   The integration engineer must also compute PR #837's net diff against
   current `main`; if provider-switching or sprint-timing changes remain
   outside the frozen agreement, recommend excluding them unless the owner
   expressly includes and qualifies them.
5. **Number Time boundary:** Decision 40(g) permits the already-built,
   direct-entry public-demo activity only. It does not authorize tutoring
   invitations or other practice areas. The owner has specifically requested
   the full Number Time acceptance matrix; do not treat it as passed or
   defer it without a separate scope decision. Decisions 40(c)-(f) remain
   outside this RC and should be explicitly deferred, not decided by
   implementation.
6. **Exact workflow approvals:** after source and target are selected,
   authorize or decline the exact workflow/ref/SHA/inputs in the approval
   request below. At the latest check, PR #837 browser run `44191338496`
   and sample-qualification run `44191338604` on ref
   `claude/debug-job-failure-l9isb8`, SHA
   `da1a4a2413e80402672d042513325c88bde21a03`, were `action_required` with
   zero jobs; the available record does not say which approval is required.
   These pre-update runs are not evidence for a later head. No workflow
   dispatch, package publication, notarization, or release/deployment
   workflow is authorized by this packet.

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

On the latest checked PR #837 head,
`da1a4a2413e80402672d042513325c88bde21a03`, browser run `44191338496`
and sample-qualification run `44191338604` are both `action_required` with
zero jobs; the other eight listed runs on that head have the same
conclusion. The available record does not name the required approval, and
these runs are not the selected candidate. Do not approve or retry them as
release evidence. After the owner selects an integrated SHA, the
qualification engineer must identify that SHA's exact check runs and
request any required GitHub approval before interpreting results. The
existing macOS runner can build arm64; the Intel runner is
`macos-15-intel`. Neither runner establishes the customer's architecture.

## Engineering and qualification blockers

Each item has an accountable role, next action, and evidence required to
close it:

| Blocker | Accountable role and next action | Closure evidence |
| --- | --- | --- |
| Candidate source and open dependencies | Owner selects the source scope; integration engineer reconciles required PRs without merging on the owner's behalf. Preserve #862's hold. | One committed, clean, full 40-character SHA with a reviewed dependency list. |
| Customer OS, architecture, topology, provider/model, and data scope | Owner supplies the choices above; release engineer records them without inference. | Approved scope record tied to the candidate. |
| Database runtime privilege | Backend and deployment engineers resolve the conflict between API-startup `create_all` and the release contract's no-DDL `bede_app` role; the local Compose profile currently uses `sage` for both API access and PostgreSQL bootstrap. | On the selected package, prove separate bootstrap/migrator/app identities, required role flags and grants, successful startup and upgrade without app schema DDL, and restore without exposing bootstrap credentials to the runtime. |
| Production recovery | Deployment engineer provides encrypted backup, key custody, offsite policy if required, and a destructive restore rehearsal. | Dated backup/restore evidence with measured RTO/RPO on the selected deployment. |
| Package and provenance | Release engineer finds an authorized compatible runner and an approved packaging route. The existing operator image build downloads faster-whisper `base` weights and publishes to GHCR; that path is not authorized here. | Customer-installable package, exact source and target provenance inside/alongside it where supported, SHA-256 from final bytes, and a separate verifier report. No model download or publication without separate approval. |
| Installed-build security and access | Release engineer qualifies TLS, passkey setup, teacher/campus/learner isolation, persistence, provider connectivity, health, diagnostics, and rollback on the selected topology. | Requirement-mapped results tied to exact candidate and artifact; failures resolved or explicitly left blocking. |
| Functional and language qualification | Qualification engineer runs the required teacher journeys and isolation/recovery cases. If Spanish is approved, run an end-to-end journey with the approved mock tutor and label the result as a mock. Actual local-model Spanish or tool-call claims require an explicitly authorized machine with the model already installed; they are not a gate for mock verification. | Complete exact-candidate matrix and evidence manifest. Mock tutor results must be labeled as mock. |
| Number Time acceptance | After owner candidate selection, qualification engineer adds Number Time-specific mock responses and browser journeys to `scripts/qualification/browser_journeys/`, then runs the real UI/API with the harness's loopback mock provider and disposable SQLite store. Use temporary math attempts only. The current PR branch predates merged PR #857 and has no Number Time journey. Do not send live model traffic or use household data. | Cover count, compare, add, subtract, and number-bond topics across Watch, Together, and Your turn; first-try, second-try, and answer-shown outcomes; the count-only evidence rule for counter-building; invitation, consent, grade/subject, per-sign-in quota, and retry/race boundaries; accessible labels and responsive layout. Prove no household access and no change to existing demo progress stores. Bind results to the exact candidate. |
| Physical Mac and Safari | Owner alone operates the pilot Mac; engineering prepares one bounded session and exact install/rollback steps. | Actual owner-recorded results. Until then every physical row remains `NOT_RUN`. |
| School data authorization and notice | School administrator supplies required authorization; counsel reviews the school notice before real learner data. | Current notice hash and required authorization/review evidence; no wording here claims those occurred. |

These are not a permanent stop list: each names the person or role who can
act and what evidence closes the gap. If a prerequisite needs a workflow
permission or runner, request the exact workflow, ref, SHA, inputs, and
approval rather than claiming delivery.

## Dated owner checklist

**Status recorded 2026-11-17.** No due dates were supplied; none are
invented here.

- [ ] Confirm the actual customer host, architecture, topology, provider,
  model, learner-data egress, credential provisioning, and sample-versus-
  real-data scope.
- [ ] Decide teacher-language scope, Teacher Quiz Studio/model-drafted quiz
  scope, and the required Number Time boundary.
- [ ] Select an integrated full source SHA after dependency and scope review;
  authorize any exact package, model-weight, GHCR, signing, or notarization
  effects before they occur.
- [ ] Ensure exact-SHA checks and qualification run after the necessary
  workflow approval; review all findings and package provenance.
- [ ] Operate the bounded physical Mac/Safari acceptance session and record
  actual results; do not substitute hosted-browser or mock results.
- [ ] Make a dated `PRODUCTION PILOT RC READY` decision only after every
  required gate closes, then separately decide whether customer deployment
  is authorized.

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
