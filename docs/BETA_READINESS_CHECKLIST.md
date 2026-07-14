# Beta Readiness Checklist

**Purpose:** working, collaborative checklist of what to close out before declaring
an open community beta. Not a legal document, not a spec — a punch list. Check
items off as they're actually verified (real check, not "looks right").

**Status legend:** `[x]` done & verified · `[~]` in progress · `[ ]` not started · `[!]` blocking

**Last audited:** 2026-07-14, against `origin/main` @ `dc05738`.

---

## 0. Branch hygiene (read this first)

- `[!]` **This session's working branch (`claude/clean-project-clone-s216ne`) is
  60 commits behind `origin/main`.** Main has since merged: offline `LICENSE_KEY`
  seat-gating (#81), the demo's diagnostic Phase 3–4 completion (#43/#46/#47/#73),
  a term-rotation/mastery-tracking system (#67), several UI/voice fixes (#48–#90).
  A prior concurrent session already collided once on `DIAGNOSTIC_BUILD_PROGRESS.md`
  (duplicate Phase 4 build, reconciled in `cd4dca1`) — same collision risk exists
  for anything still in flight on this branch. **Rebase this branch onto
  `origin/main` before merging anything else**, and re-run the full backend
  suite afterward to catch any silent behavioral drift (e.g. the model-provider
  refactor vs. whatever `ai_service.py` looks like on main now).

---

## 1. Security

- `[x]` AES-256-GCM at rest, MASTER_SECRET → KEK → DATA_KEY hierarchy, encrypted
  audit log independent of request transactions.
- `[x]` JWT IP+UA fingerprinting, constant-time credential comparisons.
- `[x]` `ExfiltrationGuard` blocks known dump endpoints + scans buffered JSON
  responses for leaked key material.
- `[x]` Containers: no-shell user, `read_only: true`, `cap_drop: ALL`.
- `[x]` Offline license verification (`LICENSE_KEY`) gates seat count in
  production — no phone-home, no telemetry.
- `[!]` **No automated dependency-vulnerability scanning.** No Dependabot config,
  no `pip-audit`/`npm audit`/`safety`/CodeQL step anywhere in `.github/workflows/`.
  With `anthropic`, `resemblyzer`, `openai-whisper`, `webauthn`, `pyotp` etc. as
  live attack surface, this should exist before external users install it.
- `[!]` **Rate limiting is in-process, in-memory, per-IP, no eviction**
  (`core/middleware.py`: `AUTH_LIMIT=10`, `API_LIMIT=120`, `VOICE_LIMIT=20` per
  minute). Fine for a single LAN box. If beta users ever run multiple workers/
  replicas, or the process restarts under load, limits silently reset or stop
  being shared. Confirm this is acceptable for the beta's actual deployment
  shape (self-hosted single-instance, presumably yes) and document the
  assumption explicitly so nobody scales it wrong later.
- `[ ]` No `SECURITY.md` / vulnerability-disclosure process for external
  reporters — worth adding before inviting a wider community to poke at it.

## 2. Legal / Compliance

- `[!]` **Parent agreement gate ships with placeholder legal text**
  (`core/parent_agreement.py`, `CURRENT_VERSION = "2026-07-13-draft"`,
  module docstring literally says "DRAFT — PENDING LEGAL REVIEW"). Blocking:
  swap in the Perplexity Pro + attorney-reviewed text and bump
  `CURRENT_VERSION` before beta — bumping the version automatically re-prompts
  every parent who accepted the draft.
- `[!]` Confirm minor-waiver enforceability with the attorney for whichever
  jurisdictions beta users will actually be in — as discussed, a pre-injury
  waiver signed by a parent is often *not* enforceable against the child's own
  future claim in many US states; the agreement's framing (assumption of risk +
  platform-scope disclosure, not a liability shield) should be attorney-confirmed
  as the right structure, not just the wording.
- `[ ]` No COPPA-specific documentation or COPPA compliance review on record,
  despite this being child-directed software collecting voice biometrics and
  session data. Worth an explicit attorney pass given voice enrollment counts as
  biometric data under several state laws (Illinois BIPA, Texas CUBI, etc.) —
  even for a self-hosted LAN deployment, this may apply depending on where
  families run it.
- `[ ]` No user-facing Privacy Policy or Terms of Service document (the repo
  `LICENSE` is a proprietary software license, not a privacy policy). If beta
  users are outside your household — i.e. an actual "open community beta" —
  they'll expect one.
- `[ ]` No comprehensive "export/delete all data for a family" capability.
  Only per-student `DELETE /pod/configs/{name}` and `DELETE /voice/profiles/{name}`
  exist — there's no single "erase this family's account entirely" action a
  parent (or you, on request) can take. Worth having even absent a formal GDPR
  requirement, since you're collecting biometric + educational records on minors.

## 3. Data Safety / Backup / Recovery

- `[x]` `make db-backup` / `make db-restore` documented and exercised in
  `production-regression.yml` (local-Postgres mode).
- `[!]` **No documented disaster-recovery story for `MASTER_SECRET`.** If a
  self-hosting parent loses `.env` (disk failure, botched reinstall) without a
  separate backup of `MASTER_SECRET`, every encrypted row — voice profiles,
  student configs, audit log — becomes permanently unrecoverable, even with a
  valid `db-backup` dump in hand (the dump is ciphertext). `PRODUCTION_SETUP.md`
  should say this in bold, and `make db-backup` (or a new `make backup-secrets`)
  should make backing up `.env` alongside the DB dump procedural, not implicit.
- `[ ]` No automated/scheduled backup — `make db-backup` is manual, on-demand.
  For non-technical beta parents this likely means backups never happen unless
  prompted. A cron-friendly wrapper or a setup-wizard nudge would close this.

## 4. Testing / CI

- `[x]` Backend: 335 tests passing, 7 skipped (confirmed: skips are only because
  no local Postgres is reachable in this sandbox — `test.yml` runs a real
  `postgres:16` service, so these pass for real in CI).
- `[x]` `production-regression.yml` covers managed/local DB modes, setup wizard
  image build + form submission, `.env` generation, full-stack health check,
  no-CLI tablet-trust flow, backup/restore.
- `[!]` **No frontend test runner configured at all** — no Vitest/Jest, no
  `.spec.`/`.test.` files, nothing in CI for `homeschool-tutor/` or `demo/`
  beyond `tsc`/`vite build` type-checking. Every frontend fix this session
  (TTS silence bug, upload guardrails, parent-agreement gate) was verified by
  hand via Playwright, not by a repeatable test. For a wider beta, at minimum
  the high-risk flows (auth redirect/`returnTo`, SSE streaming state machine,
  the new parent-agreement gate, voice enrollment/verify) deserve real
  component or Playwright-in-CI tests so regressions don't ship silently.
- `[ ]` No accessibility testing in CI (axe-core, Lighthouse CI, etc.) — see §8.

## 5. Documentation

- `[x]` `PRODUCTION_SETUP.md`, `PARENT_SETUP.md`, `CHILD_GUIDE.md`,
  `VOICE_SETUP.md`, `MODEL_PROVIDERS.md`, `DEVELOPMENT.md`, `DEMO_HOSTING.md`
  all present and current.
- `[ ]` No public-facing "known limitations" doc for beta users (e.g. "voice
  biometrics can be spoofed by a good enough recording," "rate limits assume
  single-instance," "not a diagnostic/screening tool" — the platform-scope
  parts of the parent agreement, surfaced separately as a README-level doc
  rather than only inside the gate).
- `[ ]` No `CONTRIBUTING.md` / issue templates for a genuinely *open* community
  beta (there's `docs/CONTENT_CONTRIBUTING.md` — check what it actually covers;
  worth confirming it's the right scope or whether a code-contribution guide is
  also needed).

## 6. Child Safety / Platform Scope

- `[x]` Parent-agreement gate: explicitly states platform is not a diagnostic/
  screening tool for ADHD/autism/etc., frames itself as a hands-off-for-2-hours
  supplement to parent-led homeschooling, not a special-needs accommodation
  product.
- `[x]` Voice biometric session-start authentication for children.
- `[~]` `LearnerProfileData` (trivium_stage/processing_style/narration_mode/
  attention_profile) is narration-history-based profiling, not diagnostic —
  but it's adjacent enough to behavioral signal that it's worth a quick legal
  sanity check alongside the main agreement review: does its existence need a
  mention in the parent agreement's "No Diagnosis, No Screening" section, even
  though it wasn't built for that purpose?
- `[ ]` Handwriting-form-assessment feature (letter formation / cursive
  legibility as a distinct rubric) — only sketched during this project, never
  built or scoped-in. Not a beta blocker; flagging so it doesn't get implicitly
  assumed as "already covered" by the existing content-focused narration
  assessment.

## 7. Deployment / Ops

- `[x]` Caddy (TLS) → nginx → FastAPI stack, documented setup wizard, tablet-
  trust flow, offline license/seat gating.
- `[x]` `deploy-demo.yml` / `keep-demo-warm.yml` for the public demo.
- `[ ]` No stated support/feedback channel for beta users beyond the in-app
  `routers/feedback.py` lead-capture form — confirm that's actually monitored
  and has an SLA-ish expectation set before external users rely on it.

## 8. Accessibility

- `[~]` Some `aria-`/`role`/`<label>` usage present across pages (`Login.tsx`,
  `ParentSetup.tsx`, `Progress.tsx`, `Sandbox.tsx`, `TutorSession.tsx`) but not
  audited against WCAG systematically, and no automated a11y check (axe,
  Lighthouse CI) exists to catch regressions. Given the user base includes
  children operating tablets largely through voice/speech interfaces already,
  a real pass here (contrast, focus order, screen-reader labels on the tool
  cards) is worth doing before a wider audience arrives.

## 9. Known Open Items (non-blocking, but should be visible before beta)

- `[ ]` Diagnostic engine Phase 5 (validation & tuning against a real live
  session corpus) not started — Phases 1–4 are complete and shipped on `main`
  (confirmed directly: `record_skill_evidence`, `routers/diagnostic.py`, and the
  parent-facing mastery summary in `Progress.tsx` all exist and are wired up).
- `[ ]` Extending the skill map beyond math (writing, logic) — explicitly
  scoped as a future follow-up, not beta-blocking.

---

## Suggested priority order to clear before "open community beta"

1. Rebase this branch onto `main` (§0) — do this first, everything else should
   be audited against the merged result, not a stale branch.
2. Finalize + swap in attorney-reviewed parent-agreement text; get the
   minor-waiver structure and COPPA/biometric-data exposure explicitly
   confirmed (§2).
3. Document the `MASTER_SECRET` backup story in bold in `PRODUCTION_SETUP.md`
   (§3) — cheap to fix, catastrophic if skipped.
4. Add dependency-vulnerability scanning (Dependabot at minimum) (§1).
5. Decide how much frontend test coverage is a pre-beta requirement vs.
   fast-follow (§4) — this is a judgment call on risk appetite, not a hard gate.
6. Add a Privacy Policy / Terms doc and a "known limitations" doc for external
   users (§2, §5).
7. Everything else (§1 SECURITY.md, §6 LearnerProfileData legal check, §8
   accessibility) — good to close before beta, not launch-blocking on their own.
