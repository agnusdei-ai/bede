# COPPA release gates — evidence required

Status: **HOLD** for real learner data and public claims of COPPA compliance.
This checklist is a release control, not a certification.

## G1 — Parent-owned records
- [ ] Parent/educator authenticated local profile import and explicit consent
- [ ] Encrypted at-rest profile and diagnostic history survive restart
- [ ] Unauthorized users and cross-campus tenants cannot retrieve records
- [ ] Local deletion and key destruction tested, including backup behavior
- [ ] Demo diagnostic data stays ephemeral until explicit local import; no implicit server persistence

## G2 — Provider egress
- [ ] COPPA enforcement enabled in release configuration
- [ ] Every chat, moderation, embeddings, speech, transcription and telemetry egress inventoried
- [ ] Cloud providers blocked for child data unless binding no-training/no-reuse terms, account settings and retention evidence are approved
- [ ] Primary, failover, override and experimental adapters tested for denial
- [ ] Local-only fallback verified; no silent cloud fallback
- [ ] Host/network egress policy enforced and tested separately from HTTP middleware

## G3 — Security monitoring
- [x] Security mailbox defaults to bede@agnusdei.ai in application code
- [x] Blocked exfiltration routes generate privacy-safe notification attempts
- [x] Duplicate suppression and mail transport retry covered by synthetic tests (execution pending)
- [ ] End-to-end synthetic block -> audit -> email delivery evidence
- [ ] Alert telemetry integrated with metrics/traces and incident runbook
- [ ] Network firewall/tunnel isolation and negative egress tests

## G4 — Legal and operational readiness
- [ ] Current parent notice and verifiable consent reviewed
- [ ] Parent review, export, correction and deletion exercised
- [ ] School authorization and school-specific data agreements reviewed
- [ ] Retention, security officer, incident response, vendors and independent security review approved
- [ ] G1/G2/G3 synthetic CI and Mac-packaged installation evidence attached
- [ ] Explicit owner release authorization; no real-child-data GO by inference

**Known limits:** Application middleware does not govern arbitrary network
connections. The COPPA policy switch is opt-in during migration; its
presence does not prove it is enabled in any deployed environment.
Email alerts depend on an independently configured outbound mail service.
