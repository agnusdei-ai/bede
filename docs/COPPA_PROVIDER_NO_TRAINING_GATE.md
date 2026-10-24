# COPPA provider no-training gate — pre-release qualification

Status: **HOLD for external child-data processing until independently evidenced.** This is a scoped compliance control record, not a COPPA certification or a change to the approved synthetic pilot.

## Required invariant

No child message, voice recording, drawing, assessment, diagnostic evidence, or learner profile may be used by Bede or a third-party model provider to train, fine-tune, evaluate, improve, or build datasets for general-purpose models. No opt-in for such reuse is permitted in a child-facing flow. The prohibition includes failover, moderation, transcription, speech synthesis, diagnostics, and telemetry, not just the primary chat call.

An API request flag cannot override a provider's terms or account-level processing practices. Where an API supports an explicit no-store/no-training option, enforce the provider-supported setting and test the emitted request. Where no such flag exists, do **not** invent a parameter: require verified enterprise/API terms, contractual no-training commitment, retention controls, and a dated account configuration attestation. If evidence is missing, disable that external provider for child data (fail closed); use a qualified local inference path instead. Never silently fail over to an unqualified cloud provider.

## Current code review (2026-10-24)

- `services/adapters/router.py` chooses configured local, OpenAI, Mistral, or Anthropic adapters and permits ordered failover/live override. Credential presence is not privacy qualification.
- `services/adapters/openai_compatible_adapter.py` builds chat-completion requests without an explicit universal no-training field; none can be assumed to exist across compatible providers.
- `docs/VENDOR_DATA_FLOW.md` confirms the tutoring context, summaries, moderation, optional voice, and external browser artwork requests. `render.yaml` enables cloud model and cloud transcription for the public demo.
- `docs/RETENTION_POLICY.md` describes short Bede-side demo retention, but that does not establish provider-side retention, backup deletion, logging, or training exclusions.
- `docs/INFORMATION_SECURITY_POLICY.md` and the public privacy notice contain provider claims requiring verification against current vendor contracts and production settings.

## Release evidence ledger (one row per provider and endpoint)

| Required evidence | Status |
|---|---|
| Primary chat provider, account/project, model, region, endpoint and fallback inventory | UNVERIFIED |
| Provider's binding no-training/no-improvement terms for child inputs and outputs | UNVERIFIED |
| Account-level data-sharing/training settings disabled, independently witnessed | UNVERIFIED |
| API-level no-store/no-training options, where supported; wire-level negative tests | UNVERIFIED |
| Provider retention, abuse-monitoring exceptions, subprocessors and deletion terms | UNVERIFIED |
| Voice transcription/TTS, moderation, embeddings, summaries and telemetry separately qualified | UNVERIFIED |
| Live routing/failover cannot select an unqualified provider | PILOT: local-only model adapter enforced in #713; direct feature-specific egress and endpoint attestation remain NOT VERIFIED |
| Consent/parent verification, review/export/deletion journey tested end-to-end | UNVERIFIED |
| School authorization, limited educational purpose, vendor contract and student-data restrictions | UNVERIFIED |
| Production privacy notice matches observed network traffic and deployment | UNVERIFIED |
| Security incident procedure, access review and periodic assessment evidence | UNVERIFIED |

## School pilot fail-closed model routing (implemented in #713)

The institutional educator pilot enables the existing local-only model/audio
egress gate automatically whenever `EDUCATOR_PILOT_ENABLED=true` and the
instance is not a public demo (`DEMO_PIN` unset). This applies even if
`BEDE_COPPA_ENFORCE=false`. Forced model selection, live overrides and
fallbacks must not route to an unqualified cloud provider. A separate
explicit `BEDE_COPPA_ENFORCE=true` continues to enforce the same restriction
outside the pilot, including the public demo. Existing non-pilot, non-enforced
deployments are unchanged; they remain **unqualified for real child data**
until their provider/privacy evidence is independently verified.

This is a bounded technical mitigation, **not** a provider no-training
attestation, consent determination or legal certification. The configured
`local` endpoint is additionally guarded at adapter construction in the
subsequent endpoint-hardening PR: while COPPA enforcement is active, public
DNS names, public IP addresses, malformed URLs, embedded credentials, and
link-local metadata addresses are rejected. Localhost, Docker Desktop's
`host.docker.internal`, and private LAN IPs remain eligible for the selected
Mac-host path. This is an address-shape check only: it does not attest actual
DNS resolution, host ownership, HTTP redirects, TLS identity, or outbound
firewall enforcement. Those require independent operational verification.

The configured
`local` endpoint must itself be inspected for private ownership and network
egress; a provider called "local" is not proof of data residency. Direct
external child-data features and any non-adapter network routes still require
the shared outbound-boundary qualification below. Pilot GO and real learner
data authorization remain HOLD.

## Engineering acceptance (next narrow implementation)

1. Introduce a deny-by-default provider-qualification registry keyed by provider **and feature/endpoint**, with a separately controlled approval artifact and expiry; never infer approval from API credentials.
2. Gate all child-data egress at a shared outbound boundary. Reject unapproved primary and secondary/failover routes before request construction; no silent fallback. Protect runtime overrides and feature-specific direct calls.
3. Verify no-training settings only where the provider API actually supports them; otherwise require independently reviewed contractual/account evidence. Do not claim an SDK flag can compel a provider's behavior.
4. Add synthetic negative tests: primary denied, fallback denied, override denied, cloud speech denied, moderation denied, expired attestation denied, and local-only path allowed.
5. Capture redacted outbound request metadata and source SHA, never student content, to establish a reproducible evidence packet.
6. Validate the public demo and school deployments separately. Do not process real children until legal/privacy review and operational consent/deletion tests pass.

## Governance

The security officer signs the technical evidence packet. Qualified privacy/legal counsel reviews COPPA applicability, verifiable parental consent or valid school authorization, vendor agreements, retention and notice accuracy. No engineering CI pass alone constitutes legal certification. Preserve the synthetic-only Pilot HOLD and separate owner/school administrator GO.
