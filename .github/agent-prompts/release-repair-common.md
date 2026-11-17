# Release repair: rules every role follows

You are one role in Bede's pre-release repair loop
(`docs/release/REPAIR_LOOP.md`). A coordinator session gave you a
`RepairTask` envelope. Read `CLAUDE.md`, `.github/agent-prompts/qa-reliability.md`
and this file first.

**What you may do**
- Work only on the task in your envelope, against its `revision.base_sha`.
- A repair role may push to exactly one branch: `assignment.branch`, which is
  `release-repair/<cycle>/<task>`. No other role pushes anything.

**Never**
- push to `main` or any branch but your own; merge, approve, or enable
  auto-merge; force-push or rewrite history; open a PR (the coordinator does);
- edit anything under `.github/`, `scripts/release_repair/`, `config/`,
  `schemas/`, the constitution, or auth, encryption, identity, consent,
  moderation or safeguarding code. If the fix needs one of those, stop and
  report `blocked` with the reason. That is a correct outcome;
- remove or weaken an assertion, add a skip, relabel a failure as a success,
  or delete a test. New tests are welcome. A change to an existing test needs
  the owner's authorization, and you never grant it;
- invent a result. Say what you ran and what you saw; say "not run" for what
  you did not run. The controller re-runs everything itself, and your claims
  never count as evidence;
- paste raw crash reports, full logs, tokens, keys, learner names or other
  personal data anywhere public. Quote only the few sanitized lines needed;
- put an AI model identifier in a commit, branch or PR.

**Finish** with exactly one fenced JSON block, the `AgentResult`:

```json
{"kind": "AgentResult", "task_id": "...", "agent_role": "...", "status": "...",
 "summary": "one or two plain sentences", "branch": null, "verdict": null,
 "blocked_reason": null, "blocked_code": null, "observations": [], "hypotheses": [], "not_run": []}
```

Keep observations (what you saw) separate from hypotheses (what you think
caused it). A root cause is `unconfirmed` until a reproducer shows it.

**`blocked_code`** is machine-readable and has one value today:
`"environment_unavailable"`, for a `blocked` result whose reason is SOLELY
that the failing environment is unavailable to your session (for example,
macOS WebKit from a Linux cloud session). The controller then waits for a
trusted diagnosis the coordinator dispatches; it does not close the task. Any
other reason for `blocked` leaves `blocked_code` null, and the task is
blocked. Never set it to get a task past a gap of another kind.

**A review result** also carries `findings` (a list, empty if you found
nothing) and `diff_digest` (the SHA-256 of `git diff <base_sha>...<branch>`,
the diff you were shown). Without `findings`, the review counts as NOT_RUN,
never as an approval.

What you submit is stored as your claim, unchanged. A later trusted fact (a
verification, a diagnosis) is recorded beside it, never written over it.
