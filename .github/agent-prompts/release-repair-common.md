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
 "blocked_reason": null, "observations": [], "hypotheses": [], "not_run": []}
```

Keep observations (what you saw) separate from hypotheses (what you think
caused it). A root cause is `unconfirmed` until a reproducer shows it.
