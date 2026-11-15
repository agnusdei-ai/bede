# Release repair: independent review

Read `release-repair-common.md` first. You did not write this patch, and you
are not shown its author's reasoning. You push nothing.

Review the diff on the branch in your envelope against its base, plus the
controller's verification facts. Check the scope, data isolation, privacy,
authorization, cancellation and persistence where relevant, and whether any
assertion was weakened or the patch reaches beyond its task. Say whether a
required human review is still outstanding; your review never replaces one.

`verdict`: `approve`, `changes_requested` (say exactly what), or `escalate`
(needs the owner).
