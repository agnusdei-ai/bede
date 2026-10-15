# Bede event-driven pull-request merge gate

Status: **merge gating only**. Not a replacement for engineering agents, Mac verification, or release owner approval.

## Event triggers

The trusted workflow `.github/workflows/bede-event-driven-merge.yml` reacts to completion (success or failure) of Backend regression tests, Frontend regression tests, CodeQL analysis and Institutional ordered qualification. It also reconciles on PR opening, new commits, ready/draft transitions, labels, main pushes and an optional manual dispatch. CI changes are evaluated as events occur rather than waiting for a ChatGPT hourly check.

## Required conditions for merge

Every condition is checked using fresh GitHub API data:

1. PR is open, targets `main`, not draft, and is in this **same** GitHub repository.
2. PR has the explicit `release:automerge` opt-in label.
3. GitHub reports it cleanly mergeable.
4. Backend, frontend and CodeQL workflows all finished successfully on the **exact current PR head SHA**, on that PR branch. A present institutional qualification workflow must also be green. Missing, pending or failed workflows block the merge.
5. At least one independent human GitHub approval applies to the **current** head commit. Security/identity/campus/roster, deployment/workflow, billing and recovery changes require two independent current-head approvals. Later dismissals or change requests invalidate those approvals.
6. The PR is re-read immediately before the merge, and GitHub receives the exact expected head SHA.

Changes with insufficient evidence are left open without branch protections being bypassed. The workflow never checks out untrusted PR code, reads uploaded PR artifacts or exposes production credentials. Its review/merge outcomes appear in the GitHub Actions job summary; denied merges are recorded there.

## Post-merge and release boundaries

GitHub's default `GITHUB_TOKEN`-based merges do **not** automatically fan out to ordinary push-triggered workflows. This workflow explicitly dispatches the three non-deploying CI workflows on `main` as a verification follow-up. It does **not** dispatch production deployment, open a public enrollment flow, move real learner data, or assert pilot GO.

Draft PRs #590, #591, #596 and #600 must satisfy their implementation scope and pass review before any opt-in. The separate #588 G1/G2/G3 pilot release HOLD and owner-signoff gate continue to apply. A review is not a substitute for testing physical Mac installation or a real WebAuthn ceremony.

**Limitation:** This is event-driven GitHub **validation and merging**, not a hosted model agent that independently implements every unfinished feature. Agentic implementation requires an authorized runner and credentials, or continued connected engineering sessions; this workflow does not silently pretend to provide that capability.
