# G3 physical Mac and WebAuthn acceptance test

**Status: NOT RUN — Pilot HOLD.** This is a human-operated test procedure, not evidence of completed physical testing or authorization for real learners. Strict pre-pilot feature freeze remains. Use only disposable synthetic records, local-only models, and approved private equipment.

## Candidate and provenance

Before starting, record UTC time, operator, independent reviewer, exact Git commit, source-free package SHA-256, container image digests, Mac model, macOS version, CPU architecture, RAM, Docker Engine/Compose versions, browser and authenticator. Redact serial numbers and sensitive identifiers. Match the bundle architecture to the actual Docker Engine architecture. Use the packaged Verify-Bede.command, not a checkout-only script, for source-free certification. See MAC_PILOT_SMOKE.md and packaging/bundle/README.md.

Archive exact-head links and artifacts for backend, frontend, CodeQL, G1 staged, non-superuser PostgreSQL diagnostic and full 146-cell synthetic qualification. Verify 146 PASS and zero FAIL, ABSENT, BLOCKED or UNVERIFIED from the actual artifact. Independently confirm code/security review and required branch checks; do not infer them from a green workflow.

## Physical test matrix

| ID | Test | Required evidence |
| --- | --- | --- |
| G3-01 | Install source-free packaged bundle, verify HTTPS and trusted CA, restart Docker and host | Matching immutable SHA/digests, correct architecture, health before/after restart; never use insecure TLS bypass |
| G3-02 | Real browser WebAuthn invitation, registration and authentication with Mac platform authenticator or compatible key | Valid origin, RP ID and challenge succeed; invalid challenge/origin and unauthorized invitation denied; mocks do not count |
| G3-03 | Two synthetic campuses, same-name learners, educator roster, unknown UUID and revoked grants | Positive authorized operations and uniform cross-campus/unassigned/stale-grant denials, no information leakage |
| G3-04 | Teacher evidence, verified diagnostic, source-linked recommendation, approve/edit/reject | Canonical source hashes, explicit abstention, durable version-checked decision and atomic audit |
| G3-05 | Authorized local-only synthetic tutoring SSE, then revoke access during active and idle streams | Grant checked before any model contact, at every event and before commit; no post-revocation output or durable turns, no paid/hosted fallback |
| G3-06 | Lost-device recovery with separate authorized administrator approval | Old credential and sessions denied; campus directory accounts cannot administer recovery; audit and replacement credential verified |
| G3-07 | Educator offboarding and replay of old sessions, roster access and SSE | Old reads, writes, diagnostics and active streams denied, including after restart |
| G3-08 | Synthetic owner deletion with passkey elevation, typed name, fault injection and populated caches | Canonical G1/G2/source deletion, same-transaction SHA receipt, rollback on audit failure, independent proof of cache eviction and truthful backup retention |
| G3-09 | Destructive backup restore into separate disposable environment only | Authorized key custody, measured RTO/RPO, preserved revocation and restore evidence; never touch production or real data |
| G3-10 | Local performance, shutdown and recovery | CPU/RAM, latency, failures, operator recovery and capacity limits measured rather than assumed |

Every row starts NOT RUN. Record PASS, FAIL, BLOCKED or NOT RUN with UTC timestamp, exact SHA, expected and observed behavior, and redacted evidence reference. Stop and preserve evidence on security failure. Local model unavailability is BLOCKED, not PASS. Owner-paused #603 real-weights testing is not authorized by this plan.

## Evidence packet and human decisions

Store outside Git: manifest (SHA, device, package/image digests), checks (each row and redacted observations), ci (run URLs, archived 146-cell result, review and protection policy), and acceptance (separate dated engineering acceptance and owner Pilot GO/HOLD decision). Never commit credentials, passkey secrets, private keys, unredacted screenshots, or real student records.

Post only meaningful redacted SHA evidence to issues #588 and #599. Physical Mac, actual WebAuthn and owner acceptance remain NOT RUN until executed. No production deployment, public school activation, billing, real learner records, or automatic Pilot GO. A documentation merge does not lift the HOLD.
