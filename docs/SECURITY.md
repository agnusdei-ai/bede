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
action plan.

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
- **Child role has no equivalent lockout/recovery scheme.** Everything in
  the newly-closed account-lockout/recovery work below is parent-only —
  `CHILD_PIN` still has no lockout of its own. Deliberately out of scope:
  this app's single-tenant design (docs/SECURITY.md's Society-pillar scope
  statement) makes the parent the ultimate authority over the one shared
  child credential, so "recovery" for a locked-out child is simply "ask a
  parent to change `CHILD_PIN`" — a capability that already exists (parent
  settings), not a gap.
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
- **Backend `requirements.txt` is floor-pinned (`>=`, no upper bound), with
  no lockfile.** Unlike the frontend's exact-pinned `package-lock.json`, a
  fresh `pip install` at two different points in time can resolve
  different transitive versions — CI (`test.yml`) reinstalls fresh on every
  run rather than from a hash-pinned lockfile. The new `pip-audit` step
  (below) catches a *known-vulnerable* version whenever it's resolved, but
  doesn't make installs reproducible. A real fix (pip-tools/`pip-compile`,
  or switching to Poetry/uv with a lockfile) touches every dependency in
  the tree and needs its own compatibility pass — out of scope for a
  same-day hardening pass.
- **GitHub Actions are pinned to mutable version tags (`@v4`), not commit
  SHAs.** Common practice, but a compromised upstream Action could push a
  same-tag update that CI trusts automatically. Low severity, deferred in
  favor of the higher-value fixes below; `dependabot.yml`'s new
  `github-actions` ecosystem entry (below) at least surfaces version bumps
  for review rather than them happening silently.
- **Branch-protection / required-status-checks configuration on `main` is
  not verifiable from the repository itself** — it's a GitHub repo-settings
  concern, not a file in this codebase. `frontend-tests.yml`'s own header
  comment documents a real past instance of this gap (PRs #182/#185 merged
  with zero CI checks run, before that workflow existed to cover
  `homeschool-tutor/`/`demo/`). Worth confirming directly in GitHub
  settings — required checks and force-push protection — before a
  production release; not something a code change can confirm or fix.

## Closed gaps

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
    `services/parent_recovery.py` adds a recovery code — a
    high-entropy backup credential, shown once at enrollment, deliberately
    independent of both `PARENT_PASSWORD` and `CHILD_PIN` so a leak of one
    doesn't expose the others. `routers/recovery.py`'s public (necessarily
    — a locked-out parent has no session to authenticate with) `/auth/
    recovery/*` endpoints require proving **at least 2** of {recovery
    code, TOTP, WebAuthn} — never just one — before issuing a narrowly-
    scoped token good for exactly one thing: setting a new password.
    Every credential change (in-app or via recovery) bumps a
    `credentials_version` embedded in every parent/parent_pending JWT at
    issuance and checked on every request (`core/deps.py`) — the piece
    that makes "recover access, set a new password" actually **end** a
    takeover: every other outstanding session, including an attacker's
    stolen token, stops working the instant the change commits, rather
    than lingering until natural expiry alongside the new one.

  All secrets that only ever need verifying, never redisplaying (the
  password override, the recovery code) are hashed with PBKDF2-HMAC-
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
  endpoints.py`, and `tests/test_deps_credentials_version.py`.

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
