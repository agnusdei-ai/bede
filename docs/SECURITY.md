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

- **Pre-deployment adversarial testing — partial.** A first-pass adversarial
  review (2026-07-17) manually probed the deterministic layers —
  `check_safeguarding`, `_INJECTION_PATTERN`, `_redact_credentials` — with
  known jailbreak/bypass technique categories and real ambiguous-phrasing
  false-positive checks (`tests/test_safeguarding.py`), and found and closed
  one real gap (see Closed gaps below). Still missing, and out of what this
  environment can do: any test against the **live model** — no jailbreak
  probing of the constitution/`<ethical_boundaries>` actually happened,
  since that requires real Anthropic API calls this sandbox doesn't have
  credentials or approval for — and no **third-party** red-team or
  independent adversarial-robustness assessment. Both remain open.

## Closed gaps

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
  dependency list): the full prompt context to Anthropic (required), text
  sent to OpenAI's TTS API specifically — clarifying that voice
  *enrollment* transcription is local Whisper, not a network call, despite
  sharing a vendor name — and the four independent Resend email triggers.
  Also states explicitly that voice biometrics never leave the machine.
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
  the already-required `ANTHROPIC_API_KEY` rather than adding a new vendor
  or a self-hosted model — `docs/LOCALIZATION.md` had explicitly flagged
  that exact tradeoff as the reason a "parallel safety-classifier model"
  was out of scope for that work; this closes it without introducing
  either objection. Fails open twice over (inside `classify_child_message`
  itself, and again at the router call site) so a classifier outage never
  blocks a legitimate tutoring turn. **Real cost/latency tradeoff, stated
  plainly**: this adds one Haiku call (roughly 200–500ms, real API cost)
  to every tutoring turn except `[START]`/`[CONTINUE]` sentinels and turns
  the free regex already caught. Covered by `tests/test_moderation.py`
  and `tests/test_moderation_router.py`.

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
