# COPPA readiness checklist (C-01 to C-35)

**What this is.** A readiness list for a future compliance audit. It maps each
control to its status and to the test or document that evidences it. It is
**not** a certification, an attestation, or a legal opinion, and nothing in
it claims Bede is COPPA compliant. Whether any control is sufficient is a
question for counsel and, where stated, an external assessor.

**Statuses.**
- `MET`: a test in this repository proves the control on the code path it names.
- `PARTIAL`: some of the control is built or proven; the rest is listed in the row.
- `GAP`: not built.
- `EXTERNAL`: cannot be proven by this repository (a counsel decision, a
  vendor contract, an operator act, or an assessor's report).
- `TODO`: owned by a different workstream; not updated by this change.
- Template-only rows say so. A template is not a completed activity.

**Workstream.** This document was written by the auth/voice/assurance
workstream. Rows marked `TODO` belong to the other workstreams (consent,
provider egress, logs and audit, demo identifiers, and the rest) and must be
filled from their reports. Do not infer a status for them from this file.

Source of the control list: the readiness assessment's section 4 (control
checklist). Related: `docs/COPPA_OPERATOR_PROFILE.md`,
`docs/COPPA_READINESS_TEMPLATES.md`, `docs/DATA_RETENTION.md`.

---

## 4a. Consent, notice and parental rights

| ID | Control | Status | Evidence | Set by |
|---|---|---|---|---|
| C-01 | Verifiable parental consent before child-identifying collection | TODO | — | consent workstream |
| C-02 | Consent ledger table | TODO | — | consent workstream |
| C-03 | Remove child first name from public-demo intake | TODO | — | demo workstream |
| C-04 | Per-child collection pause | TODO | — | consent workstream |
| C-05 | Parent "everything we hold" export | TODO | — | consent workstream |
| C-06 | Privacy notice pinned to consent version | TODO | — | consent workstream |

## 4b. Third-party disclosure and provider egress

| ID | Control | Status | Evidence | Set by |
|---|---|---|---|---|
| C-08 | Default-deny for child-data egress | TODO | — | provider workstream |
| C-09 | Provider qualification registry by feature, with expiry | TODO | — | provider workstream |
| C-10 | Wire-level no-store / no-training flags, request-capture test | TODO | — | provider workstream |
| C-11 | Vendor contracts and dated attestations | EXTERNAL | Counsel and operator record; no repository evidence | operator + counsel |
| C-12 | Qualify the `local` endpoint for network egress | TODO | — | provider workstream |
| C-13 | Single outbound boundary for child-data HTTP calls | TODO | — | provider workstream |
| C-14 | Cloud voice disabled for child data unless qualified | TODO | — | provider workstream |

## 4c. Identifiers, logs and retention

| ID | Control | Status | Evidence | Set by |
|---|---|---|---|---|
| C-15 | Log a pseudonymous learner id, not a name | TODO | — | logs workstream |
| C-16 | Redact exception text before logging | TODO | — | logs workstream |
| C-17 | Document log retention and shipping | TODO | — | logs workstream |
| C-18 | Audit log retention and IP truncation | TODO | — | logs workstream |
| C-19 | Demo session data retention matches code | TODO | `homeschool-api/tests/test_coppa_compliance.py` (candidate; not re-verified here) | demo workstream |
| C-20 | Encrypt or drop demo `student_name` / free text | TODO | — | demo workstream |
| C-21 | Retention bound for hosted child data (counsel sets value) | TODO | — | counsel + operator |

## 4d. Authentication, access and key management

| ID | Control | Status | Evidence | Set by |
|---|---|---|---|---|
| C-22 | Parent second factor required on a hosted profile | PARTIAL | Code: `routers/auth.py` (`mfa_enrollment_required` refusal), `routers/mfa.py` (`require_enrollment_or_elevated_parent`), switch `HOSTED_PROFILE` in `core/config.py`. Tests: `homeschool-api/tests/test_hosted_profile_auth.py` (refusal, enrollment token scope, self-hosted unchanged). Still open: the frontend must handle the refusal; the switch stays off on live family instances until it does. Operator guidance: `docs/COPPA_OPERATOR_PROFILE.md` §1-2. The route guard table `homeschool-api/tests/test_app_composition.py` was updated deliberately for the four enrollment routes and three new device routes | this workstream |
| C-23 | Child device pairing (PIN plus per-device token) | PARTIAL | Code: `routers/auth.py` (`_gate_child_device`, `/auth/child-devices` list/approve/revoke), `core/database.py` (`ChildDevicePairing`), `models/schemas.py` (`device_token`). Tests: `homeschool-api/tests/test_hosted_profile_auth.py` (unpaired refused, one-time token, token required, revocation, fingerprint still bound). Still open: frontend storage and approval UI. Guidance: `docs/COPPA_OPERATOR_PROFILE.md` §3 | this workstream |
| C-24 | Child role cannot read parent-only endpoints | TODO | `homeschool-api/tests/` role suites (candidate; not re-verified here) | auth workstream (other agent) |
| C-25 | Key separation and rotation drill | TODO | — | operator |
| C-26 | Backups encrypted and deletion-aware | PARTIAL | Runbook: `docs/COPPA_OPERATOR_PROFILE.md` §4 (trap explained: a pre-deletion backup restores the student's key; restore procedure; 30-day window proposed, **operator decision**). Not proven by a test: the restore test has not been run. Open: no automatic deletion replay after restore | this workstream |

## 4e. Voice biometrics

| ID | Control | Status | Evidence | Set by |
|---|---|---|---|---|
| C-27 | Biometric notice and consent before enrolment | TODO | — | consent workstream |
| C-28 | Delete voiceprints and any recordings on deletion | MET | `homeschool-api/tests/test_voiceprint_deletion.py`: parent delete and student deletion remove the `VoiceProfile` row and its readable form, and shred the key; enrol and delete write no file (runtime); no voice module opens a file for writing (static scan, with a guard on the scanner). Recordings: none are retained by any voice path (`docs/COPPA_OPERATOR_PROFILE.md` §5). Consent-revocation trigger for deletion is the consent workstream's | this workstream |

## 4f. Assurance, incident and governance

| ID | Control | Status | Evidence | Set by |
|---|---|---|---|---|
| C-29 | Written security program and retention policy kept current | PARTIAL | `docs/INFORMATION_SECURITY_POLICY.md` and `docs/RETENTION_POLICY.md` were checked against this change. Both are scoped to the public demo; no statement in either disagrees with the code this change adds, so neither was edited. Family-data retention is in `docs/DATA_RETENTION.md`, which gained the `child_device_pairings` note. Guards: `homeschool-api/tests/test_coppa_compliance.py` (existing). Counsel and operator review still required | this workstream |
| C-30 | Incident response with a child-data breach runbook | PARTIAL | Template only: `docs/COPPA_READINESS_TEMPLATES.md` C-30. Owner, tabletop date and notice analysis are placeholders (`[NOT STARTED]`). Existing `docs/INCIDENT_RESPONSE.md` is unchanged. No tabletop has been run | this workstream |
| C-31 | Independent third-party assessment | EXTERNAL | Template only: `docs/COPPA_READINESS_TEMPLATES.md` C-31 (scope, terms, findings register). No assessor selected; no report exists | operator |
| C-32 | Dependency and supply-chain gate | TODO | — | CI workstream |
| C-33 | COPPA guards kept in CI change filter | TODO | `homeschool-api/tests/test_coppa_compliance.py` (candidate) | CI workstream |
| C-34 | Data protection impact assessment for child profiling | EXTERNAL | Template only: `docs/COPPA_READINESS_TEMPLATES.md` C-34. Requires counsel's review and a signature. Not signed; not started | counsel |
| C-35 | Records of processing inventory | PARTIAL | Inventory written: `docs/COPPA_READINESS_TEMPLATES.md` C-35, rows for every cascade table plus `student_keys`. Checked by `homeschool-api/tests/test_processing_inventory.py` (each deletion-cascade table appears in the inventory). Not yet checked: the audit log, container logs and backups rows, which are marked open | this workstream |
