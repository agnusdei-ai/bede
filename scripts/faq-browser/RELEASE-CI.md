# FAQ reader CI and publication boundary

## Where this check belongs

The inspected canonical repository is `agnusdei-ai/bede`. Its
`scripts/build_pages_site.sh` builds the public demo with npm and assembles
`site/` and the demo into `publish/`. `wrangler.jsonc` serves that directory
through Cloudflare. `.github/workflows/deploy-demo.yml` publishes only GitHub
Pages redirect stubs; attaching FAQ tests solely to that workflow would not
protect the canonical website.

The new `.github/workflows/faq-reader.yml` is a separate, read-only pull-request
check that tests the real static website before review/merge. It also supports
merge queues, all main-branch pushes, and manual dispatch. It needs neither
Canvas nor the API server. No hosting build command, branch rule, deployed
configuration, or GitHub setting was changed by this work.

The local proposal also adds a fail-closed check at the start of the existing
`scripts/build_pages_site.sh`, before dependency installation or output assembly.
It uses the public GitHub read API to wait up to 12 minutes for the newest
canonical FAQ run for the checked-out main SHA. The three jobs and their
current-attempt, nonempty, unexpired evidence uploads must all have succeeded.
Feature revisions, PR-only evidence, old successful runs superseded by a failed
run, missing checks and API errors block the build. A local JSON record captures
the accepted run and evidence expiry. No deployment token or new release
workflow is introduced.

The same command is also configured in Wrangler's repository-owned
`build.command` hook. This protects the normal `wrangler deploy` command even
if an external CI job bypasses the website assembly script. Worker identity,
compatibility date, asset directory and routes are unchanged. Wrangler's
custom build hook also runs during `wrangler dev`; use the existing website
preview server for local content review rather than bypassing the release
guard. Commands that deliberately skip custom builds or use a different
configuration are not an approved publication path.

## Files needed in an approved canonical release

The canonical checkout has no pnpm workspace or Canvas artifact. Include:

- `.github/workflows/faq-reader.yml`
- `scripts/faq-reader.test.mjs` (portable runtime checks)
- `scripts/faq-browser/reader.mjs`, `print-preview.mjs`, and `server.mjs`
- `scripts/faq-browser/reader-contract.mjs`, `reader-engines.mjs`, and `release-engines.mjs`
- `scripts/faq-browser/release-check.mjs`, `release-config.mjs`, and `release-config.test.mjs`
- `scripts/faq-browser/package.json` and `package-lock.json`
- `scripts/faq-browser/publication-gate.mjs`, `publication-gate.test.mjs`,
  and the guard invocations in `scripts/build_pages_site.sh` and `wrangler.jsonc`
- The reviewed print-only change in `site/assets/faq-reader.css`. Keep `site/faq/index.html`,
  `site/assets/faq-reader.js`, and `site/assets/faq-topics.js` from canonical `main`
  rather than overwriting them with workspace copies. Test against the canonical content.
- These release/readme instructions

Do not copy the workspace's root pnpm configuration into the canonical
repository or add Canvas-only tests to its release gate. The workspace-only
`scripts/package.json` commands and preview parity test are not required there.
Keep `/generated-artifacts/` ignored in Git and hosting output configuration.

## Activation requires separate owner approval

1. Review the changes locally first. Do not push this branch merely to test the
   workflow: Cloudflare branch pushes can publish the website independently of
   GitHub checks.
2. Once explicitly approved, transfer the reviewed changes to a verified
   canonical checkout and submit/run the workflow through the owner's chosen
   safe release process. A local successful run is not evidence that GitHub
   Actions itself has run.
3. After the first successful Actions run creates the check context, require
   the jobs **FAQ copy, PDF and native print cancellation**, **FAQ export parity
   (firefox)** and **FAQ export parity (webkit)** in the main-branch
   ruleset/protection. Use the exact contexts shown by that run. Do not bypass
   existing checks or temporarily disable protections. WebKit parity here means
   the Playwright engine's clipboard/fallback/print-media tests, not branded
   Safari or native macOS/iOS print-dialog certification.
4. Verify the existing Wrangler CI path actually executes the guarded build
   and stops before Wrangler when it fails. A required GitHub check controls
   merge eligibility; it does **not** by itself block Cloudflare's independent
   push-triggered deployments. Do not describe the local guard as enforced
   until the actual production path and its negative case are confirmed.

## Existing Wrangler CI release policy (local proposal, not yet active)

The owner specified the existing Wrangler CI release path. Its deployment is
reported on GitHub as **Workers Builds: bede**; repository hosting instructions
identify `scripts/build_pages_site.sh` as the build entry point. Do not create
a replacement GitHub Actions release workflow or change hosting to activate it.
Dashboard settings are not a prerequisite for local preparation.

Keep the existing Worker, build inputs, bindings, routes and Wrangler deploy
step. The existing build must exit successfully before that step can execute.
The repository guard makes that exit contingent on FAQ evidence for the
current canonical main SHA. It deliberately refuses to assemble feature-branch
revisions. GitHub API outages or rate limiting block a release; retry later,
never bypass the guard or substitute a cached success. Main moving while checks
are pending blocks the older build; build the new main instead.

The repository cannot prove that external CI lacks an alternate deployment
configuration or deliberately skips custom builds. The normal Wrangler path
has its own guard as well as the assembly guard. Before activation, confirm
its dry-run refuses a branch revision and inspect the corresponding Workers
build result. Audit other
production-capable jobs/manual triggers as well. Do not infer those controls
from the GitHub check alone. Any needed remote or hosting changes require
separate explicit approval.

Promotion must verify all three named jobs succeeded in the trusted FAQ
workflow on the exact canonical `main` SHA and that the retained evidence
belongs to that run. A green PR/merge-queue SHA, stale run, skipped job, or
missing evidence is not sufficient. If an automated merge does not emit a
push-triggered run, dispatch the workflow on `main` and verify the resulting
SHA before proceeding. Bind the Cloudflare build/version to that same tested
SHA; never promote the latest build just because it is latest. Record the
SHA, Actions run and evidence expiry, Cloudflare version and deployment IDs.
Use an approved non-publishing first run to confirm a failed/unchecked build
stops before Wrangler. A push can trigger Workers Builds: separate explicit
owner approval is still required before any push, merge or publication.

No token, secret, deployment permission, or production URL is needed by this
workflow. It does not publish or change hosting.

## Reviewing evidence

Every run attempts to upload `faq-reader-<run-id>-<attempt>` with a 14-day
retention period, even if a dependency installation or test fails. PDFs and the
clipboard-denial screenshot exist only if those scenarios reached capture;
installation and gate logs explain earlier failures.

`release-check.json` records versions, each executed check's exit code/signal,
and the final result. The workflow must stay red on missing system tools,
browser/display problems, incomplete content, clipping, skipped tests, or a
native print-dialog change. Never replace native cancellation with mocked
events to obtain a green check.

## Branch builds and superseded commits (2026-11-19)

Workers Builds runs the publication gate on every build. Two cases used to show
as a red "Workers Builds: bede" check although nothing was broken:

- **A branch build** (a pull request) is never the head of `main`, so the gate
  always refused it. `WORKERS_CI_BRANCH`, which Workers Builds sets to the branch
  it builds, now makes the gate print that nothing is published from a branch
  and exit 0. Only a named branch other than `main` skips: an absent, blank or
  `main` value runs the full gate unchanged, so a missing variable cannot turn
  the gate off. Both build entry points still call the gate unconditionally; the
  decision lives inside it (`isBranchBuild`).
- **A superseded `main` commit** (a newer commit landed while this one waited for
  evidence) is still refused and still exits 1, with a message saying it was
  superseded and that the newer commit's build publishes.

A branch build now continues past the gate and may produce a preview. Whether
previews exist is a dashboard setting (Settings, Build, Branch control); the gate
no longer decides it.
