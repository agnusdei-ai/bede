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
   - Verification is a `record` dispatch naming the task, its branch and its
     recorded base. The `candidate` job runs that branch's tests with the
     trusted runner, and the new test must fail on the base and pass on the
     branch. The trusted validator reads the diff.
4. **Integrate.** The coordinator merges reviewed branches into
   `release-repair/<cycle>/candidate` with merge commits and records
   `integrated` with the new SHA. Open tasks on the old base are superseded
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
- **Owner-only events** (`authorization`, `physical`, `cancel`) need
  `actor: owner` and an `owner_ref` naming where the owner said it. The
  coordinator submits them only on the owner's word.

## The trust boundary

- `resolve` and `record` run only the controller, policy and acceptance
  manifest at the run's own `main` SHA. A candidate cannot loosen the rules
  it is judged by.
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

## Files

- `scripts/release_repair/`: controller, state store, leases, policy,
  validator, regression verifier, result adapter, gates, evidence,
  redaction, artifact lookup, main audit.
- `config/release-repair.json`: the policy.
- `config/acceptance/`: `bede-release.json` (real gates) and
  `test-only.json`.
- `schemas/`: release cycle, repair task, agent result, snapshot.
- `.github/workflows/release-repair.yml` and `release-repair-audit.yml`.
- `.github/agent-prompts/release-repair-*.md`: role instructions.
- Tests: `homeschool-api/tests/test_release_repair_*.py`.
