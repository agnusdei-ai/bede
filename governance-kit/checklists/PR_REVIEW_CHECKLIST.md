# PR Review Checklist

For reviewing a change to an agent that already has governance in place. Short
on purpose: a checklist nobody finishes is a checklist nobody reads.

---

## Always

- [ ] **Does this add a prompt-building path?** If yes, does the constitution
      preamble reach it? This is how a fifth prompt ends up ungoverned.
- [ ] **Does this persist text the model wrote or a user influenced?** If yes,
      is it replayed into prompt context later, and is it sanitized on both
      paths? Provenance is not the test; replay is.
- [ ] **Does this delete or reword any guardrail prose?** Guardrail text is
      removed by otherwise-correct refactors and no functional test goes red.
- [ ] **Does this compute anything new about a person?** If yes, who sees it,
      what would it be mistaken for, and would a blank be distinguishable from a
      low value?

## If it adds a tool

- [ ] Trust tier declared, and `internal` is actually true: where does the
      result come from?
- [ ] Registered **and** has a dispatch branch (the set-equality test still
      passes)
- [ ] `reactable` only if the outcome is genuinely dynamic
- [ ] If silent, the no-output contract is tested
- [ ] Counts against the existing caps rather than getting its own budget
- [ ] Audited on dispatch

## If it touches detection or policy

- [ ] New patterns tested against a **benign** corpus, not only a hostile one
- [ ] New categories placed deliberately in blocking vs. audit-only, with the
      reason in the PR
- [ ] The classifier still fails open
- [ ] Tier 1 still works with Tier 2 forced to fail
- [ ] Language coverage extended if the product's language coverage changed

## If it touches the constitution

- [ ] Substance genuinely unchanged, or the full change-control process ran
- [ ] Digest re-pinned **in this same commit**: a lone re-pin commit is the
      shape of an unreviewed governance change
- [ ] Structural validator updated if the required shape changed
- [ ] A written reason is in the PR body, not just the commit message

## If it adds a test

- [ ] ⚠ **Was it verified by breaking the thing it guards?** Say so in the PR.
      A test that does not fail when the behavior regresses is worse than none,
      because it appears in coverage as though it were working.
- [ ] Does it read the **real object** rather than a reconstructed replica?
- [ ] If it scans text for a term, could it pass on a **docstring explaining why
      the thing was deliberately not done**? Scan declarations and calls, not
      prose.
- [ ] Does it assert the **call site**, or only the function?

## If it touches user-facing copy

- [ ] Still true of what the system actually does
- [ ] If a public claim of completeness exists (a privacy inventory, a
      disclosure page), is it still complete after this change?
- [ ] Same fact stated in two places → is there a test that they agree?

---

## The two questions worth asking on every PR

**1. What would have to be true for this to be wrong?**

Not "is this correct": the author already believes it is. Ask what assumption
it rests on, then check whether that assumption is written down anywhere.

**2. If this fails silently, how would anyone find out?**

Most governance failures are silent. Nothing errors, nothing fails to build, the
system simply does something slightly different from what its documentation
says. If the honest answer is "a user would tell us," the change needs a test or
a log line before it merges.
