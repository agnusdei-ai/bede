# The pre-release repair loop

**Status: built, not yet operational.** The controller, validator, workflows
and role instructions exist and are tested. The live loop (a coordinator
session starting child sessions, CI waking it, state persisting between runs)
has **not** been demonstrated yet. Until it has, nothing here should be
described as running. The first live cycle is the WebKit task below.

The loop repairs a release candidate before it ships, then qualifies it. It
never merges, publishes, deploys or approves. Those stay with the owner.

## Who does what

| Role | Who | Can write |
|---|---|---|
| Release owner | the owner | merge, publish |
| Coordinator | a Claude Code session the owner started, driving the controller | dispatches the controller, opens PRs, integrates reviewed branches |
| Triage, reproduce, repair | one child Claude Code session per task | a repair session pushes only to `release-repair/<cycle>/<task>` |
| Verify | the trusted controller plus the isolated `candidate` job | nothing |
| Independent review | a separate child session, shown the diff and the evidence, not the author's reasoning | nothing |
| Physical Mac and Safari | a person; recorded with an owner reference | nothing |
| Evidence | the trusted controller | nothing |

There is no API key and no model in CI. The sessions run under the owner's
own account.

## What a cycle looks like

1. **Start.** Dispatch `Release repair loop` with `action: start`, a
   `cycle_id` and the full `candidate_sha`. Every configured failure starts
   as an active task. Today that is the WebKit crash.
2. **Baseline.** The coordinator runs the existing qualification workflows
   on the candidate SHA, then dispatches `action: record` with their run ids
   in `results_runs`. Every failing check becomes a task, or adds evidence to
   the task it duplicates.
3. **Each task** moves through triage, reproduce, repair, verify and review.
   - The coordinator records which session holds a role (`assign`) before
     starting it, so a resumed coordinator reattaches instead of starting a
     duplicate.
   - Each session finishes with an `AgentResult` (see
     `.github/agent-prompts/release-repair-common.md`). The coordinator
     submits it as a JSON event. It is stored as a claim and never counts as
     evidence.
   - A reproduce session that cannot reach the failing environment reports
     `blocked_code: environment_unavailable`; the coordinator dispatches the
     trusted diagnosis workflow and then `record` with `task_id` and
     `diagnosis_run` (see "The six loop definitions").
   - Verification is a `record` dispatch naming the task, its branch and its
     recorded base. The `candidate` job runs that branch's tests with the
     trusted runner, and the new test must fail on the base and pass on the
     branch. The trusted validator reads the diff.
4. **Integrate.** The coordinator merges reviewed branches into
   `release-repair/<cycle>/candidate` with merge commits and records
   `integrated` with the new SHA (the full procedure is under "Integration";
   it never merges to `main`). Open tasks on the old base are superseded
   and reissued on the new base, keeping their attempt count. Earlier passes
   do not carry over.
5. **Qualify and package** on the new SHA, the same way as step 2.
6. **Physical checks.** The owner runs `scripts/qualification/mac_check.py`
   and the result is recorded as a `physical` event with the owner's
   reference. Without one, the physical gates stay NOT_RUN.
7. **Decision.** When every required gate passes and nothing blocks, the
   status is `READY_FOR_RELEASE_DECISION`. That is a statement that the
   evidence is complete, never an approval.

The coordinator notifies the owner twice: when a cycle starts and when it
reaches a terminal state (ready, budget exhausted, blocked or cancelled).

## The rules the controller enforces

- **Budget:** two repair attempts per task, then `BUDGET_EXHAUSTED`.
- **Known failures are investigated, not waived.** The WebKit crash
  (`webkit-original-page-reload-crash` in `config/release-repair.json`) is
  release-blocking and deduplicated by its check and crash frame. Repeated
  hits add evidence to one task. Only an owner-recorded
  `owner_approval_ref` can suppress repair, and none is recorded.
- **Existing tests:** any change to one waits for the owner. Four kinds are
  always named and never pass silently: a removed assertion, a weakened
  expected result, a new skip, and a failure relabelled as a success. New
  tests are welcome. An agent can never authorize its own exception.
- **Protected paths** (`.github/`, this loop's own code, config and schemas,
  the constitution, auth, encryption, identity, moderation) and **sensitive
  paths** (consent, MFA, recovery, deletion, learner scope, `site/`,
  `demo/`) wait for the owner.
- **Leases:** a result from a stale or expired lease, or verified against
  the wrong base, branch or policy revision, is refused.
- **Outcomes keep their reasons.** A cycle that ran out of budget and is
  missing Mac evidence reports both blockers.
- **Missing evidence is NOT_RUN, never a pass.** ABSENT, BLOCKED and
  UNVERIFIED qualification cells are failures. A result for another SHA is
  refused.
- **Owner-only events** (`authorization`, `physical`, `cancel`,
  `resolved_outside_loop`) need
  `actor: owner` and an `owner_ref` naming where the owner said it. The
  coordinator submits them only on the owner's word.

## The six loop definitions (owner, 2026-11-16)

Each stage below is enforced by the controller, not only described here.
`homeschool-api/tests/test_release_repair_loop_definitions.py` pins every
rule, and each guard was verified by breaking the code it guards.

1. **Trusted diagnosis.** A reproduce session that is blocked SOLELY because
   the failing environment is unavailable to it reports
   `"blocked_code": "environment_unavailable"`. The task then moves to
   `AWAITING_DIAGNOSIS`, which is not terminal, instead of `BLOCKED`. Any
   other blocked result is still `BLOCKED`, and so is this one when the
   failure has no trusted diagnosis configured
   (`no_trusted_diagnosis_configured`), so a task can never wait forever.
   The coordinator dispatches the configured read-only workflow
   (`webkit-reload-diagnosis.yml`: `workflow_dispatch` only,
   `contents: read`, no secrets, a hosted `macos-15` runner), then
   dispatches `record` with `task_id` and `diagnosis_run`. The trusted
   `record` job alone builds the `diagnosis` event (`diagnosis.py`), from
   that run's own artifacts: `results.json` (per-variant tallies, NOT_RUN
   variants with their reasons) and `runner.txt` (the `candidate:` line and
   the `verified:` line naming the WebKit build, Node and macOS it ran on).
   The coordinator never types a diagnosis: `intake.py` refuses a
   `diagnosis`, `verification` or `results` event, or an `ancestry` field,
   submitted as `event_json`, and records the refusal. The controller
   refuses a diagnosis from another workflow, for another SHA (the run's
   head SHA and each artifact's SHA must equal the task's base), with a
   missing, ambiguous or unfinished artifact, whose engine never ran, or
   whose verified environment does not match the pins, and one for a task
   that is not `AWAITING_DIAGNOSIS`. The child's original claim is stored
   unchanged and never edited; the diagnosis is recorded beside it on the
   task and in the failure's evidence. A diagnosis is bound to its SHA, so
   an `AWAITING_DIAGNOSIS` task is superseded and reissued like any open
   task when the candidate moves. (`AWAITING_AUTHORIZATION` stays exempt
   from supersession, as before: an owner decision is pending.)
2. **Repair.** Unchanged: one repair session per attempt, on
   `release-repair/<cycle>/<task>` only, two attempts per task.
3. **Verify.** The trusted `candidate` job runs the branch's new test on the
   base and on the branch. A new test that **passes on the base too**
   (`pre_fix_passed`, every exit code 0; a timeout is not a pass) proves
   nothing about the fix: the task returns to `REPAIRING` with
   `invalid_verification_test_passes_on_base` and the attempt is **not**
   consumed. A second invalid verification on the same task blocks it with
   `invalid_verification_repeated`. A verification for another branch,
   against a stale base, without a resolved 40-hex SHA, under another policy
   revision, or an agent result from a stale or expired lease, is refused.
4. **Independent review.** A review is a record: the review session's
   assignment (role, session id, lease generation), the `diff_digest` of the
   diff it was shown, the resolved SHA it reviewed, and its `findings`. A
   review with no `findings` field, an invalid digest, or one that could not
   complete (`status` other than `reviewed`, such as a Copilot review that
   never finished) is recorded as NOT_RUN: it approves nothing and the task
   waits for another review. An approval counts only for the diff the task
   still resolves to.
5. **Integrate, qualify and package.** The coordinator's procedure is under
   "Integration" below. Package evidence is recorded per artifact (see
   "Package evidence").
6. **Terminal rules.** Notifications go out at start and at a terminal
   state only. A blocked or budget-exhausted cycle keeps every blocking
   reason, each under its own code, and a not-reproducible task keeps the
   original reason and the new one together.

## The four owner rulings (2026-11-16)

1. **Diagnosis versions are #848's rule.** Node exactly `v24.22.2`;
   Playwright **1.56.0** (WebKit 26.0, the build that crashed) is the
   **control**; **1.63.0** (WebKit 26.6, the version `main` pins) is the
   **comparison**; the browser is the one the pinned package installs. The
   pins live in `config/release-repair.json` under the WebKit failure's
   `trusted_diagnosis`, and the policy loader refuses a range or a control
   equal to the comparison. Outcomes:
   - the control did **not** crash: the harness did not show it can detect
     the failure, so the task is `BLOCKED` with
     `diagnosis_control_did_not_reproduce`;
   - the control **and** the comparison crashed: reproduced; the task goes
     to `REPAIRING` with the diagnosis attached as evidence;
   - only the control crashed: not reproduced on the version the candidate
     pins; the task is `BLOCKED` with the original reason **and**
     `not_reproducible_in_trusted_environment`, reported together.

   None of these is a pass or a waiver. The failure stays open and
   release-blocking until it is verified fixed.
2. **Fixed outside the loop.** A failure fixed by an owner-directed PR
   outside the loop (the WebKit crash was fixed by #841's Playwright 1.63.0
   pin) closes only through `resolved_outside_loop`: `actor: owner`, an
   `owner_ref` naming where the owner said it, `fixing_pr`, `merge_sha` and
   `failure_key`, submitted by the coordinator only on the owner's word. The
   `record` job checks with git (`merge-base --is-ancestor`, in a blobless
   bare clone) that the merge SHA is an ancestor of the **current**
   candidate and adds that fact; the controller refuses the event without
   it, against another candidate, or when git could not answer. It is
   accepted only when the current candidate's results include at least one
   row for the failure's checks and every one of them passes. The failure
   becomes `FIXED_VERIFIED` and its open task `FIXED` with reason
   `resolved_outside_loop:<pr>@<sha>`. A task already terminal (`BLOCKED`)
   is not rewritten.
3. **`independent_review`.** PASS needs at least one qualifying review
   record. If no repair task ever reached `READY_TO_INTEGRATE` or
   `INTEGRATED` in the cycle, the gate reads **NOT_REQUIRED**: reported
   under that name, never as PASS, and it does not block. If any task is
   integrated or ready to integrate without a qualifying approval of its
   current diff, the gate is NOT_RUN and it blocks. This replaces the
   vacuous pass cycle `webkit-1` exposed.
4. **Verify loop.** As in definition 3 above: an invalid verification does
   not spend an attempt, and the second one blocks the task.

## Integration

The coordinator, never a repair session:

1. Merges each reviewed branch (status `READY_TO_INTEGRATE`) into
   `release-repair/<cycle>/candidate` **with a merge commit**.
2. Dispatches `record` with an `integrated` event naming the new candidate
   SHA and the merged task ids. The controller refuses a task that was not
   reviewed and approved, moves the candidate, and supersedes every open
   task on the old base, reissuing it on the new base with its attempt
   count. Results for the old SHA stop counting.
3. Opens the pull request from the candidate branch to `main`. That pull
   request waits for the owner. The coordinator **never merges to `main`**,
   never enables auto-merge, and never approves.

## Package evidence

`qualification_adapter.package_artifacts` records one row per packaged file
in a `build-bede-operator.yml` artifact: filename, embedded SHA,
architecture, OS, checksum and signing status. What the build actually
writes decides what is recorded:

- `RELEASE_PROVENANCE.json` carries `source_sha` and `architecture`. It is
  read beside the file or inside a `.tar.gz` (read, never extracted). A
  package built from another SHA is refused.
- It has **no OS and no signing or notarization field**, so both are NOT_RUN
  with that reason, never read off an artifact's name. The engineering
  builds are deliberately unsigned or ad hoc signed; distribution signing is
  the owner's separate release step. A `NOT_FOR_DISTRIBUTION.txt` beside
  the file is recorded as a fact.
- The checksum is the build's own `.sha256` sidecar, recomputed. A missing
  sidecar is NOT_RUN for that artifact, never inferred from the Actions
  archive digest; a mismatch is FAIL.
- The arm64 Mac DMG has no provenance file beside it and its embedded copy
  cannot be read off macOS, so its embedded SHA is NOT_RUN and the package
  gate stays NOT_RUN until the build writes one beside it (as the Intel DMG
  does). That is a build change for the owner, not something this loop
  infers.

Results are keyed by SHA, so an unchanged pass on the same SHA is reused
when other results are recorded later, and a new SHA earns its own.

## The trust boundary

- `resolve` and `record` run only the controller, policy and acceptance
  manifest at the run's own `main` SHA. A candidate cannot loosen the rules
  it is judged by.
- Only `record` builds the trusted events: `results`, `verification`,
  `diagnosis`, and the `ancestry` fact on `resolved_outside_loop`. Its
  intake (`intake.py screen`) refuses any of them arriving through
  `event_json` and records the refusal.
- `candidate` is the only job that runs candidate code. It has
  `contents: read`, no state access and no coordinator credential. Its test
  outcomes are still candidate-controlled by nature, so they are bound to
  the SHA and treated as no more than that.
- State snapshots are accepted only from the `record` job of this workflow
  on `main`. A snapshot uploaded before `record` started, which is when
  `candidate` runs, is refused.

## Known limits, stated plainly

- **A push to `main` is detected, not prevented.** Sessions push with the
  owner's authorization, and the live ruleset has no required checks.
  `Main provenance audit` fails loudly on any commit that did not arrive
  through a merged PR. A merged PR shows how a commit arrived, not that
  anyone authorized it. The owner has not yet confirmed this trade-off in
  writing (`docs/DECISIONS.md` entry 41).
- **Snapshots can race.** Artifacts have no compare-and-swap. A run checks
  that no newer snapshot appeared before it publishes, and the coordinator
  resubmits anything not acknowledged. That detects a race; it does not
  prevent one. A missing, corrupt, expired or ambiguous snapshot is
  `BLOCKED`, never a fresh start.
- **GitHub concurrency is not a queue.** A pending run can be replaced by a
  newer one. Every event carries an `event_id`, duplicates are no-ops, and
  `reconcile` lists what was never acknowledged.
- **The demonstrations in the tests are controller tests.** They prove the
  rules with fake inputs. The test-only acceptance manifest
  (`config/acceptance/test-only.json`) is labelled as such and says nothing
  about Bede's real release gates.
- The `demo-watchdog` repair job and the event-driven merge workflow stay on
  hold. This loop does not meet their "cannot push to main" condition and
  does not touch them.

## What the live runs have found

- **Cycle `webkit-1`, run 2 (2026-11-15):** the first `record` dispatch
  failed with 401 while downloading the saved snapshot. GitHub answers an
  artifact download with a redirect to blob storage, and `urllib` forwarded
  the GitHub token to the storage host, which refused it. `artifacts.py` now
  drops the token on any cross-host redirect (also keeping it from a third
  party), and a real-socket test pins it. Nothing was published by the
  failed run, and its event was resubmitted under the same `event_id`.
- **Cycle `webkit-1` ended BLOCKED (2026-11-16, run 43782253330, snapshot
  sequence 4).** Triage classified the crash; the reproduce session reported
  `blocked`, as its rules require, because a cloud session has no macOS
  runner and the failure is macOS WebKit only. It read the coordinator's
  diagnosis run (43757437010) and confirmed its tallies without claiming a
  run of its own. The controller stored that reason verbatim, marked the task
  and the cycle BLOCKED, and recorded the terminal notification. The repair
  could not have gone through the loop either: the fix was the Playwright
  1.63.0 pin, which lives in `.github/`, a path no repair role may edit. It
  reached `main` through the owner-directed #841 instead.

  So the loop has now been seen to dispatch, persist, wake, accept a child
  session's result and reach a terminal state. It has **not** yet exercised
  trusted verification, review or integration, since no task got that far.
  Two gaps this cycle exposed, both now closed **in the controller** (owner
  rulings 2026-11-16, above):
  - **A macOS-only failure could not be reproduced by any role.** It now
    waits in `AWAITING_DIAGNOSIS` for a trusted diagnosis the `record` job
    reads from a named `webkit-reload-diagnosis.yml` run.
  - **`independent_review` reported PASS when nothing was reviewed.** It now
    reads NOT_REQUIRED when no repair got that far, NOT_RUN when a repair
    lacks a qualifying review record, and PASS only on one.

## What is demonstrated, and what is not

- **Demonstrated by tests** (controller tests with fake inputs, plus real
  git, real tarballs and #848's real artifact formats where reachable):
  every definition and ruling above, each guard verified by breaking it.
- **Not yet demonstrated live:** a `record` dispatch with `diagnosis_run`
  against a real `webkit-reload-diagnosis.yml` run, a `resolved_outside_loop`
  event with the live git check, a qualifying review, an integration, and a
  package collection from a real `build-bede-operator.yml` run. None of
  these should be described as running until a cycle has done it.

## Files

- `scripts/release_repair/`: controller, state store, leases, policy,
  validator, regression verifier, result adapter, gates, evidence,
  redaction, artifact lookup, main audit, the trusted diagnosis builder
  (`diagnosis.py`) and the record job's intake (`intake.py`).
- `config/release-repair.json`: the policy.
- `config/acceptance/`: `bede-release.json` (real gates) and
  `test-only.json`.
- `schemas/`: release cycle, repair task, agent result, snapshot.
- `.github/workflows/release-repair.yml` and `release-repair-audit.yml`.
- `.github/agent-prompts/release-repair-*.md`: role instructions.
- Tests: `homeschool-api/tests/test_release_repair_*.py`.
