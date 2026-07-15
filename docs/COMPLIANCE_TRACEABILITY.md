# Compliance & Security Traceability Matrix

Maps each legal/child-safety/security obligation raised during the beta
audit (`docs/BETA_READINESS_CHECKLIST.md`) to the exact code that satisfies
it, the test that verifies it, and the audit-log event that records it at
runtime. Built so an attorney or auditor doesn't have to take "it's handled"
on faith — every claim below cites a file, a test, or names the gap
explicitly if one exists.

**Methodology:** every implementation citation was read directly from
source at the commit noted; every test citation was confirmed to exist by
grepping the actual test file, not assumed from a name. "No test found"
means a real grep across every test file's contents came back empty, not
that a test wasn't searched for.

**Basis:** audited against `origin/main` @ `dc05738`, cross-referenced
against this session's working branch (`claude/clean-project-clone-s216ne`)
where it adds controls main doesn't have yet. Status column calls out
which base a control lives on.

**Status key:** 🟢 shipped & tested on `main` · 🟡 on this branch only,
pending merge · 🟠 partial (implemented, coverage or scope gap) · 🔴 gap,
no implementation yet.

---

| # | Obligation | Basis | Implementation | Test coverage | Audit trail | Status |
|---|---|---|---|---|---|---|
| R1 | Parent must affirmatively accept a platform-scope / no-diagnosis disclaimer before reaching any parent-only page | User requirement: sign-off/waiver gate | `core/parent_agreement.py` (`SECTIONS`, `CURRENT_VERSION`); `routers/parent_agreement.py` (`GET /status`, `POST /accept`); `homeschool-tutor/src/guards/RequireParentAgreement.tsx`; wired around `/setup`, `/pod`, `/progress`, `/sandbox` in `App.tsx` | `tests/test_parent_agreement.py` — 8 tests incl. re-prompt on stale version | `AuditEvent.PARENT_AGREEMENT_ACCEPTED` in `routers/parent_agreement.py::accept()` | 🟡 Built + tested on this branch; **does not exist on `main` yet** — not live until this branch merges |
| R2 | The disclaimer's liability/waiver wording must be attorney-reviewed before real users see it | User's explicit instruction; standard practice for waiver language | `core/parent_agreement.py`'s "Your Responsibility" section is a literal `[PLACEHOLDER — PENDING LEGAL REVIEW]` bracket | `test_sections_cover_scope_no_diagnosis_responsibility_and_acknowledgment` checks the section *exists*, cannot and does not check legal sufficiency | n/a | 🔴 Blocking gap — swap in reviewed text, then bump `CURRENT_VERSION` (forces re-consent automatically) |
| R3 | Bede must not claim to diagnose/screen ADHD, autism, or any condition, and must point concerned parents to a licensed professional | User requirement; avoids practicing-medicine/psychology-without-a-license exposure | `core/parent_agreement.py`, "No Diagnosis, No Screening" section — names ADHD/autism explicitly, explicitly frames `LearnerProfileData`'s attention/engagement signal as non-clinical | `test_no_diagnosis_section_names_adhd_and_autism_explicitly` | n/a (content, not runtime) | 🟡 Same branch-only status as R1. Resolves the "does LearnerProfileData need its own disclaimer mention" open question from the checklist — it's already named. |
| R4 | Voice biometric enrollment/override may only be performed by a parent, never a child | Biometric-data consent norms (BIPA/CUBI-style: authorized representative consents for a minor) | `routers/voice.py::enroll()` and `::override()` — both `Depends(require_parent)` (confirmed on both `main` and this branch) | `tests/test_voice_router.py` — wiring tests introspect each endpoint's `Depends(...)` default to confirm `require_parent`/`require_real_user` is actually attached (catches a silent dependency swap a direct function call can't), plus logic tests for enroll/verify/override/delete | `AuditEvent.VOICE_ENROLL`, `VOICE_OVERRIDE` | 🟡 Tested on this branch; pending merge into `main` |
| R5 | All student personal data (voice profiles, configs, narration, diagnostic evidence) encrypted at rest, never returned as plaintext | CLAUDE.md constraint; general biometric/PII handling practice | `core/encryption.py` (MASTER_SECRET → KEK → DATA_KEY, AES-256-GCM); every user-data table in `core/database.py` stores `LargeBinary`/BYTEA (`profile_enc`, `config_enc`, `assessment_enc`, etc.) | No dedicated `test_encryption.py`, but encrypt/decrypt round-trips are exercised incidentally through `conftest.py`, `test_interaction_signals.py`, `test_processing_style.py`, `test_record_skill_evidence.py` | `ExfiltrationGuard` (`core/middleware.py`) additionally scans outbound JSON for `"embedding"` arrays / `data_key` / `device_salt` as a defense-in-depth backstop | 🟢 Shipped, incidentally covered |
| R6 | A family can delete a child's biometric/config data | Deletion rights for minors' biometric data (general good practice, not a specific statute) | `DELETE /voice/profiles/{student_name}` (`routers/voice.py`), `DELETE /pod/configs/{student_name}` (`routers/pod.py`) — both `require_parent` | `tests/test_voice_router.py::test_remove_profile_404s_when_nothing_was_deleted` / `::test_remove_profile_logs_the_audit_event_on_success` cover the voice side; `routers/pod.py`'s delete endpoint still has no dedicated test | none dedicated | 🟠 Voice-side tested (branch-only, pending merge); pod-config deletion untested; still only per-item deletion exists — no single "erase this family's account entirely" action (checklist §2) |
| R7 | An auth token can't be replayed from a different device | Session-hijacking defense | `core/security.py::validate_fingerprint` (`hmac.compare_digest`); `core/deps.py::require_auth`; `core/middleware.py::compute_fingerprint` | `test_demo_fingerprint.py::test_parent_role_fingerprint_binding_is_unchanged` confirms parent-role binding directly; the file's main focus is the demo_code exemption case | `AuditEvent.TOKEN_FINGERPRINT_MISMATCH` | 🟢 Shipped & tested on `main` |
| R8 | Production must refuse to boot with a known-weak default secret/PIN | CLAUDE.md constraint | `core/config.py` — three `@model_validator(mode="after")` checks; `core/pin_policy.py::pin_is_strong` | `test_config.py`, `test_pin_policy.py` | n/a (startup-time refusal) | 🟢 Shipped & tested on `main` |
| R9 | Parent-supplied free text (`faith_emphasis`, `lesson_focus`, `current_unit`) can't be used to inject prompt-override instructions into Bede's system context | Prompt-injection defense (CLAUDE.md names this explicitly as the SSE-path mitigation) | `services/ai_service.py::_sanitize_parent_field` / `_INJECTION_PATTERN` (~line 444/459) | `tests/test_parent_field_sanitization.py` — unit tests for every named injection pattern plus HTML-tag stripping, and integration tests proving `_build_subject_prompt` sanitizes all three parent fields before they reach the assembled system prompt | n/a | 🟡 Tested on this branch; pending merge into `main` |
| R10 | Every security/compliance-relevant event is captured in an independent, encrypted audit trail that survives a failed request | CLAUDE.md constraint | `core/audit.py::AuditEvent` enum + `log_event()` opening its own `AsyncSessionLocal()` | `tests/test_audit_log.py` — real round trip against an in-memory SQLite engine with genuine AES-256-GCM encryption: persistence, encrypted-not-plaintext storage, truncation limits, corrupt-row handling, and that a write failure never propagates to the caller | — (this row *is* about the audit trail) | 🟡 Tested on this branch; pending merge. Writing this test surfaced a real bug (now fixed): `AuditLog.id` used plain `BigInteger`, which doesn't get SQLite's rowid-alias autoincrement, so every insert failed under a SQLite test engine — fixed with the same `BigInteger().with_variant(Integer(), "sqlite")` pattern `DiagnosticEvidenceLog.id` already used |
| R11 | Uploaded files (handwriting canvas image, narration file) are size-capped against storage/cost abuse | User requirement (this session) | `models/schemas.py`: `MAX_UPLOAD_BYTES`, `MAX_UPLOAD_BASE64_CHARS` (this branch only); `routers/voice.py::_MAX_AUDIO_BYTES = 10MB` (pre-existing, on `main`) | `tests/test_upload_size_limits.py` (this branch, 5 tests) | n/a | 🟡 Drawing/narration caps are branch-only, pending merge; voice audio cap already on `main` |
| R12 | Auth/voice/API traffic is rate-limited per IP | Abuse prevention | `core/middleware.py::RateLimitMiddleware` — `AUTH_LIMIT=10`, `API_LIMIT=120`, `VOICE_LIMIT=20` per minute | `test_middleware.py` | `AuditEvent.RATE_LIMITED` | 🟠 Shipped & tested, but in-process/in-memory only — no cross-instance sharing if ever scaled beyond one worker (checklist §1) |
| R13 | Collection of a child's personal data only happens after a parent sets up the account (COPPA-style "verifiable parental consent" posture) | COPPA (applicability pending attorney confirmation per checklist §2) | Structural: no self-serve child signup path exists in any router; a parent must create the pod and, for voice-required students, is the only role that can enroll voice (R4) | n/a — this is an architectural argument, not a certified compliance control | n/a | 🔴 No formal legal determination on record — flag alongside R2 for the same attorney pass |

---

## What this surfaced that the checklist didn't already say

- **R9 was the most important finding here, and is now closed** (on this branch). CLAUDE.md names `_sanitize_parent_field`/`_INJECTION_PATTERN` as *the* mitigation for prompt injection on the one path (`/tutor/chat` SSE) that `ExfiltrationGuard` deliberately doesn't scan. It had zero test coverage at the actual integration point; `tests/test_parent_field_sanitization.py` now covers it directly.
- **R4/R6 (voice router) and R10 (audit log) also now have dedicated tests.** Writing R10's test surfaced a real bug in the process — `AuditLog.id`'s plain `BigInteger` column silently failed every insert under a SQLite test engine (NOT NULL constraint), fixed with the `.with_variant(Integer(), "sqlite")` pattern already established for `DiagnosticEvidenceLog.id`. That's exactly the kind of thing "unverified by an automated test" hides.
- **R3 resolves the LearnerProfileData open question** from the beta checklist (§6) — the disclaimer already names the learner-profile feature explicitly, so that item can move from "in progress" to "done" once R1/R3 merge.
- **R1/R2/R3/R9/R10/R11's branch-only status is the same finding as checklist §0**, restated here as a compliance fact rather than a git-hygiene one: none of this session's consent-gate, sanitizer-integration, audit-log, or upload-limit tests are live in `main`'s CI until the branch merges. An attorney or auditor reviewing "what's actually deployed and tested" today would see none of them.
- **R6's pod-config deletion path is still untested** — only the voice-profile half of that obligation got covered this round; `routers/pod.py`'s delete endpoint remains a real gap.

## Keeping this current

This is a snapshot, not a standing check — nothing enforces that these rows
stay accurate as code changes. At minimum, re-verify this table:
- before finalizing legal text (R2), so the attorney is reviewing what's
  actually shipped, not a stale description;
- after rebasing this branch onto `main` (R1/R3/R4/R6/R9/R10/R11 move from 🟡 to 🟢);
- whenever `AuditEvent`, `routers/voice.py`, or `_sanitize_parent_field`
  change, since those are exactly the rows with the thinnest test coverage
  today.
