# COPPA readiness templates (C-30, C-31, C-34, C-35)

These are **blank templates**. Writing a template here does not mean the
activity has happened. Every owner, date and outcome field is a placeholder
(`[OWNER]`, `[DATE]`, `[NOT STARTED]`) and must be completed by the named
person in the operator's own records. Do not copy a completed version back
into this repository; keep completed copies with the company's records,
as `docs/INTELLECTUAL_PROPERTY.md` does for its own instruments.

Status of each control is tracked in `docs/COPPA_READINESS_CHECKLIST.md`.

---

## C-30. Child-data incident playbook

Extends `docs/INCIDENT_RESPONSE.md`. Use this section when the incident
involves children's personal information.

**Owner:** `[OWNER: responsible individual]` · **Last tabletop exercise:** `[DATE — NOT STARTED]`

### 1. Triage (first hour)

- [ ] Record the time the incident was detected and by whom: `[TIME / DETECTOR]`
- [ ] Decide whether child personal information may be involved (student
      names, voice profiles, transcripts, narration, mastery data, audit IPs).
      `[YES / NO / UNKNOWN]`
- [ ] Contain: revoke affected credentials (`CHILD_PIN` / `PARENT_PASSWORD`
      rotation, `POST /auth/child-devices/{id}/revoke`, device revocation),
      and take a backup **before** changing anything else. `[ACTIONS TAKEN]`
- [ ] Preserve evidence: the audit log, container logs and the backup
      identifier. Do not edit the audit log. `[EVIDENCE LOCATION]`

### 2. Assess

- [ ] Which families / students / record types: `[SCOPE]`
- [ ] Data state at the time: encrypted or plaintext (see
      `docs/DATA_RETENTION.md` and `docs/INFORMATION_SECURITY_POLICY.md` §3)
- [ ] Whether the data was accessed, exfiltrated, or only exposed: `[FINDING]`
- [ ] Which vendor(s) received the data, if any (`docs/VENDOR_DATA_FLOW.md`)

### 3. Notify (decision for counsel)

- [ ] Parent notification drafted and reviewed by counsel: `[DATE / COUNSEL]`
- [ ] FTC or state notice analysis by counsel: `[OUTCOME — NOT STARTED]`
- [ ] Vendor notification where a contract requires it: `[VENDOR / DATE]`

This playbook does not decide whether a notice is legally required. That
analysis belongs to counsel.

### 4. Recover and review

- [ ] Restore from a clean backup if needed, then run the procedure in
      `docs/COPPA_OPERATOR_PROFILE.md` §4 (re-delete students removed after
      the backup)
- [ ] Post-incident review written within `[N]` days: `[DATE]`
- [ ] Any control that would have prevented or shortened the incident is
      added to `docs/COPPA_READINESS_CHECKLIST.md` with a test

---

## C-31. External assessment (scope and engagement)

**Status:** `[NOT STARTED]`  **Assessor:** `[NAME — not yet selected]`  **Report date:** `[DATE]`

### Scope statement

- Deployment under test (version / commit SHA): `[SHA]`
- Hosting topology (`docs/DEPLOYMENT_TOPOLOGY.md`): `[TOPOLOGY]`
- In scope: network exposure, authentication (parent MFA, child PIN and
  device pairing), session handling, encryption at rest, container hardening,
  TLS, rate limiting, the public demo and marketing site
- Out of scope: `[LIST]`
- Test accounts and synthetic data only; no real child data: `[CONFIRMED BY]`

### Engagement terms

- Independence statement from the assessor: `[ATTACHED / DATE]`
- Rules of engagement and emergency contact: `[CONTACT]`
- Report delivery and handling of findings: `[PROCESS]`

### Findings register (fill in from the report)

| ID | Severity | Finding | Owner | Target date | Status |
|---|---|---|---|---|---|
| `[ID]` | `[SEV]` | `[TEXT]` | `[OWNER]` | `[DATE]` | `[OPEN]` |

---

## C-34. Data protection impact assessment (DPIA)

Covers profiling of children for mastery and adaptive instruction, and
voice biometrics. Prepared for counsel's review; the assessment itself is
counsel's and the operator's to sign.

**Status:** `[NOT STARTED]`  **Prepared by:** `[OWNER]`  **Approved by:** `[NAME, DATE — NOT SIGNED]`

### 1. Description of processing

- Purpose: `[STATE PURPOSE]`
- Data subjects: children enrolled by a parent or school, and their parents
- Data categories: see the processing inventory (C-35)
- Recipients: see the processing inventory and `docs/VENDOR_DATA_FLOW.md`
- Retention: `docs/DATA_RETENTION.md`; backup window
  `docs/COPPA_OPERATOR_PROFILE.md` §4 (operator decision: `[VALUE]`)

### 2. Necessity and proportionality

- Why each data category is needed for the stated purpose: `[ANALYSIS]`
- Less intrusive alternatives considered (for example, mastery data kept
  only for the session: `RETAIN_MASTERY_PROFILES=false`): `[ANALYSIS]`

### 3. Profiling and automated decisions

- Mastery estimates, learner profile and adaptive recommendations: what they
  are, what they are not (`docs/MASTERY.md`, `docs/ADAPTIVE_LEARNING_INTELLIGENCE.md`)
- Whether any output affects a child's access to something: `[FINDING]`

### 4. Voice biometrics

- What is stored (one encrypted embedding per child; no audio retained)
- Consent and notice for biometric enrolment: `[STATUS — counsel]`
- Applicable state biometric law: `[COUNSEL ANALYSIS — NOT STARTED]`

### 5. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation | Residual |
|---|---|---|---|---|
| `[RISK]` | `[L]` | `[I]` | `[CONTROL IDs]` | `[R]` |

### 6. Sign-off

`[SIGNATURE — NOT SIGNED]`  `[DATE]`

---

## C-35. Records of processing (processing inventory)

Operator's record of what personal information is processed, why, by whom,
and where it lives. Checked against the code by hand each review: every
student-scoped table in `homeschool-api/core/database.py` must appear once
below, and `services/student_deletion.py` must cascade to it.

**Owner:** `[OWNER]`  **Last reviewed:** `[DATE — NOT STARTED]`

| # | Table / store | Personal information | Purpose | Lawful basis / notice | Recipients | Retention | Deleted by | Encrypted |
|---|---|---|---|---|---|---|---|---|
| 1 | `student_configs` | Student name, grade, subjects, context | Lesson plan | `[COUNSEL]` | none | until student deleted | Delete all data | Yes (student key) |
| 2 | `voice_profiles` | Voice embedding | Voice sign-in | `[COUNSEL — biometric]` | none | until deleted | Delete all data; `DELETE /voice/profiles/{s}` | Yes |
| 3 | `narration_assessments` | Rubric scores | Feedback | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 4 | `learner_profiles` | Learner-type read | Adaptation | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 5 | `learner_behavior_checks` | Adaptation counter | Adaptation check | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 6 | `lesson_bookmarks` | Resume note per subject | Continuity | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 7 | `mastery_profiles` | Skill probabilities | Diagnostic | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 8 | `diagnostic_evidence_log` | Probe deltas | Diagnostic | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 9 | `skill_activity_log` | Completed-work events | Work ledger | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 10 | `adaptive_instruction_traces` | Recommendations | Parent review | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 11 | `educator_assessment_evidence` | External scores | Parent records | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 12 | `session_transcripts` | Session transcript | Parent review | `[COUNSEL]` | `[AI PROVIDER — see VENDOR_DATA_FLOW]` | until student deleted | Delete all data | Yes |
| 13 | `api_usage_events` | Token counts per student | Cost | `[COUNSEL]` | none | until student deleted | Delete all data | Yes |
| 14 | `child_device_pairings` | Tablet id, user agent, token digest (no student name) | Child sign-in control | `[COUNSEL]` | none | until parent revokes | Revocation (not student deletion; device-level) | Digest only |
| 15 | `audit_logs` | Event, IP, user agent | Security | `[COUNSEL]` | none | `[OPEN — C-18]` | Not deleted by student deletion | Yes |
| 16 | Container / host logs | `[TO INVENTORY]` | Operations | `[COUNSEL]` | `[HOST]` | `[OPEN — C-17]` | `[OPEN]` | `[OPEN]` |
| 17 | Backups | Copies of 1-15 | Recovery | `[COUNSEL]` | none | `[OPERATOR DECISION — 30 days proposed]` | Restore procedure | Yes |
| 18 | `student_keys` | Wrapped per-student data key (the shredding switch for rows 1-13, 19-21 and 22) | Encryption | `[COUNSEL]` | none | until student deleted | Delete all data (destroyed, not just deleted) | Wrapped under DATA_KEY |
| 19 | `practice_assessments` | Reading of a photographed quiz (no names, schools or dates) | Practice Coach | `[COUNSEL]` | `[CLOUD READER — only with per-upload consent, see docs/PRACTICE_COACH.md]` | until student deleted | Delete all data | Yes (student key) |
| 20 | `practice_sets` | Parent-approved practice set | Practice Coach | `[COUNSEL]` | none | until student deleted | Delete all data | Yes (student key) |
| 21 | `educator_roster_assignments` | Which educator may see which learner (pilot roster) | Classroom pilot | `[COUNSEL]` | none | until student deleted or grant revoked | Delete all data | Yes (student key) |
| 22 | `consent_records` | Consent method, notice-version hash, scope, granted/revoked times; parent label and revocation reason encrypted | Parental consent ledger | `[COUNSEL]` | none | until student deleted `[COUNSEL — consent evidence retention]` | Delete all data | Partly (parent label and reason under student key; student name, method, hash, scope and times are plain columns) |
| 23 | `student_collection_state` | Per-child collection pause timestamp | Collection pause | `[COUNSEL]` | none | until student deleted | Delete all data | No (timestamp only; student name key) |
| 24 | `installation_inventory` | Install id, installation receipt id, mode, school location id, registered-at, license-server outcome (no child data, no names) | Permitted-installation record | `[COUNSEL]` | none (local; the license-server leg sends only the existing `{license_key, install_id}`) | `[PROPOSAL ONLY — kept while the installation exists; no purge job]` | Not deleted by student deletion | No |

Rows marked `[OPEN]` are not complete and must not be read as controlled.
A row is complete only when every cell is filled by the operator and each
retention claim is backed by a test or a dated procedure.
