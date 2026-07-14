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
| R4 | Voice biometric enrollment/override may only be performed by a parent, never a child | Biometric-data consent norms (BIPA/CUBI-style: authorized representative consents for a minor) | `routers/voice.py::enroll()` and `::override()` — both `Depends(require_parent)` (confirmed on both `main` and this branch) | **No dedicated router test found** — grepped every test file on `main` for `voice_auth`/`enroll_student`/voice-router imports; none exist. Enforcement rests entirely on the `require_parent` dependency being correctly wired, unverified by an automated test. | `AuditEvent.VOICE_ENROLL`, `VOICE_OVERRIDE` | 🟠 Implemented, real test-coverage gap — worth a direct router test before beta given how sensitive this data is |
| R5 | All student personal data (voice profiles, configs, narration, diagnostic evidence) encrypted at rest, never returned as plaintext | CLAUDE.md constraint; general biometric/PII handling practice | `core/encryption.py` (MASTER_SECRET → KEK → DATA_KEY, AES-256-GCM); every user-data table in `core/database.py` stores `LargeBinary`/BYTEA (`profile_enc`, `config_enc`, `assessment_enc`, etc.) | No dedicated `test_encryption.py`, but encrypt/decrypt round-trips are exercised incidentally through `conftest.py`, `test_interaction_signals.py`, `test_processing_style.py`, `test_record_skill_evidence.py` | `ExfiltrationGuard` (`core/middleware.py`) additionally scans outbound JSON for `"embedding"` arrays / `data_key` / `device_salt` as a defense-in-depth backstop | 🟢 Shipped, incidentally covered |
| R6 | A family can delete a child's biometric/config data | Deletion rights for minors' biometric data (general good practice, not a specific statute) | `DELETE /voice/profiles/{student_name}` (`routers/voice.py`), `DELETE /pod/configs/{student_name}` (`routers/pod.py`) — both `require_parent` | Not directly confirmed (same gap as R4) | none dedicated | 🟠 Partial — only per-item deletion exists; no single "erase this family's account entirely" action (checklist §2) |
| R7 | An auth token can't be replayed from a different device | Session-hijacking defense | `core/security.py::validate_fingerprint` (`hmac.compare_digest`); `core/deps.py::require_auth`; `core/middleware.py::compute_fingerprint` | `test_demo_fingerprint.py::test_parent_role_fingerprint_binding_is_unchanged` confirms parent-role binding directly; the file's main focus is the demo_code exemption case | `AuditEvent.TOKEN_FINGERPRINT_MISMATCH` | 🟢 Shipped & tested on `main` |
| R8 | Production must refuse to boot with a known-weak default secret/PIN | CLAUDE.md constraint | `core/config.py` — three `@model_validator(mode="after")` checks; `core/pin_policy.py::pin_is_strong` | `test_config.py`, `test_pin_policy.py` | n/a (startup-time refusal) | 🟢 Shipped & tested on `main` |
| R9 | Parent-supplied free text (`faith_emphasis`, `lesson_focus`, `current_unit`) can't be used to inject prompt-override instructions into Bede's system context | Prompt-injection defense (CLAUDE.md names this explicitly as the SSE-path mitigation) | `services/ai_service.py::_sanitize_parent_field` / `_INJECTION_PATTERN` (~line 444/459) | **No test found.** `test_diagnostic_prompt_injection.py` exists but tests something unrelated (demo-vs-db diagnostic content cross-contamination), not this sanitizer. Grepped every test file's content on `main` for `_sanitize_parent_field`/`_INJECTION_PATTERN` — zero matches. | n/a | 🔴 Real gap — this is the control CLAUDE.md cites as *the* defense for the SSE path (which deliberately isn't scanned server-side), and it has no automated test |
| R10 | Every security/compliance-relevant event is captured in an independent, encrypted audit trail that survives a failed request | CLAUDE.md constraint | `core/audit.py::AuditEvent` enum + `log_event()` opening its own `AsyncSessionLocal()` | `log_event`/`AuditEvent` only appear in `conftest.py` (as a test fixture stub) across all of `main`'s tests — **no test confirms an event is actually persisted and later readable** | — (this row *is* about the audit trail) | 🟠 Mechanism exists, un-verified by a real test — most tests appear to stub it out rather than assert against it |
| R11 | Uploaded files (handwriting canvas image, narration file) are size-capped against storage/cost abuse | User requirement (this session) | `models/schemas.py`: `MAX_UPLOAD_BYTES`, `MAX_UPLOAD_BASE64_CHARS` (this branch only); `routers/voice.py::_MAX_AUDIO_BYTES = 10MB` (pre-existing, on `main`) | `tests/test_upload_size_limits.py` (this branch, 5 tests) | n/a | 🟡 Drawing/narration caps are branch-only, pending merge; voice audio cap already on `main` |
| R12 | Auth/voice/API traffic is rate-limited per IP | Abuse prevention | `core/middleware.py::RateLimitMiddleware` — `AUTH_LIMIT=10`, `API_LIMIT=120`, `VOICE_LIMIT=20` per minute | `test_middleware.py` | `AuditEvent.RATE_LIMITED` | 🟠 Shipped & tested, but in-process/in-memory only — no cross-instance sharing if ever scaled beyond one worker (checklist §1) |
| R13 | Collection of a child's personal data only happens after a parent sets up the account (COPPA-style "verifiable parental consent" posture) | COPPA (applicability pending attorney confirmation per checklist §2) | Structural: no self-serve child signup path exists in any router; a parent must create the pod and, for voice-required students, is the only role that can enroll voice (R4) | n/a — this is an architectural argument, not a certified compliance control | n/a | 🔴 No formal legal determination on record — flag alongside R2 for the same attorney pass |

---

## What this surfaced that the checklist didn't already say

- **R9 is the most important finding here.** CLAUDE.md names `_sanitize_parent_field`/`_INJECTION_PATTERN` as *the* mitigation for prompt injection on the one path (`/tutor/chat` SSE) that `ExfiltrationGuard` deliberately doesn't scan. That control has zero test coverage. If it silently regressed, nothing in CI would catch it.
- **R4/R6 (voice router) and R10 (audit log) have no dedicated tests either** — all three are "trust the wiring" today, verified only by manual reading, not by CI.
- **R3 resolves the LearnerProfileData open question** from the beta checklist (§6) — the disclaimer already names the learner-profile feature explicitly, so that item can move from "in progress" to "done" once R1/R3 merge.
- **R1/R2/R3/R11's branch-only status is the same finding as checklist §0**, restated here as a compliance fact rather than a git-hygiene one: none of this session's consent-gate or upload-limit work is live in production until the branch merges. An attorney reviewing "what's actually deployed" today would see none of R1–R3.

## Keeping this current

This is a snapshot, not a standing check — nothing enforces that these rows
stay accurate as code changes. At minimum, re-verify this table:
- before finalizing legal text (R2), so the attorney is reviewing what's
  actually shipped, not a stale description;
- after rebasing this branch onto `main` (R1/R3/R11 move from 🟡 to 🟢);
- whenever `AuditEvent`, `routers/voice.py`, or `_sanitize_parent_field`
  change, since those are exactly the rows with the thinnest test coverage
  today.
