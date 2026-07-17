# Security & Compliance Posture

This documents Bede's security architecture in terms auditors and
compliance frameworks ask for — a companion to the code-level description
in `CLAUDE.md`'s "Security Constraints" section, not a replacement for it.
Like `docs/DATA_RETENTION.md`, this is a factual description of what the
code does, **not legal advice or a certification** — neither AIUC-1 nor
SOC 2 compliance can be established by a document; both require an
accredited third-party auditor's opinion after a live assessment.

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

- **Pre-deployment adversarial testing.** No red-team report, jailbreak
  test suite, or third-party adversarial-robustness assessment exists yet
  for the constitution and safeguarding regexes in `ai_service.py`.
- **Active alerting on the audit log.** `core/audit.py` writes an
  encrypted, independent audit trail, but nothing currently watches it
  for anomalous access patterns.
- **Formal incident response plan.** No named security contact,
  severity/escalation matrix, or breach-notification procedure exists
  yet.
- **SBOM.** Dependencies (`requirements.txt`, `package.json`) are curated
  and purpose-commented but not published as a CycloneDX/SPDX SBOM.

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

## SOC 2 Type 2

SOC 2 Type 2 additionally requires an accredited CPA firm to observe
these controls operating effectively over a 6–12 month window, plus a
documented policy set (Information Security, Access Control, Change
Management, Vendor Management, Risk Assessment) — none of which a
codebase alone can satisfy. The technical controls this repository
already has (encryption at rest, constant-time auth, rate limiting,
security headers, container hardening, the encrypted independent audit
log) map most directly to the Security and Confidentiality criteria;
Availability, Processing Integrity, and Privacy have partial technical
coverage but no accompanying policy documentation yet.
