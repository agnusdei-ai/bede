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

**No bypass actors.** The rule applies to everyone, owner included. An
earlier draft carried an `actor_id: 5` RepositoryRole entry meant to read
"repository admin" — written from memory rather than checked. That fails in
the worse direction than it sounds: a wrong id does not necessarily error, it
can grant standing bypass to a role nobody picked, and the ruleset still
displays as active. The gate would report enforced while someone walks
through it. An empty list has no such ambiguity, and an emergency merge stays
available by disabling the ruleset — visible and audited, rather than a
permanent exemption nobody re-reads.

**Order matters.** The workflow restructure must be on `main` before the
gate is switched on. Enabling it first blocks every PR that doesn't touch
`homeschool-api/`.

### It found something on its first run

Removing the `paths:` filter meant `frontend-tests.yml` ran on a pull request
that touched no frontend code — and it failed immediately, on a **live
high-severity advisory**: `undici` 7.0.0–7.28.0, reachable transitively
through `jsdom`, flagged for response desynchronization and cross-user
information disclosure.

Nothing in that PR caused it. The advisory had been sitting in both
`homeschool-tutor` and `demo` lockfiles, and `npm audit --audit-level=moderate`
would have caught it on any run — except the workflow only ran when someone
touched `homeschool-tutor/` or `demo/`, and nobody had since the advisory
published.

That is the same shape as the failure this gate exists for, one layer out:
a control that was correct, present, and simply not being asked the
question. The path filter was not only a merge-blocking hazard, it was
suppressing a supply-chain gate that P15 says should be enforced by gates
rather than convention.

Fixed by bumping `undici` to 7.29.0 in both lockfiles — within `jsdom`'s
existing `^7.25.0` range, so no dependency change was needed.

### What it does not do

It does not stop a change that is wrong on its own — that is what the tests
are for. It stops a change that is right on its own and wrong in
combination, which is the failure that no single PR's CI can see.

---

## Platform verification log — observed, not inferred

**This is a log, not a gate.** Nothing here blocks a merge. It records which
platforms Bede's client path has actually been *run on* versus which it is
merely expected to work on, so "we think it works" and "someone watched it
work" stay distinguishable. That distinction disappears silently otherwise,
and the first person to discover it is a family.

**Why a log rather than a gate.** Nothing in the client is pinned to an OS
version, and every platform-sensitive path is feature-detected rather than
version-checked — `navigator.audioSession` (iOS/iPadOS 17+) is behind a
capability check with a try/catch, `getUserMedia` is called inside a real user
gesture, `h-dvh` degrades to ordinary viewport height where unsupported. So a
new OS build is not presumed broken, and blocking a release on hardware nobody
owns would be theatre. What is owed instead is an honest record.

**The rule:** an entry moves from *expected* to *verified* only when someone
ran it on that build and watched the flow. A passing test suite does not move
an entry — jsdom evaluates no CSS, no media queries and no referrer policy,
so an entire class of platform behaviour is structurally invisible to it (see
`HandwritingCanvas.tsx`'s `short:sr-only` fix and
`tests/test_youtube_embed_referrer.py`, both of which needed a real browser).

### Minimum supported version — a policy floor, not an observation

**iOS/iPadOS 15.6 is the minimum supported version** (stated 2026-08-16).
Below it, Bede is not supported on that device; no claim is made either way
about whether it happens to work.

This is a **different kind of statement** from every row in the table below,
and the two are deliberately not merged. A support floor is a decision about
what this project will stand behind. A verified row is a report that someone
watched it work. They can disagree in both directions, and here they do: the
floor is 15.6 and the lowest version actually observed is 15.8, so **15.6 and
15.7 are supported but unobserved**. Collapsing the two would either
overclaim (calling 15.6 verified when nobody has run it) or underclaim
(refusing support for versions we intend to support).

**Why 15.6 specifically is not recorded here** — the version was set by
decision, not derived from a WebKit feature this codebase can point at. If
there is a concrete reason (an API floor, a device generation, a customer
commitment), it belongs beside the number; a floor whose rationale is lost
cannot be revisited later without redoing the work that set it.

Nothing in the code enforces this. It is a statement of intent, and the
feature-detection posture described above is what actually determines
behaviour on any given build.

| Platform | Status | Note |
| --- | --- | --- |
| iOS/iPadOS 15.6 | supported, not observed | The stated floor — see above. |
| iOS/iPadOS 15.8 | verified | Older iPad, `.mobileconfig` install path. Lowest version actually run on. |
| iOS 26.6 | **expected, not yet observed** | iPhone 15. No WebKit change flagged in that release note that touches this; feature detection is the defence against version drift. Close this the first time someone runs a real session on that build. |
| Android tablet | expected | Chrome/WebView; the CA install path differs (Settings → Security → Install a certificate) and is documented in `docs/PRODUCTION_SETUP.md`. |

**Multi-device peer testing is not on this table**, and its absence is not an
untested-platform note. It is blocked on an unbuilt protocol — see
`docs/DECISIONS.md` entry 14. A verification log records what has not been
*observed*; entry 14 records what has not been *built*. Recording the second
as though it were the first would suggest a device could be tested today.
