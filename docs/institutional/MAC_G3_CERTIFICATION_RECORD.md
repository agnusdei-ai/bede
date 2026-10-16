# Bede | G3 physical-Mac certification record

**Classification:** Controlled engineering acceptance / synthetic institutional pilot  
**Owner:** Agnus Dei Technologies, LLC  
**Companion procedure:** [MAC_G3_CERTIFICATION_RUNBOOK.md](MAC_G3_CERTIFICATION_RUNBOOK.md)  
**Template status:** All rows deliberately NOT RUN until actual physical-device evidence exists. **This form is not an issued certificate.**

## A. Controlled build and devices

| Field | Actual recorded value |
| --- | --- |
| Test session ID / UTC start-end | NOT RECORDED |
| Test operator / independent reviewer | NOT RECORDED |
| Bede repository and source code SHA | `agnusdei-ai/bede` / NOT RECORDED |
| Reference integrated application SHA | `d3eb645c2de1058bb8056005a09c7d40446cea20` (#616 to main) |
| 146/146 synthetic matrix evidence source | Candidate `6574a0e1b69ed3b162c39c626be316c4e457db4e`; independently link artifact |
| Operator package workflow run / artifact ID | NOT RECORDED |
| Operator archive name and SHA-256 | NOT RECORDED |
| Embedded `RELEASE` / `ARCH` / image digests | NOT RECORDED |
| Host physical Mac model, chip and CPU arch | NOT RECORDED |
| Host macOS build / FileVault | NOT RECORDED |
| Host memory, storage and free space | NOT RECORDED |
| Docker Desktop / Compose / Postgres versions | NOT RECORDED |
| Host model provider, model digest, runtime and location | NOT RECORDED |
| Client Mac model, macOS, browser build (if applicable) | NOT RECORDED |
| Client authenticator / actual WebAuthn UV method | NOT RECORDED |
| Server HTTPS hostname, CA fingerprint and private LAN mode | NOT RECORDED |
| Operator-controlled recovery host / backup trust domain | NOT RECORDED |
| Evidence storage URI or restricted folder and retention | NOT RECORDED |

Do not place secrets, tokens, actual passkey responses, enrollment links, `.env`, private keys, raw student content or plaintext backups in this record or attached evidence. Mask synthetic test accounts where publicly circulated.

## B. Mandatory acceptance matrix

Allowed outcomes: **PASS**, **FAIL**, **BLOCKED**, **NOT RUN**. Record exact UTC, operator, evidence URI and a concise observed result for every applicable row. A PASS may not be inferred from code existence, CI or another row's result.

| ID | Physical-Mac acceptance requirement | Outcome | Evidence reference / UTC |
| --- | --- | --- | --- |
| G3-01 | Approved source SHA matches sealed package, image arch and native Mac Docker architecture; clean source-free install, trusted HTTPS, health and private listener verified | NOT RUN | — |
| G3-02 | Actual educator WebAuthn passkey enrollment/sign-in, replay denial, prompt cancel/retry and no insecure fallback | NOT RUN | — |
| G3-03 | Two same-named synthetic learners on different campus UUIDs: valid roster access and uniform cross-campus/unknown/revoked denial | NOT RUN | — |
| G3-04 | Synthetic G2 evidence -> recommendation/abstention -> approve/edit/reject -> hash-chained ledger -> approved-only instruction | NOT RUN | — |
| G3-05 | Approved-only local tutoring SSE, durable synthetic history/diagnostic provenance and active-stream revocation; no external inference or automatic learner delivery | NOT RUN | — |
| G3-06 | Administrator-authorized lost-device recovery: separate real passkey, verified prior mailbox, old key/session invalid, new key works | NOT RUN | — |
| G3-07 | Roster revoke, campus membership disable and whole-educator account disable: old tokens/API/voice/tutor streams refused; other campus unaffected | NOT RUN | — |
| G3-08 | Independently administered Bede recovery environment rejects campus AD/Entra/SSO/directory administrator and backup-agent control; Bede operator permitted | NOT RUN | — |
| G3-09 | Stop/start/reboot or documented restart with preserved encrypted state, no restored revoked access, private DNS/TLS still valid | NOT RUN | — |
| G3-10 | Encrypted backup verify and **isolated** clean recovery rehearsal with proper independent keys; no destructive test on actual pilot records | NOT RUN | — |
| G3-11 | Security/accessibility operator observation: native browser errors, secret-free evidence, safe failure, no real learner/billing activation | NOT RUN | — |

For a **Mac mini appliance capacity claim**, attach a separate **G3-CAP** record with real workload measurements evaluated under `core.mac_bundle_qualification` for the exact chip/SKU. If concurrency is not part of this invite-only pilot, explicitly state **capacity not certified; no throughput claim** — never substitute a stub or pretend that passing G3 validates classroom scale.

## C. Automated vs human evidence map

| Evidence source | Value from actual run | Scope limit |
| --- | --- | --- |
| Synthetic qualification matrix artifact (exact code SHA) | 146/146 on original integrated candidate; artifact/run URI: **TO ATTACH** | Virtual WebAuthn; stubbed local model and mail |
| `mac-check-out/mac-check-result.json` | **NOT RUN** | Real teacher browser passkey and six checks; virtual administrator; source checkout, not package |
| `mac-check-out/mac-check-calls.json` | **NOT RUN** | Route templates, status codes, hashes and counts only |
| `bede-evidence/<UTC>/summary.txt` and `health.json` | **NOT RUN** | Source-free installed package / verified HTTPS health only |
| Redacted actual G2, recovery, offboarding and restart test observations | **NOT RUN** | Physical installed system and human-controlled credentials |
| Recovery-plane directory negative test and isolated backup restore evidence | **NOT RUN** | Must be independent of campus identity/backup administration |

**Evidence integrity ledger** — enter each artifact as a new row:

| UTC captured | Scenario ID | Private filename / location | SHA-256 | Reviewed/redacted by |
| --- | --- | --- | --- | --- |
| — | — | — | — | — |

## D. Defects, exceptions and environmental gaps

| Issue / finding | Affected case | Severity | Owner | Resolution commit or environmental remediation | Re-test evidence |
| --- | --- | --- | --- | --- | --- |
| None recorded yet; this is not a claim of defect-free operation | — | — | — | — | — |

**No blanket exceptions.** A mandatory FAIL/BLOCKED/NOT RUN means G3 NOT CERTIFIED. New code or installer changes require impact-based qualification on the changed exact SHA; documentation-only edits do not themselves invalidate existing application-test evidence. Environmental fixes require new physical evidence for only the affected case(s).

## E. Certification and release decisions — separate authorities

**G3 engineering/device decision**

- Verdict: **NOT CERTIFIED — NOT RUN**
- Exact certified artifact SHA: **NOT RECORDED**
- All mandatory cases PASS with evidence? **NO**
- Outstanding security/environmental gaps: **NOT REVIEWED**
- Engineering verifier name / UTC approval: **NOT SIGNED**
- Independent security reviewer name / UTC approval: **NOT SIGNED**

**Invite-only pilot release authorization**

- Pilot GO verdict: **NOT AUTHORIZED BY THIS RECORD**
- Authorized sites and participant counts: **NOT RECORDED**
- Synthetic-only vs separately approved real-data scope: **SYNTHETIC ONLY**
- Deployment topology, inference model and support contacts: **NOT RECORDED**
- Owner identity / explicit approval timestamp: **NOT SIGNED**
- Pilot rollback, stop, deletion, retention and escalation owner: **NOT RECORDED**

A completed G3 form evidences a particular Mac build, architecture, tested load and trust topology. It does **not** certify all macOS hardware, classroom throughput, student outcomes, commercial readiness, or a public release.
