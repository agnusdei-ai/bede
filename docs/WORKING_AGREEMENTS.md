# Working Agreements

The loops this repository actually runs on, extracted from `CLAUDE.md`.

`CLAUDE.md` is the source of truth and runs to roughly 43,000 words, which
makes it excellent for looking a fact up and poor for re-reading before you
start. This file is the short form: the recurring disciplines, what each one
is for, and the defect each was written after. Nothing here is new policy.

If this document and `CLAUDE.md` ever disagree, `CLAUDE.md` wins. Adding a
standing workflow there without adding it here fails
`homeschool-api/tests/test_working_agreements.py`, so the two cannot quietly
drift apart.

---

## 1. Delivery

*Source: `CLAUDE.md` → Standing Workflow: Root-Cause Fixes*

You found and fixed a root cause. Drive it to done rather than parking it on
a pull request.

1. **Test first**, preferring a real end-to-end check over a code-reading
   argument. Trigger the workflow for real and read the job logs instead of
   asserting the YAML looks right. If a live check is not reachable from the
   sandbox, say so explicitly rather than implying full verification.
2. **Open a PR** whose body states exactly what was verified and how.
3. **Merge it automatically.** This authorization stands until withdrawn.
4. **Tell the user** once it is merged, and live where that applies.

**The carve-out:** changes under `site/` and `demo/` replace step 3 with a
thorough self-review (`/code-review` or `/security-review`), the findings
reported, and then an explicit sign-off before merging. These are the first
thing a prospective family sees, and copy can drift from what the product
does in a way code review does not catch. Every other step still applies.

## 2. Verification

*Source: `CLAUDE.md` → Standing Workflow: Test The Function AND Its Invocation*

A function that is tested but never correctly invoked is untested in the only
way that matters.

- **Assert the call site, not just the callee.** Pass a sentinel and observe
  it arrive downstream.
- **Read the real object, never a reconstructed replica.** A replica test
  passed after the regression it guarded was deliberately reintroduced.
- **A fake looser than the real thing is not a test.** It is a second place
  for the bug to hide. Validate stubs against the real schema or model.
- **Test in the runtime that actually runs it.** jsdom evaluates no CSS
  cascade, layout, media queries, or canvas drawing, so whole classes of
  defect are structurally invisible to a component test.
- **Verify the guard by breaking the thing it guards**, and state the result
  in the PR. A test that does not fail when the behaviour regresses is
  decoration.

Written after: `bayesian_update` never passing `params`, so the values one
whole phase existed to tune were unreachable from the only path that used
them; an MCP tool sending `password` where the API requires `credential`, a
guaranteed 422 that survived because the stub accepted any JSON; an MCP
server written against the wrong SDK major that could not start at all, with
every unit test passing; `site/_headers` being correct and never actually
served.

A general "is this function ever called" scan was built and **deliberately
rejected**: 46 of 614 flagged, essentially all false positives, and a guard
that cries wolf gets deleted.

## 3. Documentation

*Source: `CLAUDE.md` → Standing Workflow: Feature Documentation*

A feature is not done until its documentation is. Same change, not a
follow-up. Route by audience:

| Change | Destination |
| --- | --- |
| Parent-facing controls and behaviour | `docs/PARENT_SETUP.md` §5, written as plain instructions to a non-technical parent |
| Anything the learner sees or uses | `docs/CHILD_GUIDE.md`, in Bede's own warm voice, no jargon |
| Setup, voice, auth, deployment, backup | The matching file in `docs/` |
| Router, frontend flow, service module, table, `SessionConfig` field, env var | `CLAUDE.md`'s `## Architecture` |
| Anything else user-facing | Somewhere it will actually be found later |

Then check whether the change made existing text stale, and fix that text in
the same change. A thorough PR description is not a substitute: pull requests
get buried in git history, documentation is what the next person reads.

## 4. Follow-through

*Source: `CLAUDE.md` → Standing Workflow: Carry Out the Decision, Don't Just Record It*

A decision is not finished when it is written down. It is finished when the
code, the documentation, and the user-facing copy all say the same thing.

1. **Finish the sweep.** If a rule now applies, apply it everywhere it holds
   in the same change. Grep for the old form and prove it is gone.
2. **Where the same fact lives twice, add the assertion that fails when they
   drift.** Do not trust the next person to remember.
3. **A spec that stays unbuilt needs a reason, not a status.** "Proposed" is
   legitimate only when the decision genuinely belongs to the founder.
   Anything blocked only on effort gets built.
4. **State what remains, and why, in the same breath.** Silence about a gap
   is what turns it into a defect nobody owns.

Written after: a model docstring claiming a feature was off by default for
four phases after the flip was recorded elsewhere; the marketing site saying
"eleven subjects" for three shipped subjects; a subject rename landing in
`models/schemas.py` and not in `site/`, twice, because those files never
conflict in git.

## 5. Decisions, and the evidence under them

*Source: `CLAUDE.md` → The Decision Register, and Standing Workflow: A Decision Backed By Research Ships The Evidence*

`docs/DECISIONS.md` carries one numbered entry per decision that shapes the
product and cannot be read off the code.

Three statuses, each carrying an obligation:

- **`open`** names what it `needs:`
- **`deferred`** names its `until:` trigger
- **`closed`** states what was `**Decided**`

A deferral without a trigger is an open entry wearing a calmer word, which is
the failure the status column exists to prevent. Tags name **who** resolves an
entry; the status names **when**. Never change a tag to make an entry feel
less blocked. Where a design document and the register would state the same
fact, the design document points at the register.

**When an entry rests on published research**, the evidence ships beside it
(`docs/PRICING_RESEARCH.md` is the pattern) under seven rules: name the study
behind every claim; state its evidence class; check editorial notices and
report the check either way; cite nothing that was not retrieved; give
contrary findings their own section; label weak evidence weak in the sentence
that uses it; state each finding's limits with the finding.

The point is not rigour for its own sake. It is knowing what the research
**cannot** tell you. A research document whose conclusion always matches what
someone already wanted to do is doing no work.

## 6. CI reachability

*Implicit in `CLAUDE.md`, and the loop every other loop passes through.*

`.github/workflows/test.yml` computes `relevant=false` and skips `api-tests`
for any path its change filter does not name.

So **any file a guard reads from outside `homeschool-api/` must appear in
that `grep -qE` pattern line**, or the guard is real everywhere except on the
change it was written to catch. The test that pins this must read the pattern
line itself: an early version grepped for the filename anywhere in the
workflow and passed on a comment sitting beside the filter, which is the
vacuous pass this repository warns about elsewhere.

## 7. The site's security headers

*Source: `CLAUDE.md` → Standing Workflow: The Site's Security Headers Are Asserted On Every Merge*

1. **Per PR, in source.** `test_site_headers.py` reads the expected set out
   of `core/middleware.py`, checks no two rules conflict, checks `_headers`
   survives the build into `publish/`, and checks `wrangler.jsonc` has grown
   neither a `main` script nor `assets.run_worker_first`. Either one silently
   stops Cloudflare applying `_headers` at all.
2. **Per merge, live.** `site-headers-live.yml` curls the real hosts, reading
   the expected set out of `site/_headers` rather than a second copy. The last
   hop is Cloudflare's own project settings, which live outside this
   repository and are invisible to CI.
3. **Both files are named in the change filter**, per loop 6.

**A red header check means fix the deployment, never delete the check.** The
source test asserts the live workflow still exists, because the only signal
that a gate has been removed is its absence.

## 8. Concurrency

*Source: `CLAUDE.md` → Standing Workflow: Never Commit Or Merge Under A Running Agent*

A delegated agent owns the files it was assigned until it reports back. A
dirty working tree during delegated work is normal and expected, not a
problem to tidy.

1. **Wait for the completion notification.** Not a poll, not a `git status`
   that looks finished, not a plausible-looking file.
2. **A tidiness prompt is not authority to commit.** A stop hook or lint
   warning describes the tree; it knows nothing about who is writing to it.
   Answer it by explaining why the tree is dirty.
3. **Confirm nobody owns the files** before committing.
4. **A cross-repository change merges as a pair or not at all.**
5. **Committing on an agent's behalf loses its evidence.** Gate exit codes,
   pass counts, and break-verification results belong in that commit message,
   and only the agent that ran them has them.

---

## The refusals

Not loops, but the constraints every loop runs inside. These outrank
convenience, and several are enforced by tests rather than trusted.

- **Never measure, score, or quantify a child's spiritual engagement**, and by
  explicit extension their character. There is no `record_virtue_evidence` and
  there must never be one. A proposal for one is a question to raise, not a
  thing to build.
- **Bede scores the work product, never the child.** Never against another
  child, against what a child that age "should" do, or against how the same
  child did last week. The third is the subtlest, because it sounds like
  encouragement.
- **Never name, guess at, or imply a diagnosis**, and never name a setting
  after a condition.
- **A blank must never look like a low mark**, and a low mark must never look
  like a blank.
- **No `ALTER TABLE` path exists.** New tables rather than new columns, frozen
  enum values, strictly additive skill maps.
- **The demo must never be looser or worse than the product it sells.**
- **Anything the server composes for a child**, or hands the model as a label,
  **is written per locale.**
- **A guard that fires on a document saying the right thing is worse than no
  guard.** Scan declarations and calls, not prose.
