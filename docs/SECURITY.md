# Security & Compliance Posture

This documents Bede's security architecture in terms auditors and
compliance frameworks ask for — a companion to the code-level description
in `CLAUDE.md`'s "Security Constraints" section, not a replacement for it.
Like `docs/DATA_RETENTION.md`, this is a factual description of what the
code does, **not legal advice or a certification** — neither AIUC-1 nor
SOC 2 compliance can be established by a document; both require an
accredited third-party auditor's opinion after a live assessment. If
something has actually gone wrong (or you've found a vulnerability in
Bede's code), see **[docs/INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)**
instead — this file is the architecture/posture overview, that one is the
action plan. See **[docs/OWASP_LLM_TOP10.md](OWASP_LLM_TOP10.md)** for the
companion mapping against the OWASP Top 10 for LLM Applications.

## AIUC-1 Society pillar: scope statement

AIUC-1's Society pillar addresses the risk that an AI agent could be
misused to facilitate cyberattacks or CBRN (chemical, biological,
radiological, nuclear) harm. Bede is assessed as **out of scope / low
inherent risk** for this pillar, for reasons that are architectural rather
than policy-based:

- **No code execution, shell, or open web-fetch tool is ever exposed to
  the model.** Bede's entire tool surface is nine fixed, narrowly-scoped
  tools — `request_narration`, `invite_handwriting`, `offer_socratic_hint`,
  `celebrate_discovery`, `connect_to_faith`, `show_visual_aid`,
  `assess_narration`, `suggest_next_subject`, `record_skill_evidence` (see
  `CLAUDE.md`'s "Agentic tools include" section) — none of which can
  execute arbitrary code, reach the network, or touch the filesystem
  beyond its own database rows.
- **The domain is closed.** Bede tutors a fixed set of K-8 Catholic
  Classical subjects (`services/ai_service.py`'s `_SUBJECT_CONTEXT`); it
  has no general-purpose assistant mode to redirect toward attack
  tooling or CBRN uplift content.
- **The deployment is single-tenant and LAN-scoped.** Each family runs
  its own instance (see `docs/PRODUCTION_SETUP.md`); there is no shared,
  internet-facing multi-tenant surface an attacker could pivot through.
- **The constitution's non-negotiable rules are a second, independent
  layer on top of the architectural limits above** — `core/constitution.py`
  verifies a SHA-256-pinned, structurally-validated constitution at every
  startup (see `docs/CONSTITUTION.md`), and `ai_service.py`'s
  `<ethical_boundaries>` prompt rules explicitly refuse role changes,
  system-prompt disclosure, and out-of-scope requests.

This reasoning has **not** been validated by third-party adversarial
testing (see the open Safety-pillar gap below) — it documents why the
architecture makes this pillar low-risk by construction, not that the
absence of these harms has been independently red-teamed.

## Known open gaps

Tracked here so they don't only live in a one-off review; update this
list as items are closed.

- **Pre-deployment adversarial testing — still not independent.** Two
  passes now done (see Closed gaps): a static-layer review of the
  deterministic regexes, and a real live-model probe against the actual
  constitution/`<ethical_boundaries>` (`scripts/adversarial_probe.py`,
  `docs/adversarial-probes/`). What's still missing, and structurally out
  of scope for in-house testing regardless of environment: a **third-party**
  red-team or independent adversarial-robustness assessment — AIUC-1's own
  control language calls for an outside organization specifically, and
  this remains the same tooling that helped build the system, testing
  itself. `scripts/adversarial_probe.py` is a real, reusable asset for
  that engagement (or for periodic in-house re-runs between engagements),
  not a replacement for it.
- **Environment/infrastructure pentesting — not yet run.** Everything above
  covers the tutoring persona; nothing has yet independently verified that
  the *deployed* environment (network exposure, auth/session binding, rate
  limiting, container hardening, TLS config, encryption at rest) actually
  holds up the way its code reads. `docs/environment-pentests/README.md`
  tracks this — same in-house-not-independent caveat applies, and same
  git-SHA-pinned tracking format as the adversarial probes above, so
  findings can be correlated release-to-release once testing starts.
- **Parent MFA is opt-in, not required.** WebAuthn/TOTP only gate login once
  a parent has separately enrolled a method (`services/mfa_service.py`) — a
  family that never visits MFA setup runs single-factor (password only) on
  the role that can view/delete all student data and the audit log.
  Whether to require enrollment (and the UX for a family locked out of
  their only factor) is a product decision, not a pure code fix — flagged
  here rather than changed unilaterally. Account recovery for that
  locked-out case is now closed (see Closed gaps), which removes the
  biggest objection to eventually requiring MFA — it no longer means "one
  lost device bricks the account."
- **Child role has no lockout/recovery scheme — and deliberately still
  won't.** The recovery half of this remains correct and unchanged: the
  single-tenant design makes the parent the ultimate authority over the one
  shared child credential, so "recovery" for a child is "ask a parent to
  change `CHILD_PIN`", a capability that already exists. What this entry
  previously got wrong was treating that as also answering brute force —
  it doesn't. Nothing about recoverability makes a 6-digit PIN harder to
  guess, and the per-IP rate limiter keys on IP alone, which a LAN attacker
  defeats trivially. That half is now closed by escalating-delay throttling
  rather than a lockout (see Closed gaps, and `core/child_throttle.py` for
  why a lockout would have been the wrong instrument here).
- **`RateLimitMiddleware` and the E009 anomaly watch are in-memory,
  per-process — same class of gap already disclosed for
  `services/streaming_transcription.py` and the OpenAI TTS httpx pool
  (`docs/VOICE_SETUP.md`), but never previously stated for rate
  limiting/anomaly detection specifically.** On a horizontally-scaled
  deployment, the effective limit becomes `limit × instance count` and the
  anomaly thresholds become correspondingly easier to stay under by
  spreading requests across instances. Not a gap for this app's actual
  target (a self-hosted single-family instance, or the demo's current
  single-instance Render deployment) — would need a shared store (Redis)
  behind a real multi-replica deployment, which nothing in this app runs
  today.
- **Branch-protection / required-status-checks configuration on `main` is
  not verifiable from the repository itself** — it's a GitHub repo-settings
  concern, not a file in this codebase. `frontend-tests.yml`'s own header
  comment documents a real past instance of this gap (PRs #182/#185 merged
  with zero CI checks run, before that workflow existed to cover
  `homeschool-tutor/`/`demo/`). Worth confirming directly in GitHub
  settings — required checks and force-push protection — before a
  production release; not something a code change can confirm or fix.
- **`production-regression.yml`'s "Confirm the license is ACTIVE" step is
  non-blocking (`continue-on-error: true`), so CI can silently stop proving
  the license gate actually works.** `CI_TEST_LICENSE_KEY` went invalid
  (bad signature against `core/licensing.py`'s `PUBLIC_KEY_PEM` — not
  simple expiry) and stayed that way across many runs, because reissuing it
  needs the offline private signing key (`docs/PRODUCTION_SETUP.md
  #licensing`) that nothing in CI holds — left blocking, this one stale
  secret also skipped every step after it (tablet-trust page, Postgres
  backup/restore), throwing away real coverage over an unrelated problem.
  The step still runs and still reports failure in the Actions UI, but a
  human with that private key has to notice and act on it — nothing
  enforces that anymore. Worth periodically confirming this step is
  actually green, not just that the workflow overall is.
- **A proposed Bede↔Locuto content-agent connector has one remaining
  unresolved pre-implementation blocker, tracked in
  [`docs/LOCUTO_CONNECTOR_DECISIONS.md`](LOCUTO_CONNECTOR_DECISIONS.md).**
  No such connector exists yet, and this is infrastructure ahead of a
  feature, not a gap in anything shipped today. Packet 1 (which adapter a
  Locuto-content-touching capability may call) is resolved —
  `services/adapters/router.py`'s `resolve_local_only()` exists and is
  tested, independent of `BEDE_ADAPTER_ORDER`/`BEDE_FORCE_ADAPTER`/any live
  DB override. Packet 2 remains open: Bede has no
  signed-release/reproducible-build/hash-pinned-weights infrastructure
  matching `agnusdei-ai/locuto`'s own `docs/agents.md` §5 measurement
  requirement for a locally-composed agent. See that document for the full
  options and recommendation — pending a decision from both products'
  owners, and moot until `agents.md` §9 open question 1 (whether a content
  agent ships at all) resolves.

## Closed gaps

- **GitHub Actions were pinned to mutable version tags (`@v4`), not commit
  SHAs — closed 2026-08-12.** A compromised upstream Action could push a
  same-tag update that CI would trust automatically next run, with nothing
  in this repository able to tell that update apart from one a maintainer
  actually reviewed. `dependabot.yml`'s `github-actions` entry doesn't
  cover this — `open-pull-requests-limit: 0` suppresses routine
  version-bump PRs, leaving only security-advisory PRs, so a mutable tag
  can still move silently between those.

  Every `uses:` line across all nine workflow files now pins the exact
  commit SHA the tag resolved to, with the tag kept as a trailing comment
  (`uses: actions/checkout@<sha> # v4`) — the standard pattern for this
  hardening. Resolved via `git ls-remote --tags` against each action's own
  repo, peeling annotated tags to their underlying commit where needed
  (`azure/login`, `azure/artifact-signing-action`,
  `anthropics/claude-code-action`). Bumping to a newer release now means
  re-resolving and replacing both the SHA and its comment, not editing a
  version number.

- **Backend `requirements.txt` was floor-pinned (`>=`, no upper bound),
  with no lockfile — closed 2026-08-12.** Unlike the frontend's
  exact-pinned `package-lock.json`, a fresh `pip install` at two different
  points in time could resolve different transitive versions, and
  `test.yml`'s `pip-audit` step could only catch a *known-vulnerable*
  version whenever one happened to be resolved — installs were never
  reproducible.

  `homeschool-api/requirements.txt`/`requirements-dev.txt` are renamed to
  `requirements.in`/`requirements-dev.in` (pip-tools' own convention),
  kept as the human-edited, floor-pinned *source of intent* they already
  were. `requirements.lock.txt`/`requirements-dev.lock.txt` are new,
  fully-pinned, hash-verified lockfiles generated via `pip-compile
  --generate-hashes --allow-unsafe` (Python 3.12, matching CI —
  `--allow-unsafe` is what also pins `setuptools`, which
  `ctranslate2`/`torch` need exactly once hashes are in play).
  `test.yml`'s `api-tests`/`demo-concurrency-test` jobs and
  `adversarial-probe.yml` now install from the lockfile
  (`pip install --require-hashes -r requirements-dev.lock.txt`), so CI
  tests byte-for-byte what a fresh install produces, not whatever the
  resolver picks that day. `pip-audit` now audits the lockfile too, for
  the same reason.

  A new `lockfile-freshness` job (`test.yml`) and script
  (`homeschool-api/scripts/check_lockfile_freshness.sh`) regenerate both
  lockfiles into a temp directory and diff against what's committed,
  failing the build on drift — the guard against this becoming another
  "looks maintained but silently isn't" config, per CLAUDE.md's "Thirty
  settings never reached the container" incident. Run locally with
  `--fix` to regenerate both after editing either `.in` file.

  `homeschool-api/Dockerfile` still installs from `requirements.in`
  (rename only, behavior unchanged): its CPU-only-`torch` install relies
  on resemblyzer's transitive `torch` dependency rather than an exact
  hash, and switching it to the lockfile wasn't verifiable here — the
  sandbox's egress proxy blocks `download.pytorch.org`. Verified end to
  end otherwise: the lockfile was generated for real, and `pip install
  --require-hashes -r requirements-dev.lock.txt` succeeded against a
  clean virtualenv before this was considered done.

- **Public demo had no hard per-visitor cost ceiling — OWASP LLM10
  "Unbounded Consumption" — closed 2026-08-12.** `core/demo_code_session.py`'s
  own module docstring previously stated "No per-code message cap by
  design," reasoning that `_MAX_ACTIVE_CODES` (concurrent codes) and the
  per-IP `RateLimitMiddleware` "api" bucket (120 req/min default) were
  sufficient cost control. Neither bounds aggregate spend: the rate limit
  caps REQUEST RATE, not total messages, so a single scripted session
  sustained at that ceiling for its whole `demo_code_token_expire_minutes`
  token lifetime (120 min default) could sustain roughly 14,000 real model
  calls from one demo code — a genuine denial-of-wallet surface with no
  dollar or message-count floor underneath the rate limit, on the one
  publicly-reachable, unauthenticated-signup surface this codebase has.
  `core/demo_code_session.py` now adds `_MAX_MESSAGES_PER_CODE` (400 — well
  above any real evaluation, see that constant's own comment) and
  `has_message_quota()`, a read-only pre-check kept deliberately separate
  from the existing `record_message()` counter so the ENFORCEMENT happens
  before the expensive model call a turn triggers, not after: an
  over-quota turn is refused for free, never billed. Wired into both
  `routers/tutor.py`'s `/tutor/chat` and `routers/sandbox.py`'s
  `/sandbox/demo-chat` — the two call sites that were already logging
  "usage bookkeeping only — no cap enforced" verbatim — ahead of the
  safeguarding/moderation/policy-engine pipeline, so a refused turn costs
  nothing beyond one DB read. The refusal is a plain, localized (en/es)
  chat message (`services/ai_service.py`'s `demo_quota_response`, same
  fallback contract as `safeguarding_response`/`moderation_redirect_response`)
  rather than an HTTP error, matching how every other pre-model gate in
  these two SSE endpoints already communicates a redirect to the child/
  visitor's own chat window, and is audit-logged as `AuditEvent.RATE_LIMITED`
  with `detail="demo_message_quota"`. `core/diagnostic_preview_quota.py`'s
  own docstring (which referenced the old "uncapped in duration and message
  count" framing) was corrected in the same change. Duration and subject
  BREADTH remain deliberately uncapped — a full, real evaluation is still
  the point, not a crippled preview; only aggregate message volume per code
  is now bounded. See `CLAUDE.md`'s demo-session documentation and
  `tests/test_demo_message_quota.py`.

- **The setup wizard recommended a PIN the API refuses to boot on —
  closed 2026-08-03.**
  Hardening rejected `602656` as a `CHILD_PIN` at startup, which is
  correct: it had been this repository's published example, printed in
  `.env.example`, `setup.sh`, the setup wizard's own hint text and input
  placeholder, `docs/PARENT_SETUP.md`, `docs/DEMO_HOSTING.md`, and the
  error messages that told a parent what a good PIN looks like. A value
  on GitHub is not a secret.

  The rejection landed in `core/config.py` and nowhere else. The wizard
  kept printing "e.g. 602656 is a good one" and kept accepting it,
  because its own check was `pin_is_strong()`, which passes: the PIN is
  well-shaped, and shape was never the problem. So a parent who followed
  the installer's on-screen advice got an `.env` the installer called
  valid and a container that then refused to start, reporting that their
  PIN was "the default dev value." `setup.sh` had the identical defect on
  the terminal path. `config.py`'s own error messages recommended
  `602656` inside the same validator that rejected it, so following the
  error's advice led to the other branch of the same failure.

  It also broke the deployment regression suite, which drives the wizard
  exactly as a parent would. `main` was red for five consecutive runs,
  and every one of them was this.

  The fix is structural rather than textual. Both rules now live in
  `core/pin_policy.py`, the one module the API and the wizard already
  share (the wizard runs in a pydantic-free container and copies just
  that file): `pin_is_strong()` for shape, and `is_published_credential()`
  for whether the exact value has been printed publicly. Two different
  questions, deliberately kept apart, since a published value can be
  perfectly well-shaped. `homeschool-api/tests/test_wizard_and_api_agree_on_credentials.py`
  asserts the invariant directly — **the wizard must never accept a
  credential the API will refuse to boot on** — in both directions,
  including submitting the form and constructing `Settings` from the
  `.env` it produces. No interface names a concrete PIN any more: both
  installers generate a fresh suggestion per run, which is the only kind
  of example that stays usable. `setup.sh`'s bash copy carries the same
  list, verified by running its generator against its own checker.

- **Thirty settings never reached the container, including every value
  security keys depend on — closed 2026-08-03.**
  `docker-compose.yml`'s `api` service passes environment variables by
  naming them one at a time rather than using `env_file`, which is a
  reasonable choice: the list is a reviewable statement of what the
  container actually receives. Its own comment states the obligation that
  follows — "anything set in `.env` and NOT named here is silently
  dropped. A knob documented in `.env.example` that does nothing is worse
  than no knob at all" — but nothing enforced it, and 22 documented
  settings had drifted off the list.

  The security-relevant ones: `WEBAUTHN_RP_ID`, `WEBAUTHN_RP_NAME` and
  `WEBAUTHN_ORIGIN`, which together decide whether FIDO2 security keys
  exist at all. `mfa_service.webauthn_enabled()` is `rp_id and origin`,
  with no fallback derivation, so with both dropped every packaged
  deployment reported `webauthn_available: false` and refused both
  enrollment and authentication, no matter what the parent had put in
  `.env`. The documented second factor was unreachable in practice. TOTP
  runs through a separate path and was unaffected, so MFA as a whole
  still functioned, which is part of why this went unnoticed. Also
  dropped: `TOTP_ISSUER`, all five `RATE_LIMIT_*` buckets (so the tuned
  per-endpoint limits documented here and in `docs/VOICE_SETUP.md` ran at
  code defaults), both `VOICE_THRESHOLD_*` speaker-verification
  thresholds, and `RETAIN_MASTERY_PROFILES`, whose value the setup wizard
  had begun asking a parent for that same day.

  The shape of this defect is what makes it worth recording rather than
  the individual settings. It is silent in both directions: nothing
  errors, pydantic falls back to the code default, and the deployer sees
  a running system that ignores them. In a self-hosted product that is
  the worst available failure mode, because the person affected cannot
  distinguish "I configured it wrong" from "this was never wired up."
  Closed by wiring the missing variables and by
  `homeschool-api/tests/test_compose_settings_passthrough.py`, which
  fails when a setting documented in either `.env.example` is absent from
  the list, when a default written in compose disagrees with the one in
  `core/config.py`, or when a variable in the list is not a real setting.
  Verified with `docker compose config` against a sample `.env` rather
  than by reading the YAML.

- **"Parent" was administrator for the whole session — mechanism built
  2026-08-03, enforcement closed 2026-08-04.**
  One role was simultaneously the ordinary account identity — adjusting
  today's plan, sitting with a child, reading a narration — and the fully
  privileged administrative one: reading the audit log, repointing the AI
  provider at a different vendor, deleting a security key, permanently
  destroying a student's data. Same token, same scope, for up to eight
  hours. A session left open on an unattended tablet was not just logged
  in, it was administrator, and none of those actions needed the password
  the parent typed once that morning.

  `core/elevation.py` adds a step-up: management-plane actions require an
  elevation granted by re-presenting the password (plus a TOTP code where
  TOTP is enrolled) at `POST /auth/elevate`, valid for
  `ELEVATION_TTL_MINUTES` (default 10) and keyed to that one session. What
  it covers: the audit log, licensing, the AI provider, every
  authentication/recovery factor change, and permanent student deletion.
  What it deliberately does not cover is the ordinary parent day —
  requiring a password to read a narration would train a parent to retype
  it reflexively, which is how step-up stops being a signal.

  Two limits worth stating rather than burying. This raises the cost of a
  **stolen session** — a token lifted from an open tab, a shared device, an
  XSS replay — not of a stolen password; someone with the password can
  elevate too. And **WebAuthn is not required at the step-up** even when
  enrolled, because verifying a security key needs its own
  challenge/response endpoint pair the way login does; a WebAuthn-only
  deployment elevates on the password alone. That is the next increment,
  not a decision.

  `/auth/elevate` sits under the same per-IP auth rate limit and the same
  `parent_lockout` as `/auth/login`, deliberately: an endpoint that compares
  a submitted password is a password oracle whether or not the caller
  already holds a session.

  **Enforcement closed 2026-08-04.** `homeschool-tutor/src/components/
  ElevationPrompt.tsx`, mounted once at the app root next to
  `GlobalAuthInterceptor` (the existing 401-handling interceptor — same
  technique, same reason), wraps `window.fetch` and catches the 403 an
  unelevated call returns (`core/deps.py`'s `{elevation_required: true}`
  marker). It prompts for the password — and a TOTP code, if enrolled,
  fetched via `GET /mfa/status` — calls `POST /auth/elevate` itself, and
  retries the original request exactly once on success; a cancelled or
  failed elevation returns the original 403 unchanged, so each call site's
  existing error handling still applies as the fallback. Concurrent
  elevation-gated calls (e.g. a settings page loading the audit log and the
  AI-provider status together) share one in-flight prompt rather than
  opening two or orphaning the first request's promise. No individual call
  site needed to change. `ELEVATION_ENFORCED` now defaults `true`
  (`core/config.py`, `docker-compose.yml`, `.env.example`); a deployment can
  still set it `false` to opt out (e.g. one driving the API directly with no
  frontend). `GET /admin/status` reports the current posture either way.
  Covered by `homeschool-tutor/src/components/ElevationPrompt.test.tsx`.

- **A lost or stolen tablet could not be individually revoked — Option C
  closed 2026-08-04.** The JWT's `SHA-256(IP | User-Agent)` fingerprint
  (P10) binds a token to the device that requested it, but binding is not
  identity: nothing recorded which physical devices a family's tokens had
  ever been issued to, so the only way to lock out one compromised or
  missing tablet was to rotate `PARENT_PASSWORD`/`CHILD_PIN` for
  everyone. `docs/DEVICE_IDENTITY_DESIGN.md` records the fuller design
  space (Options A/B/C) and recommends C first — this is that build, not
  the browser-keypair Option A the design doc still lists as open.

  `core/device_registry.py` follows the exact "DB-backed fact, cached
  in-process, refreshed periodically" shape `core/parent_credential.py`
  already established for `credentials_version`: a new `DeviceRecord`
  table (`core/database.py`) holds one row per device (`device_id`,
  first/last seen, last role, last user-agent, `revoked`), the in-process
  cache is a plain `set` of revoked ids refreshed every 10 seconds
  (`periodic_refresh()`, started from `main.py`'s lifespan) so a check on
  the hot request path is a sync membership test, never a DB round trip.
  `device_id` is a client-generated, opaque, non-secret UUID
  (`homeschool-tutor/src/utils/deviceId.ts`, `localStorage`-backed so it
  survives a browser restart) sent on login and folded into the issued
  JWT — it identifies hardware, not a person, and proves nothing on its
  own.

  Two enforcement points, deliberately different in shape. `routers/
  auth.py`'s `login()` rejects a revoked device, but only **after** the
  submitted credential has already verified — `_reject_if_device_revoked()`
  is called after `parent_lockout.record_success()`/`child_throttle.
  record_success()`, never before. An earlier draft checked revocation
  first, which would have made `/auth/login` a **pre-authentication
  oracle**: an attacker could learn whether a specific `device_id` was
  revoked without ever presenting a valid password, simply by watching
  which of two 401 messages came back. `test_a_wrong_password_never_
  reveals_device_revocation_status` pins byte-identical 401 detail text
  for a wrong password against a revoked device versus a never-registered
  one. `core/deps.py`'s `_validate_token` is the second, independent
  enforcement point: every authenticated request re-checks the `device_id`
  embedded in its own token, so a token issued before revocation is
  rejected on its very next use, not just at its next login.

  **One narrow, accepted residual, not closed and not silently left
  open.** A parent enrolled in MFA who logs in from a revoked device gets
  a `parent_pending` token (password correct, second factor still
  outstanding) — `login()`'s own revocation check does not run again on
  the follow-up `/mfa/*/verify` call, so in principle that call's own 401
  could be read as confirming the device is known-revoked rather than
  merely "wrong TOTP code." This is a strictly weaker oracle than the one
  closed above (it requires the *correct password* first, where the
  closed one required nothing), and closing it structurally cannot be
  done for free: `require_mfa_pending` routes through the same
  `_validate_token` that already carries the per-request device check, so
  the pending token itself is already checked on arrival at the MFA
  endpoint — the only way to check *earlier* would be inside `login()`
  before issuing the pending token, which buys nothing `_validate_token`
  doesn't already provide and would burn a real TOTP attempt for no
  additional security. Left open on purpose, pinned by
  `test_a_device_revoked_mid_login_cannot_complete_its_second_factor`
  (verified via negative control — the guard was temporarily disabled,
  confirmed the test fails, then restored) so the reasoning stays testable
  rather than just asserted here.

  Parent-facing surface: `GET /admin/devices` (`require_parent`) and
  `POST /admin/devices/{device_id}/revoke` (`require_elevated_parent` —
  revoking a device is exactly the kind of destructive, session-affecting
  action P8's step-up exists for) back `homeschool-tutor/src/components/
  DeviceSettings.tsx`, a collapsible card on the parent setup page listing
  every known device with a "This device" badge and a confirmation prompt
  before revoking the device the parent is currently using. Every
  revocation is audit-logged (`AuditEvent.DEVICE_REVOKED`); a blocked
  login or blocked request from a revoked device logs
  `AuditEvent.DEVICE_LOGIN_BLOCKED`, wired into the E009 anomaly watch at
  the same tight 3-in-10-minutes threshold as `ELEVATION_DENIED` — reaching
  this at all means someone is actively using hardware a parent already
  revoked, so there's no benign "I mistyped" explanation to wait out.

- **The public demo shared one identity domain with the family
  deployment, closed 2026-08-03.** `routers/auth.py`'s `login()` issued
  `parent`, `child`, and `demo_code` tokens from one function, in one
  format, under one signing key, validated by one path — despite the demo
  being pseudonymous, internet-facing, multi-tenant, and operated *for*
  strangers rather than *by* them. The practical consequence: every bug in
  the demo's credential path was a bug in the family's. `demo_code` login
  consumes a code minted by an unauthenticated endpoint, so any flaw there
  that yielded an attacker-controlled *signed* token had nothing structural
  standing between it and `role: "parent"` — only the fact that every
  authorization check, present and future, remembers to look at the role.

  `core/identity.py` splits this into two domains with separate signing
  keys, derived from `SECRET_KEY` by domain-labelled HMAC. The domain
  travels in the JWT header, covered by the signature; verification picks
  the key by that domain and then requires the role to be one the domain
  may issue. A demo token claiming `parent` now fails at the signature
  layer, before authorization runs.

  Stated precisely, because the difference matters: this is domain
  separation, not key isolation. Both keys derive from one `SECRET_KEY` by
  default, so compromising that secret still yields both. Setting
  `DEMO_SECRET_KEY` on the public demo instance gives it a key sharing no
  material with the family's — recommended there, unnecessary for a
  self-hosted family deployment that has no demo role in play.

  Tokens issued before the change stay valid until they expire
  (`LEGACY_TOKEN_GRACE`, default on) so the deploy doesn't sign families out
  mid-lesson. It is not a downgrade path — the grace accepts only tokens
  signed with the raw pre-migration key, so stripping the header off a
  domain-signed token fails.

- **Deletion was logical, not cryptographic, closed 2026-08-03.**
  `services/student_deletion.py` issued real SQL `DELETE`s across every
  student-scoped table, which was correct as far as the live table went and
  no further. Postgres keeps dead tuples until VACUUM, the delete is written
  to WAL, and every `make db-backup` dump taken beforehand still contained
  the rows — all of it decryptable indefinitely under a global `DATA_KEY`
  that by design never changes (even `MASTER_SECRET` rotation deliberately
  preserves it). So README.md's and `docs/DATA_RETENTION.md`'s "permanently
  delete" was true of the live table and false of the disk, and the standard
  way an auditor tests an erasure claim — restore a backup and look — would
  have shown the record intact.

  `core/student_keys.py` gives each student one random 32-byte key, wrapped
  under `DATA_KEY` and bound to their name as AAD (so a wrapped key cannot
  be moved between students by anyone with DB write access). Every
  student-scoped encrypted column is now encrypted under that key, marked
  by envelope version 3. Deletion destroys the key row *in the same
  transaction* as the row deletes, so the shred cannot half-succeed and
  leave the key destroyed but the rows present, or the reverse. Afterwards
  every copy of that student's ciphertext — live rows, dead tuples, WAL
  segments, old backups — is permanently unopenable, including by this
  deployment itself.

  Two deliberate limits worth stating rather than burying. **The audit log
  is not per-student** and survives a deletion by design (`core/audit.py`);
  crypto-shredding it per student would destroy the security record along
  with the data. And **rows written before this change stay readable** —
  the envelope dispatches on its own version byte, and rows upgrade
  themselves on next write. A migration that got this wrong would make a
  family's data permanently unreadable, which is strictly worse than the
  gap staying open longer.

- **Encrypted columns had no AAD binding, closed 2026-08-03.**
  `core/encryption.py`'s AES-GCM calls carried no associated data, so a
  ciphertext blob proved only "encrypted by whoever holds `DATA_KEY`" —
  making it portable between rows, columns, and tables. Anyone with
  database write access could swap one student's `profile_enc` into
  another's row, or a bookmark between subjects, and it would decrypt
  cleanly. Every T1–T4 column now binds `table/column/row_key`, so a blob
  is only valid in the row it was written for; moving it fails
  authentication instead of decrypting. See `docs/DATA_CLASSIFICATION.md`
  for the per-entity mapping.

- **Child PIN had no brute-force defense, closed 2026-08-02.** The only
  barrier was `core/middleware.py`'s per-IP auth bucket (10/min), which
  keys on IP alone — trivially defeated on a LAN, and via IPv6 essentially
  free. The parent role had DB-backed lockout since July; the child role
  guarded the same student data with nothing, and this document's prior
  reasoning for that (a locked-out child just asks a parent to reset the
  PIN) answered lockout-RECOVERY, not brute force. Nothing about
  recoverability makes a 6-digit PIN harder to guess.

  `core/child_throttle.py` throttles by escalating DELAY, deliberately not
  by refusal. Copying `core/parent_lockout.py`'s fixed-threshold lockout
  here would have closed a brute-force gap by opening an easier
  availability one: the threshold is public the moment the source is (see
  `docs/THREAT_MODEL.md`'s self-defeating-mechanisms note), so any sibling
  or houseguest on the WiFi could reliably end a lesson before it started,
  with "go find a parent" as the recovery path. Instead the first three
  failures are free (a child mistyping their own PIN notices nothing),
  then delay escalates to a 5-second cap — roughly two months of
  continuous guessing for a 10^6 keyspace, and there is no state an
  attacker can push the child role into that a parent must clear. State is
  keyed on the credential rather than the source address, so IP rotation
  buys nothing; it is in-process rather than DB-backed because this runs on
  a family's Raspberry Pi and a child logs in every school morning, and a
  container restart clearing it is acceptable given restarting requires
  host access. Covered by `tests/test_child_throttle.py`, including that a
  correct PIN still authenticates after 500 failures — the property that
  makes this not a lockout.

- **Rate limiter was O(n) per request and leaked memory without bound,
  closed 2026-08-02.** `_check_rate` rebuilt the entire sliding window on
  every single request (`[t for t in window if t > cutoff]`) — linear in
  the configured limit, measured at 0.8 us/call at limit=20 rising to 38.3
  us at 3000, ahead of every route handler, on hardware
  `docs/PARENT_SETUP.md` targets at Raspberry Pi class. Separately, idle
  `(ip, bucket)` entries were never evicted: 50,000 distinct source
  addresses held 50,000 entries indefinitely, reachable on the
  internet-facing public demo.

  Timestamps are non-decreasing (`time.monotonic`), so expired entries are
  always a prefix — `bisect` finds the cut in O(log n) and one slice-delete
  drops them. Now flat at ~0.38 us/call regardless of limit (~6x faster at
  the default, ~95x at 3000). Idle entries are swept lazily, at most once
  every five minutes, using the widest window any caller has requested so a
  live window can never be evicted (which would silently reset an
  attacker's progress). A deque benchmarked marginally faster still but
  costs ~760 bytes per key against a list's ~64 — the wrong trade when the
  demo's keys are overwhelmingly sparse and the device may have 1-2 GB
  total.


- **`MASTER_SECRET` had no rotation path at all, closed 2026-08-02.**
  `core/encryption.py`'s own docstring, and `docs/INCIDENT_RESPONSE.md`'s
  containment step for a suspected `MASTER_SECRET` leak, both said the same
  thing: don't rotate it. Restarting with a new `MASTER_SECRET` and no
  matching wrapper for the existing `DATA_KEY` meant either a boot failure
  (`initialize_encryption()` refuses to silently generate a fresh
  `DATA_KEY` over an existing row) or, on a from-scratch deployment,
  actually generating a new `DATA_KEY` that abandoned everything encrypted
  under the old one. So the one credential this app's entire encryption
  hierarchy roots in had no real response to its own compromise — the
  Accountability-pillar failure mode of "the incident response plan's
  answer to its own top severity item is a documented dead end."

  `core/encryption.py`'s new `rotate_master_secret()` re-wraps the
  *existing* `DATA_KEY` under a new `MASTER_SECRET` — `DATA_KEY` itself
  never changes, so every row already encrypted under it (every student
  config, transcript, voice profile) stays valid with zero rewriting; only
  the single `encryption_config.data_key` row is touched. It verifies the
  new wrapping round-trips before committing, and raises without writing
  anything if the supplied old secret doesn't actually unwrap the current
  `DATA_KEY` — a failed attempt is a true no-op, not a partial one.
  `scripts/rotate_master_secret.py` is the operator-facing CLI (prompts
  for both secrets via `getpass`, never as a CLI argument or env var, so
  neither sits in shell history or a process list); `docs/
  INCIDENT_RESPONSE.md`'s "Critical" containment step now points here
  instead of ruling rotation out. Covered by `tests/test_encryption.py`,
  including that the DATA_KEY bytes are provably identical before and
  after rotation (proving this re-wraps rather than regenerates) and that
  the *old* secret genuinely stops working — the actual containment
  property this exists for, not just a housekeeping rotation.
- **Scripture quoting had no public-domain/copyright distinction, closed
  2026-07-31.** Found on an explicit instruction not to let Bede present
  non-factual claims — including invented or unverifiable wording of a
  copyrighted Bible translation — as though they were exact. Before this,
  `_bible_translation_note` (`services/ai_service.py`) told Bede to
  "favor" whichever of the 11 `BIBLE_TRANSLATIONS` a family picked,
  uniformly, with no distinction between KJV/Douay-Rheims (genuinely
  public domain) and the other nine (NKJV, ESV, NIV, NASB, NLT, CSB,
  RSV-CE, NABRE, NRSV-CE — modern, actively copyrighted translations,
  each owned by its own publisher). Bede has no verified, licensed copy of
  any of those nine translations' exact text — only whatever it happened
  to learn during training, which is neither guaranteed accurate to that
  specific translation's wording nor something this app has a license to
  reproduce at length. Encouraging Bede to "favor" that wording risked two
  compounding problems at once: presenting hallucinated phrasing as if it
  were a real quotation (a factual-accuracy failure — the constitution's
  first non-negotiable rule), and reproducing a publisher's actual
  copyrighted text at length without a license (a legal exposure this app
  had never assessed).

  `PUBLIC_DOMAIN_BIBLE_TRANSLATIONS` (`models/schemas.py`) now splits the
  11 translations into the two genuinely public-domain ones and the nine
  that aren't. For a public-domain pick, behavior is unchanged — Bede
  still favors that wording freely. For a copyrighted pick,
  `_bible_translation_note` now tells Bede to paraphrase Scripture in its
  own words by default, keep any direct quotation to a single short,
  widely-known verse, always cite book/chapter/verse so the family can
  check the exact text themselves, and never present a longer or
  uncertain passage as though it were that translation's precise wording.
  `ParentSetup.tsx`'s hint text states the distinction plainly to the
  parent rather than leaving it implicit. Covered by the new
  `tests/test_bible_translation_note.py` (this feature, from PR #323, had
  shipped without its own dedicated test file — added here too).

  **Follow-up research pass, 2026-08-01.** Actually looked up each of the
  nine copyrighted publishers' own stated permission-to-quote policy
  (`data/bible_translations/copyright_permissions.json`, sourced via
  WebSearch directly against each publisher's own permissions page,
  cross-checked against an independent secondary source per entry — see
  `docs/CONTENT_CONTRIBUTING.md`) rather than leaving the July 31 fix's
  blanket "no license" framing unverified. The real numbers are generous
  — 500 to 1,000 verses (5,000 words for NABRE, the unit the USCCB itself
  states) without formal permission — far beyond anything a single
  tutoring turn would ever approach, so licensing was never really the
  operative constraint. `_bible_translation_note` now cites the family's
  translation's real, sourced limit for transparency, while keeping the
  actual behavioral constraint on accuracy (Bede still cannot verify its
  own memorized wording against a licensed copy, independent of how
  generous the license is) — a more honest, better-sourced version of the
  same underlying rule, not a loosening of it. Also added an explicit
  closing line so the accuracy caution can't be misread as license to
  thin out Socratic narrative discussion of Scripture, which stays fully
  governed by `Subject.scripture`'s own teaching context, untouched by
  this fix. `tests/test_catalog_data_integrity.py` gained integrity
  checks for the new data file (every copyrighted translation has an
  entry, no stray entries for the two public-domain ones, every entry has
  a real source URL).
- **Bede's own hands-on suggestions had no dedicated physical-safety
  guardrail, closed 2026-07-31.** Found by auditing what the constitution's
  non-negotiable "protect the full dignity, privacy, safety, and
  developmental needs of every child" actually covers in code: it's
  enforced as a reactive rule (`services/moderation.py`'s `self_harm`/
  `violence` categories, `check_safeguarding`'s deterministic patterns) for
  a child's *own* reported distress or danger, but nothing previously
  governed the other direction — Bede's *own* free-text suggestions in
  ordinary hands-on tutoring (Nature Study, Science, and Mathematics all
  legitimately call for real-world physical activity in Mater Amabilis's
  own pedagogy) being safe by design in the first place. Bede's only
  actual kinesthetic tool, `invite_handwriting`, is already screen-based
  (drawing/writing on the tablet canvas) and carries no physical-object
  risk of its own, so this closes a gap in Bede's *language*, not in a
  tool's behavior.

  `_physical_safety_guardrails()` (`services/ai_service.py`), wired into
  the cached static prompt block (`_build_static_prompt`) so every
  session, every grade, gets it at no added cost — universal, unlike
  grade-varying sections like `_ai_literacy_guardrails`, since a younger
  child is if anything more literal about a hands-on suggestion, never
  less. Tells Bede to keep any suggested activity to safe, ordinary items
  (paper, pencils, blocks, books), never suggest heights, fire/heat, sharp
  or breakable objects, throwing/forceful impact, electricity, water
  beyond a sink, or ingesting anything non-food; to say so plainly when an
  activity genuinely calls for a nearby adult; and to redirect rather than
  comply if the child proposes something risky as their own idea for the
  lesson. Deliberately **not** a change to
  `constitution/bede.constitution.json` itself — this operationalizes an
  existing non-negotiable rule the same way `_ai_literacy_guardrails`
  operationalizes Catholic AI teaching: ordinary code, changeable by
  normal PR review, not the constitution's own founder-review/digest
  change-control process. Covered by
  `tests/test_physical_safety_guardrails.py`.

  **Follow-up design verification, same day.** Tracing a concrete scenario
  through both this guardrail and the pre-existing safeguarding layer
  (`moderation.py`'s `self_harm` category, `check_safeguarding`'s
  deterministic patterns, `ethical_boundaries` rule 12's full stop)
  surfaced two real composition gaps rather than confirming a clean
  handoff between them:
  1. The original hazard list only named risk to objects/environment
     (heights, fire, sharp things, water) — nothing named a child
     directing a risky "experiment" at their OWN body: holding their
     breath, restricting food or water, extreme temperature exposure, or
     testing pain tolerance. Framed as a lesson activity, that's exactly
     the shape a self-harm impulse can hide in, and none of the original
     categories would have caught it.
  2. The original "child proposes something risky" instruction always
     said "redirect to a safe alternative" — correct for ordinary object/
     environment risk-taking, but a real under-escalation if the request
     targets the child's own body: substituting a safer prop and
     continuing the lesson is the wrong response to what may actually be
     a distress signal wearing a lesson's framing.

  Both closed in the same function: the hazard list now names self-
  directed bodily risk explicitly, and the response is forked — object/
  environment risk still gets the warm redirect-and-continue, but any
  activity targeting the child's own body routes to the exact same
  stop-and-escalate response as the safeguarding rule, with an explicit
  "when in doubt, treat it as the stop" tiebreaker rather than leaving the
  model to guess which path a borderline request belongs on. Verified via
  4 new tests in the same file (9 total).
- **Node 20 was end-of-life, and nothing in the toolchain said so, closed
  2026-07-30.** Follow-up to the sweep below, from asking the obvious next
  question: are node/npm actually clean *everywhere*, or just in the two
  places the audit gates look? The packages were clean. The runtime under
  them was not. Node 20 reached end-of-life on **2026-04-30** and had been
  unsupported for three months, while pinned in three places:
  `frontend-tests.yml`'s two jobs (`node-version: 20`) and
  `homeschool-tutor/Dockerfile` (`node:20-alpine`, the build stage that
  produces the served bundle).

  The reason this survived a dependency-security pass is worth recording,
  because it generalizes: **`npm audit` and Dependabot audit packages, not
  the runtime beneath them.** A repo can sit at a clean zero — as this one
  did, immediately after the sweep below — while building on a runtime
  that will never receive another security patch, for OpenSSL, HTTP
  parsing, or anything else. No tool in the pipeline reports it. Checking
  interpreter and base-image EOL dates is a separate, manual habit from
  reading advisory counts, and the two do not substitute for each other.

  Moved to Node 24 (active LTS, security support through 2028-04-30) in
  CI and in the Dockerfile, and both `package.json` files gained
  `engines: {node: ">=22"}` — a floor at the oldest still-supported LTS,
  so a contributor on an EOL runtime gets a warning rather than silently
  resolving a lockfile against it. The rest of the stack was checked at
  the same time and is fine: every other container is Python 3.12
  (supported through 2028-10), and there are exactly two Node projects in
  the repo, both covered.
- **Audit gate threshold raised from `high` to `moderate`, closed
  2026-07-30.** The gates restored below were set to
  `--audit-level=high`, matching what they used before their deletion.
  That threshold was wrong, and provably so: the post-authentication open
  redirect closed in #319 — the highest-impact finding of that entire
  review — was published as a **moderate** advisory
  (GHSA-wrjc-x8rr-h8h6). A gate set to `high` would have let it through,
  which is exactly what happened for as long as it sat in the tree.

  npm's severity rating describes an advisory in the abstract, not what
  the affected dependency is load-bearing for in *this* application. A
  moderate advisory in the router that owns post-login navigation matters
  more here than a high one in a build-time-only tool. Nothing automated
  is positioned to make that call, so the gate now errs toward surfacing
  and letting a human decide. Both projects are at zero, so the tightened
  threshold costs nothing today. It must not be quietly raised back to
  `high` to clear a red build.

- **Post-authentication open redirect on the login screen, closed
  2026-07-30.** `Login.tsx` read `?returnTo=` straight off the URL and
  handed it to react-router's `navigate()` at four call sites, every one
  of them *after* `setAuth()`. The parameter is fully attacker-controlled,
  and the product actively teaches parents to send `/session?student=…`
  links to a tablet — so a Bede URL carrying a query string is a shape
  families already expect to receive and open. A crafted
  `?returnTo=%5C%5Cattacker.example` therefore landed a just-authenticated
  parent or child on an off-site page at the exact moment they had
  demonstrated they will type a password into whatever Bede presents.
  Two independent fixes, because either alone is one dependency
  advisory away from failing:
  - `homeschool-tutor/src/utils/safeRedirect.ts` (`safeReturnTo`) is an
    allowlist — a value must be a single in-app absolute path, or the
    caller's own default route is used instead. It validates the DECODED
    string (validating the encoded form and navigating to the decoded one
    is its own bypass: `%2F%2Fattacker.example`), rejects protocol-relative
    and backslash forms, rejects control characters and whitespace, and
    finishes with a `new URL()` origin check rather than trusting its own
    string reasoning. `safeRedirect.test.ts` runs a 20-entry hostile
    corpus through both the raw and percent-encoded forms.
  - The dependency itself was upgraded past the advisory that made the
    bypass work — see the next entry.
- **Dependency vulnerability monitoring restored, closed 2026-07-30.**
  Between PR #285 (deleting `.github/dependabot.yml`) and PR #296
  (deleting the `npm audit` and `pip-audit` CI steps), this repo was left
  with **no** software-composition analysis at all across three
  ecosystems — no Dependabot, no audit gates, no CodeQL. That is a
  straight AIUC-1 vulnerability-management gap and a SOC 2 CC7.1 gap, and
  it persisted with five known-vulnerable npm packages installed.
  PR #296's stated reason — a CVE "with no fix available yet" blocking
  unrelated PRs — did not hold: every one of the five advisories then
  outstanding had a fix available. What was true was its other half, that
  the gate had lost its auto-fix companion. Both are now addressed:
  - All five advisories cleared (`postcss` path traversal, `tar`
    recursion DoS, and the two `react-router` issues), taking
    `homeschool-tutor` to zero. Clearing react-router required migrating
    off the `react-router-dom` shim — it stops at 7.18.2, which is inside
    the range of a later RSC-mode CSRF advisory, while `react-router`
    itself continues to 8.3.0, which is clear of every current advisory.
    Imports moved from `react-router-dom` to `react-router` across 10
    files; type-check, the full 129-test frontend suite, and a production
    build all pass unchanged.
  - The `npm audit --audit-level=high` and `pip-audit` steps are restored
    as **hard gates**, and now pass on a clean tree.
  - `.github/dependabot.yml` is restored with `open-pull-requests-limit: 0`
    on every ecosystem. This is the distinction both prior deletions
    missed: that setting disables routine *version-update* PRs — the
    half-bumped peer pairs and surprise majors that motivated #285 —
    while leaving *security-advisory* PRs enabled. The gate gets its
    auto-fix companion back without the upgrade churn.

  The standing rule going forward, recorded in both workflow files: a red
  audit gate means upgrade the dependency, or record why it is
  unreachable — never delete the step.
- **Stored prompt injection via lesson bookmarks, closed 2026-07-30.**
  `LessonBookmark` (added PR #308) is the one place in this codebase where
  text shaped by the **child** becomes **persistent** prompt context.
  `generate_session_summary` asks the model for a per-subject resume
  sentence, written from a conversation the child fully steered;
  `_bookmark_note` then replays it into that subject's prompt at the start
  of every future session, indefinitely. The write path stored it as bare
  `str(v)` and the read path interpolated it raw — no sanitizing, no
  length bound, and `bookmark_enc` is `LargeBinary`, so nothing imposed a
  ceiling. The standing reasoning for leaving a child's chat text
  unsanitized (it is transient, and there is no secret in context to leak)
  does not extend to this path, because neither half of it is true here.
  `_sanitize_parent_field(..., max_len=300)` now runs on **both** paths —
  the read side deliberately as well as the write side, because rows
  written before this fix are still live in deployed databases and this
  codebase has no `ALTER TABLE`/migration path to clean them, so the read
  boundary is the only place a pre-existing poisoned bookmark can be
  neutralized.
- **`_INJECTION_PATTERN` bypass, closed 2026-07-30.** Found by the
  regression test written for the bookmark fix above. The flagship
  alternative read `ignore\s+(previous|prior|all)\s+instructions?`,
  requiring the target noun *immediately* after a single qualifier — so it
  matched "ignore previous instructions" but did **not** match "ignore all
  previous instructions", the most common phrasing of the attack, nor
  "ignore your earlier instructions", "ignore the above instructions", or
  any other multi-qualifier variant. This is the shared sanitizer for
  every free-text field reaching the prompt from outside the model,
  including anonymous public demo input, so the gap was not
  bookmark-specific. Replaced with a bounded verb→target form
  (`[^.!?\n]{0,60}?`, which cannot cross a sentence or line boundary,
  unlike the old `disregard` alternative's unbounded `.*?`), plus a new
  alternative for prompt-extraction phrasing ("reveal/show/print your
  system prompt"), which had no coverage at all. The verb list is
  deliberately narrow — `skip` and `bypass` were considered and rejected,
  since "skip the instructions on page 4" is ordinary parent lesson-note
  text and a false positive here silently mangles it.
  `tests/test_injection_pattern.py` covers 20 hostile phrasings and 9
  benign parent notes that must survive untouched.
- **Predictable `/tmp` paths in the Unix installer, closed 2026-07-30.**
  `packaging/unix/install.sh` downloaded Docker Desktop to a fixed
  `/tmp/Docker.dmg` and Ollama to `/tmp/Ollama-darwin.zip`, then mounted
  and `cp -R`'d the first into `/Applications` and `unzip -o`'d the second
  directly over it. `/tmp` is world-writable, so a fixed filename lets any
  other local account pre-place a file or symlink at that path and have
  the result installed as a trusted application. Both now download into a
  fresh `mktemp -d` (0700, unguessable) with a `trap … RETURN` cleanup,
  and both verify the expected `.app` bundle is present before anything
  reaches `/Applications`; Ollama additionally extracts to a private
  staging directory first rather than unpacking an unverified archive over
  a system location.
- **AI backend failure alerting (reliability, not a security control),
  closed 2026-07-29.** Not an AIUC-1/SOC 2 control — noted here because
  it extends E009's anomaly-watch infrastructure and a reader tracing
  that mechanism should know this one rule works differently. Before
  this, a crashed local model server or a revoked cloud API key just
  looked like Bede being broken, with no signal reaching the parent —
  `routers/tutor.py`/`routers/sandbox.py`'s existing stall-timeout/
  guaranteed-`done` resilience already kept the child's UI from hanging,
  but nothing told anyone the backend itself was unhealthy. A new
  `AuditEvent.AI_BACKEND_FAILURE`, logged from all three streaming call
  sites on a stall or any exception, feeds a new E009 rule — but
  deliberately the only one in `_GLOBAL_ANOMALY_EVENTS`, pooled across
  every IP instead of per-IP like every security rule here, since a
  broken backend affects the whole household identically rather than
  being one actor's pattern. 3 failures in 10 minutes emails
  `PARENT_EMAIL` via a dedicated template (`send_backend_failure_alert`)
  distinct from the security-alert one — "unusual activity"/"from
  address" framing would be actively misleading for a reliability
  problem with no culprit address. See `CLAUDE.md`'s "AI backend failure
  alerting" section for the full mapping. Covered by
  `tests/test_audit_anomaly.py`, `tests/test_email_service.py`,
  `tests/test_tutor_stream_resilience.py`, and
  `tests/test_sandbox_stream_resilience.py`.
- **Parent account lockout + recovery, ending a stolen-credential
  takeover, closed 2026-07-23.** Follows directly from the pre-production
  hardening pass below: that pass closed the "weak password accepted"
  gap, but a real question remained — if `PARENT_PASSWORD` (or a device
  holding the only enrolled second factor) genuinely leaks or is lost,
  what actually happens? Three real gaps, closed together because they
  compound each other:
  - **PARENT_PASSWORD lived only in `.env`, so it could never actually be
    changed from inside the running app** — forgotten or not, changing it
    meant editing a file on the server and restarting. `core/
    parent_credential.py` adds a DB-backed override that wins over the
    env default, live, no restart — the exact same precedence
    `core/license_state.py` already established for `LICENSE_KEY` (a DB
    value applied in-app wins over the env default), applied here for the
    same reason. A deployment that never touches this sees zero behavior
    change; `POST /mfa/change-password` (a full parent session changing
    its own password on purpose) is the new in-app path.
  - **No account lockout, only after-the-fact E009 alerting.** The
    anomaly watch (`core/audit.py`) already emailed a parent after 5
    failed logins in 10 minutes, but never blocked the next attempt — a
    slow or distributed brute force against `PARENT_PASSWORD` wasn't
    actually stopped. `core/parent_lockout.py` adds a DB-backed (survives
    a restart, unlike the anomaly watch's in-memory window — see the
    still-open gap above for that distinction), role-scoped lockout: 10
    failures in a 30-minute window locks the parent role for 15 minutes.
    Deliberately above the anomaly watch's own 5-failure alert threshold,
    so a parent who mistypes their password gets a heads-up email before
    they'd ever actually get locked out.
  - **A locked-out parent had no way back in short of server access, and
    "logout" never actually revoked a JWT** (a stolen token stayed valid
    up to 8h regardless of what the legitimate parent did afterward — the
    only real revocation lever was rotating `SECRET_KEY`, which logs out
    the *entire* family, not just the compromised session).
    `services/parent_recovery.py` adds a "something you know" recovery
    factor — a parent chooses ONE of two mutually exclusive shapes at
    enrollment: a **recovery PIN** (favored/default — parent-chosen, 6
    digits by default, extendable up to 12 for more entropy while staying
    memorable; same strength floor as `CHILD_PIN` via `pin_is_strong()`,
    plus its own 12-digit ceiling checked in `enroll_recovery_pin`) or a
    **recovery code** (the alternative — longer,
    machine-generated, higher entropy, for a parent who'd rather store a
    stronger secret than remember one). Enrolling either clears the other.
    Both are deliberately independent of `PARENT_PASSWORD` and
    `CHILD_PIN`, so a leak of one doesn't expose the others.
    `routers/recovery.py`'s public (necessarily — a locked-out parent has
    no session to authenticate with) `/auth/recovery/*` endpoints require
    proving **at least 2** of {recovery PIN or code, TOTP, WebAuthn} —
    never just one — before issuing a narrowly-scoped token good for
    exactly one thing: setting a new password.
    Every credential change (in-app or via recovery) bumps a
    `credentials_version` embedded in every parent/parent_pending JWT at
    issuance and checked on every request (`core/deps.py`) — the piece
    that makes "recover access, set a new password" actually **end** a
    takeover: every other outstanding session, including an attacker's
    stolen token, stops working the instant the change commits, rather
    than lingering until natural expiry alongside the new one.

  All secrets that only ever need verifying, never redisplaying (the
  password override, the recovery PIN/code) are hashed with PBKDF2-HMAC-
  SHA256 (`core/credential_hash.py`, reusing the exact KDF primitive
  `core/encryption.py`'s key derivation already depends on) rather than
  this app's usual reversible AES-256-GCM encryption — a strictly
  stronger property for a verify-only secret.

  **Voice biometrics are deliberately NOT a recovery factor** — see the
  persona/account-security discussion this closes: the current speaker-
  verification implementation (`services/voice_auth.py`) has no random
  challenge phrase or liveness detection, so it's a soft, parent-
  overridable identity signal, not a spoof-resistant credential a
  security-critical recovery flow should ever accept alone or in
  combination.

  Child-role lockout/recovery is explicitly out of scope — see "Known
  open gaps" above for why that's a non-gap in this app's single-tenant
  design, not a deferred item.

  Covered by `tests/test_credential_hash.py`, `tests/
  test_parent_credential.py`, `tests/test_parent_lockout.py`, `tests/
  test_parent_recovery.py`, `tests/test_auth_login_lockout.py`, `tests/
  test_recovery_router.py`, `tests/test_mfa_password_and_recovery_
  endpoints.py`, and `tests/test_deps_credentials_version.py`. The
  recovery-PIN option (`core/database.py`'s `ParentRecoveryPin`) and its
  mutual exclusivity with the recovery code were added the same day as a
  same-scope follow-up, favored for ease of use — the frontend
  (`ParentSecuritySettings.tsx`) lists it first and prompts a written-
  backup confirmation before letting the enrollment screen close, since
  "memorable" isn't a guarantee it'll actually be remembered months later.

  **A real gap surfaced by live browser click-through of the whole flow
  (not just unit tests), fixed the same day:** `core/middleware.py`'s
  `RateLimitMiddleware` bucketed every `/auth/*` path — including
  `/auth/recovery/*` — into one shared per-IP "auth" bucket
  (`rate_limit_auth_per_minute`, default 10/min). The exact burst of
  failed `/auth/login` attempts that trips `parent_lockout.py`'s own
  lockout also exhausted that shared budget, so the locked-out parent's
  very next call — `GET /auth/recovery/methods`, to even see the
  "Forgot password?" screen — came back 429 too. `AccountRecovery.tsx`
  had no way to tell that transient 429 apart from "recovery isn't
  configured on this instance," so it showed the latter: a parent who
  *did* have 2 recovery factors enrolled was told to seek "direct access
  to the server itself," at the exact moment recovery exists to prevent
  that. Fixed with a dedicated `auth_recovery` bucket
  (`rate_limit_account_recovery_per_minute`, its own config setting,
  independent of the login bucket) plus a frontend `rate_limited` stage
  in `AccountRecovery.tsx` that shows "please wait about a minute" with a
  retry button instead of the permanent-looking "not set up" message.
  Covered by `tests/test_middleware.py`'s
  `test_auth_recovery_has_its_own_bucket_independent_of_login` and
  `test_auth_recovery_bucket_has_its_own_limit`.

- **Pre-production hardening pass, closed 2026-07-23.** A code-level survey
  ahead of the beta-to-production transition found several gaps beyond the
  two already tracked above — some real and previously undocumented
  anywhere, some already disclosed in scattered docs/code comments but
  never centralized. Fixed in this pass:
  - **`SECRET_KEY`/`PARENT_PASSWORD`/`MASTER_SECRET` had no length/strength
    floor in production**, only an exact-match check against the known dev
    defaults — unlike `CHILD_PIN`/`DEMO_PIN`/`SANDBOX_PIN`, which already
    ran through `pin_is_strong()`. A hand-edited `.env` with
    `PARENT_PASSWORD=a` or `SECRET_KEY=x` booted cleanly in production.
    `core/config.py`'s `reject_weak_defaults_in_production` now also
    enforces a minimum length (32 chars for the two secrets, matching their
    own dev-default placeholders' "-32-chars-min" naming; 8 chars for
    `PARENT_PASSWORD`, the same minimum `setup.sh`/the setup wizard already
    enforce interactively). Covered by
    `tests/test_config_production_hardening.py`.
  - **`DISABLE_API_DOCS`/`CORS_ORIGINS` had no production validator at
    all.** Both wizards and `render.yaml` set them correctly, but nothing
    in `Settings` stopped a hand-edited production `.env` from booting with
    `/docs`/`/redoc`/`/openapi.json` (the full internal admin/audit/license
    endpoint schema) publicly reachable, or a CORS wildcard defeating the
    "explicit whitelist, no wildcards" design `cors_origins`'s own comment
    already stated as intentional. New
    `reject_exposed_docs_and_wildcard_cors_in_production` validator closes
    both; the wildcard check runs regardless of production mode, since
    `allow_credentials=True` makes it a misconfiguration at any time.
  - **Voice streaming-transcription sessions had no ownership check** — an
    IDOR-shaped gap. `POST/GET /voice/stream/{id}/...` only required a
    valid token of any role, not that the caller was the one who started
    that specific session. Low practical risk given a random 122-bit
    session id, but the real exposure is the public demo, where many
    independent concurrent visitors share the `demo_code` role on one
    instance. `services/streaming_transcription.py`'s session state now
    carries an `owner` (the demo visitor's unique `code`, or `role` for the
    single-shared-credential parent/child roles), checked on every
    chunk/finish/events call; a mismatch reads identically to "unknown
    session" rather than leaking that a given id exists. Covered by new
    tests in `tests/test_streaming_transcription.py` and
    `tests/test_voice_stream_router.py`.
  - **No automated dependency-vulnerability scanning existed anywhere** —
    the CycloneDX SBOM (`docs/sbom/`) is a point-in-time inventory, never a
    signal that anything installed has a new CVE, and no
    Dependabot/CodeQL/`pip-audit`/`npm audit` step existed in any of the
    five GitHub Actions workflows. Added `.github/dependabot.yml` (weekly
    update PRs for the backend's pip tree, both frontend apps' npm trees,
    and GitHub Actions themselves) plus a `pip-audit`/`npm audit` step in
    `test.yml`/`frontend-tests.yml` so a known-vulnerable dependency —
    existing or newly introduced by a PR — fails CI immediately rather than
    waiting for the next scheduled scan. Zero vulnerabilities found in any
    of the three dependency trees as of this pass.
  - **`make db-backup` wrote an unencrypted SQL dump with default file
    permissions** — inconsistent with `.env`, which CI explicitly asserts
    is `600` (`production-regression.yml`). Most sensitive columns are
    pre-encrypted at the application layer, but the `encryption_config`
    table (the KEK-wrapped `DATA_KEY`) is in the same dump. The `Makefile`
    target now `chmod 700`s the `backups/` directory and `chmod 600`s each
    dump file immediately after `pg_dump` completes.
  - **Most GitHub Actions workflows ran with no explicit `permissions:`
    block**, relying on the org/repo default rather than declaring the
    least privilege each job actually needs. `test.yml`,
    `frontend-tests.yml`, `production-regression.yml`, and
    `keep-demo-warm.yml` now all explicitly declare `contents: read` — none
    of them write to the repo, comment on a PR, or create a release.
  - **A stale cross-reference** in `docs/VENDOR_DATA_FLOW.md` pointed to
    this file for a dependency-pinning detail that was never actually
    written here — fixed, and the note now also points at the new
    `pip-audit`/Dependabot mitigation above.

  Deliberately **not** addressed in this pass — real gaps, but each needs
  either a product/UX decision or a larger architecture change rather than
  a same-day fix; see "Known open gaps" above for the full reasoning on
  each: parent MFA being opt-in, no account-lockout mechanism, JWT logout
  not being real revocation, the in-memory/per-process scope of rate
  limiting and anomaly detection, the unpinned backend dependency tree
  lacking a lockfile, GitHub Actions being tag-pinned rather than
  SHA-pinned, and `main`'s branch-protection configuration (unverifiable
  from the repo itself).

- **Credential/secret pattern redaction (A008), closed 2026-07-17.**
  `_redact_credentials`/`_CREDENTIAL_PATTERN` (`services/ai_service.py`)
  now catch API keys, AWS/GitHub/Slack tokens, JWTs, Bearer headers, and
  `user:pass@host` connection strings, and are applied at every point
  free text enters the backend: the live `child_message` on `/tutor/chat`
  (`routers/tutor.py`), replayed user-role `conversation_history` inside
  `stream_tutor_response` (a client resends its own unredacted copy of
  past turns every request, so this needed covering separately from the
  current turn), the independently client-submitted transcript save
  (`routers/transcripts.py`), and folded into the existing
  `_sanitize_parent_field` for parent-supplied config fields. Covered by
  `tests/test_credential_redaction.py`.
- **Active alerting on the audit log (E009), closed 2026-07-17.**
  `core/audit.py` now watches a sliding window per (IP, event type) for
  security-relevant patterns — 5 failed logins, 3 JWT fingerprint
  mismatches, or 8 access-denied events in 10 minutes from one address, or
  even a single blocked exfiltration attempt (`ExfiltrationGuard`'s
  `suspicious_request`) — and, once per pattern per 30-minute cooldown,
  records an `AuditEvent.ANOMALY_ALERT` entry and best-effort emails
  `PARENT_EMAIL` via the same Resend path as the existing safeguarding
  distress alert (`services/email_service.py`'s `send_security_alert`).
  In-process only (no new infra, resets on redeploy) — a defense-in-depth
  signal sized for a self-hosted single-family deployment, not a SIEM.
  Covered by `tests/test_audit_anomaly.py`.
- **Safeguarding was English-only despite a live Spanish-locale session,
  closed 2026-07-17.** The adversarial pass above found that
  `check_safeguarding` (`services/ai_service.py`) — the deterministic,
  pre-Claude check that bypasses the LLM entirely for a child's
  distress/danger language — only ever matched English phrasing, even
  though this deployment supports a real Spanish-locale session
  (`LOCALE=es`, `docs/LOCALIZATION.md`). A Spanish-speaking child's actual
  crisis language would never have triggered it. Added a Spanish pattern
  set (checked unconditionally regardless of deployment `LOCALE` — a family
  can be multilingual even in an English deployment) and a locale-aware
  `safeguarding_response()` so the crisis response itself arrives in the
  child's own language, not just gets detected correctly. Also the first
  test coverage this function has ever had — `tests/test_safeguarding.py`,
  including deliberate false-positive checks against ordinary lesson
  content and an ambiguous Spanish idiom ("me tocó" = "it was my turn")
  that a naive translation would have misfired on constantly.
- **Formal incident response plan, closed 2026-07-17.**
  `docs/INCIDENT_RESPONSE.md` covers detection (tying together the audit
  log, the E009 anomaly alert, and the safeguarding distress alert into one
  "what already tells you something's wrong" table), a severity scale,
  step-by-step response for both the self-hosted family instance and the
  public demo (including the crucial `SECRET_KEY`-vs-`MASTER_SECRET`
  rotation distinction — one is safe and reversible, the other destroys all
  existing data), breach-notification guidance, and a root-level
  `SECURITY.md` wiring up GitHub's private vulnerability reporting for the
  codebase itself. Named contacts are the real, already-existing channels
  (`PARENT_EMAIL` for a family's own instance, `FEEDBACK_EMAIL` for the
  demo) rather than a fabricated security-team email address.
- **SBOM and vendor data-flow note, closed 2026-07-17.** `docs/sbom/`
  holds CycloneDX 1.5 bills of material for both dependency trees
  (`backend.cdx.json` from `requirements.txt`/`requirements-dev.txt`,
  `frontend.cdx.json` from `package-lock.json`'s exact resolved versions —
  361 components with license data where npm records it), regenerable via
  `scripts/generate_sbom.py`. `docs/VENDOR_DATA_FLOW.md` covers what
  actually flows to each third party at runtime (distinct from the
  dependency list): the full prompt context to whichever AI provider this
  deployment is configured to use (Anthropic, OpenAI, Mistral, or a
  self-hosted local model that never sends anything off-machine at all —
  see `docs/PROVIDER_ADAPTERS.md`), text
  sent to OpenAI's TTS API specifically — clarifying that voice
  *enrollment* transcription is local Whisper, not a network call, despite
  sharing a vendor name — and the four independent Resend email triggers.
  Also states explicitly that voice biometrics never leave the machine.
- **Tool-call defense-in-depth and auditability, extending E009, closed
  2026-07-23.** Two gaps in one: a tool call from Claude executed
  unconditionally the instant it parsed as valid JSON, with no ceiling on
  how many a single turn could act on; and for a real (parent/child)
  session, nothing durable ever recorded that a tool fired at all — the
  demo's `services/interaction_signals.py` structural counters are a
  separate, privacy-scoped, demo-only analytics pipeline, not a general
  audit trail. `services/ai_service.py`'s `_MAX_TOOL_CALLS_PER_TURN` (6)
  now caps executed tool calls per turn — well above any real Socratic
  turn's usage, but bounding what a jailbroken or malfunctioning response
  could do in one turn (e.g. spamming `record_skill_evidence` to corrupt
  a mastery profile). A call past the cap is silently dropped — never
  executed, never rendered, the child's turn is never visibly
  interrupted — and every dispatched call (allowed or suppressed) is now
  audit-logged (`AuditEvent.TOOL_INVOKED`/`TOOL_CALL_SUPPRESSED`,
  `core/audit.py`), feeding two new E009 anomaly rules: a burst of 40+
  tool invocations in 10 minutes from one IP, or even a single suppressed
  call (anomalous by construction — one legitimate turn has never needed
  more than the cap). Covered by `tests/test_tool_call_audit.py` and the
  new rules in `tests/test_audit_anomaly.py`.
- **Adversarial resilience pipeline (extends B005/E009), closed
  2026-07-23.** `routers/tutor.py`'s `chat()` now runs
  `User Input → Adversarial Detection → Policy Engine → Tutor State Machine
  → Action Validator → Parent/Student` as additive stages layered on top of
  the pre-existing safeguarding/moderation gate — see `CLAUDE.md`'s
  "Adversarial resilience pipeline" section for the full code-level
  mapping. Adds real detection + policy for four categories a fixed
  phrase list, and the original five B005 categories, didn't cover:
  jailbreak framing ("DAN mode", "developer mode", "pretend you have no
  rules"), policy-override attempts (false claims of parent/admin/developer
  authority demanding a rules/safety-filter bypass), conversational data-
  exfiltration attempts (asking Bede to disclose its system prompt, repeat
  prior context verbatim, or reveal other students'/server data — distinct
  from `core/middleware.py`'s pre-existing `ExfiltrationGuard`, which is the
  HTTP response-body variant of the same concern), and social engineering
  (sustained pressure/guilt/urgency aimed at getting Bede to break its own
  rules). Two tiers, no added latency or vendor cost: Tier 1
  (`services/adversarial_detection.py`'s `detect_tier1`) is free, instant,
  deterministic regex, curated for near-zero false positives against
  ordinary K-8 Socratic dialogue and creative-writing roleplay, and is the
  only signal still available during a moderation-classifier outage; Tier 2
  extends `services/moderation.py`'s existing per-turn classifier call with
  the same four categories (no second LLM call). `services/policy_engine.py`'s
  `decide()` tiers the response: policy_override_attempt/
  data_exfiltration_attempt redirect the turn on a Tier 1 hit OR a Tier 2
  flag at medium+ confidence; jailbreak_intent/social_engineering never
  redirect alone, at any confidence — the same reasoning `moderation.py`
  already documents for why `prompt_injection` doesn't block alone (real
  lesson content looks like these categories often enough that blocking
  would cost more than it defends, and this app's architecture has no
  secret for a successful jailbreak to actually leak). Every detection,
  blocking or not, is audit-logged as `AuditEvent.ADVERSARIAL_DETECTED` and
  feeds a new E009 anomaly rule (3 in 10 minutes from one IP — same
  "routine boundary-testing vs. a sustained pattern" threshold
  `MODERATION_FLAGGED` uses), so the categories that never block on their
  own still surface to a parent if they recur. Explicitly does **not**
  include live adversarial pentesting against the running persona — see the
  open gap above; that remains a separate, human/AI-red-team engagement
  outside this codebase, which this pipeline is meant to be tested against,
  not a substitute for. Covered by `tests/test_adversarial_detection.py`,
  `tests/test_policy_engine.py`, `tests/test_adversarial_router.py`, and
  the new rule in `tests/test_audit_anomaly.py`.
- **B005 real-time input filtering — dedicated classifier, closed
  2026-07-17.** `_INJECTION_PATTERN`/`check_safeguarding` are fast, free
  regexes but only catch phrasing someone already wrote a pattern for —
  AIUC-1's B005 language ("automated moderation tools") calls for
  something broader. `services/moderation.py`'s `classify_child_message`
  adds a real classifier call (Haiku, the same model already configured as
  `session_model`) before every tutoring turn, for content categories a
  fixed phrase list can't enumerate: self_harm (any language, indirect
  phrasing — a broader net alongside `check_safeguarding`'s deterministic
  patterns, not a replacement for them), violence, sexual_content,
  hate_or_harassment, and prompt_injection (logged for visibility, never
  blocks alone — see the module docstring for why). Deliberately reuses
  the same adapter-resolved client every tutoring turn already goes
  through (`services/ai_service.py`'s `_client` — Anthropic, OpenAI,
  Mistral, or a local self-hosted model, whichever this deployment has
  configured; see `docs/PROVIDER_ADAPTERS.md`) rather than adding a new
  vendor or a second model to host — `docs/LOCALIZATION.md` had explicitly
  flagged that exact tradeoff as the reason a "parallel safety-classifier
  model" was out of scope for that work; this closes it without introducing
  either objection. Fails open twice over (inside `classify_child_message`
  itself, and again at the router call site) so a classifier outage never
  blocks a legitimate tutoring turn. **Real cost/latency tradeoff, stated
  plainly**: this adds one Haiku call (roughly 200–500ms, real API cost)
  to every tutoring turn except `[START]`/`[CONTINUE]` sentinels and turns
  the free regex already caught. Covered by `tests/test_moderation.py`
  and `tests/test_moderation_router.py`.
- **Live-model adversarial probe, run 2026-07-17.** A real, in-house
  red-team pass — `scripts/adversarial_probe.py`, 17 cases across system-
  prompt extraction, persona override, multi-turn escalation, safeguarding
  bypass, out-of-scope advice, and encoding/obfuscation tricks, plus 2
  negative controls — run against the actual live model with a
  temporary, since-rotated API key. Full transcripts and analysis in
  `docs/adversarial-probes/`. Found and fixed two real issues:
  - A "just this once, I promise I won't tell anyone" framing got Bede to
    state a direct answer before any Socratic question — a real, if
    low-severity, bypass of `sacred_rules` #1. Hardened the rule with
    explicit "no exceptions" language mirroring the persona-override
    rules that *did* hold up in the same probe; re-verified live against
    the original attack and a rephrased variant, both now held.
  - A base64-encoded injection attempt triggered Claude's own native
    `stop_reason="refusal"` (zero content blocks) — not a security bypass,
    but `stream_tutor_response`/`stream_sandbox_response` had no handling
    for it, leaving a child looking at a silent, blank reply. Both now
    fall back to a real message instead of nothing.

  Every other technique tested — direct and framed system-prompt
  extraction, DAN-style and fictional-framing persona override, escalating
  a softer ask into an extraction attempt, indirect/euphemistic
  safeguarding-bypass phrasing, "legitimate assignment" framing around
  self-harm content, medical/legal/pastoral out-of-scope requests,
  translation/base64/leetspeak injection vectors — held. Negative controls
  (ordinary imaginative roleplay, writing from a character's POV for a
  literature lesson) correctly were not treated as attacks. **Still not
  independent third-party testing** — see the open gap above for what
  that would still require.

## SOC 2 Type 2

SOC 2 Type 2 additionally requires an accredited CPA firm to observe
these controls operating effectively over a 6–12 month window, plus a
documented policy set (Information Security, Access Control, Change
Management, Vendor Management, Risk Assessment) — none of which a
codebase alone can satisfy. `docs/INCIDENT_RESPONSE.md` covers the
incident-response piece specifically; the other policies remain
undocumented. The technical controls this repository already has
(encryption at rest, constant-time auth, rate limiting, security headers,
container hardening, the encrypted independent audit log) map most
directly to the Security and Confidentiality criteria; Availability,
Processing Integrity, and Privacy have partial technical coverage but no
accompanying policy documentation yet.
