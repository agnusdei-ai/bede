# Release quality gates

What must be true before a change reaches `main`. One gate today; this file
is where further ones get recorded rather than living in someone's memory.

## Gate 1 — a branch must be up to date with `main` before it merges

**Status: configured in `.github/rulesets/main-branch-protection.json`,
requires a repo admin to import it.** Branch protection is not
repo-as-code on GitHub, so the file in this repo is the reviewable source of
truth and applying it is a manual action. See "Applying it" below.

### Why

On 2026-08-03, `main` went red with no bad commit in it.

PR #364 added `POST /admin/ai-provider/secondary`. PR #366 added
`tests/test_app_composition.py`, which requires every endpoint to carry a
deliberate entry in a guard table — a test written precisely because
mutation testing had shown that unmounting a security middleware or
downgrading an endpoint's guard left all 1,603 tests green.

Each PR passed CI on its own. Neither PR's CI could see the other, because
neither branch contained the other's commit. They merged minutes apart and
`main` broke on the combination: an endpoint existed that the guard table
had never been told about.

Nothing was wrong with either change. The gap was that **CI validated a
state that never shipped** — each branch as it existed before the other
merged, rather than the state `main` would actually be in.

Requiring the branch to be up to date closes that: the PR must contain
current `main`, and its checks re-run against the merged state before the
merge button unlocks.

### What it costs

Every merge to `main` invalidates every other open PR, each of which then
needs an update and a full CI re-run. With the backend suite at roughly
2 minutes and several PRs open, that serialises merges.

That is the correct trade for this repo today: it holds children's data,
and the class of bug this catches — a security control that is present,
correct, and not wired to anything — is exactly the class the guard tables
exist for. Revisit if merge throughput becomes the binding constraint;
GitHub's merge queue is the standard next step, and it tests the merged
state without serialising humans.

### The prerequisite that is easy to get wrong

**Every required check must START on every pull request**, whether or not it
has work to do.

GitHub blocks a PR whose required check never reports — it sits on
"Expected — waiting for status to be reported" indefinitely. It does not
treat "did not run" as "passed". Before this gate, every PR workflow in this
repo carried a `paths:` filter on its `pull_request` trigger, so a
docs-only PR would have become **permanently unmergeable** the moment the
gate was switched on.

`test.yml` and `frontend-tests.yml` were restructured for this: the
`pull_request` trigger no longer filters by path, and a small `changes` job
decides whether the heavy jobs run. A **skipped** job satisfies a required
check; a job that never ran does not. That distinction is the entire reason
for the restructure.

The `changes` job uses plain `git diff` rather than a third-party
paths-filter action — P15 (supply-chain integrity is enforced by gates, not
convention) says a CI gate should not quietly add an external dependency to
save nine lines of shell. It fails open: anything that is not a pull request
runs the full set, so the skip is a PR-only optimisation and a bug in it
costs CI minutes rather than coverage.

**Do not re-add a `pull_request` `paths:` filter to a workflow named in the
ruleset.** Doing so re-arms the permanently-blocked-PR failure.

### Applying it

Either import the ruleset:

> GitHub → Settings → Rules → Rulesets → New ruleset → Import a ruleset →
> `.github/rulesets/main-branch-protection.json`

or apply it directly:

```sh
gh api -X POST /repos/agnusdei-ai/bede/rulesets \
  --input .github/rulesets/main-branch-protection.json
```

Then confirm it took effect — editing the file changes nothing on its own:

```sh
gh api /repos/agnusdei-ai/bede/rulesets
```

**Order matters.** The workflow restructure must be on `main` before the
gate is switched on. Enabling it first blocks every PR that doesn't touch
`homeschool-api/`.

### What it does not do

It does not stop a change that is wrong on its own — that is what the tests
are for. It stops a change that is right on its own and wrong in
combination, which is the failure that no single PR's CI can see.
