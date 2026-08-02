# Threat Model

Who Bede defends against, what it doesn't, and why the line is drawn where
it is. Companion to `docs/SECURITY.md` (compliance posture / AIUC-1
mapping), `docs/BLACKHAT_AIUC1_READINESS.md` (executive status and punch
list), and `docs/environment-pentests/` / `docs/adversarial-probes/` (the
two testing surfaces this document's adversary classes map onto). Like
those, this is a factual description of the design, **not a certification
and not a guarantee** — an adversary class listed as "defended against"
means the architecture is built to resist it, not that it has been proven
to under live, independent testing.

This document exists because a threat model that only lists what a system
defends against is marketing. Half of it is the non-goals section, and
that half is not filler — a false "we defend against X" claim is a worse
outcome than an honest "we don't, and here's why that's the right line for
what this product actually is."

## Assets

What's actually at risk, in descending order of consequence for a
self-hosted family instance:

1. **A child's session content and history** — what they said to Bede,
   their voice profile, their mastery/diagnostic data.
2. **Parent-level access** — the role that can view/delete all student
   data, change AI providers, and read the audit log.
3. **The persona's integrity** — whether Bede stays Bede (Socratic, bound
   by the constitution) rather than becoming an unrestricted assistant a
   child is talking to unsupervised.
4. **Encryption key material** — `DATA_KEY`, `MASTER_SECRET`, and anything
   downstream of them.
5. **License/business-logic integrity** — lower stakes than the above; a
   forged license costs the operator revenue, not a family their privacy.

For the public demo specifically, add: pseudonymous visitors' transient
data, and the operator's AI-provider budget (abuse/cost exhaustion).

## Adversary classes

| ID | Adversary | Capability | Maps to test surface |
|----|-----------|------------|----------------------|
| A1 | **Device already on the home LAN** | A sibling, houseguest, or anyone sharing the WiFi — no credentials, but network-adjacent | `docs/environment-pentests/` — "inside the network" posture |
| A2 | **Tester or attacker with no prior network access** | Starts from outside a known perimeter — internet scanning, a misconfigured port-forward, or the public demo (which is genuinely internet-facing) | `docs/environment-pentests/` — "outside a known access perimeter" posture |
| A3 | **Compromised or malicious dependency** | A supply-chain compromise reaching the codebase via `pip`/`npm`/a GitHub Action | Dependabot + audit gates (`docs/SECURITY.md`'s closed gaps); SHA-pinning for Actions remains an open gap |
| A4 | **Code execution inside the `api` container** | The worst case short of physical/host compromise — one process holds `DATA_KEY` unwrapped in memory, `SECRET_KEY`, `MASTER_SECRET`, DB credentials, every AI provider key | No network segmentation defeats this; see "What's already correctly segmented" below for the one boundary that survives it |
| A5 | **Database-only compromise** | SQL injection, a stolen DB credential, or a stolen backup — *without* also compromising the `api` container's environment | Genuinely bounded — see below |
| A6 | **Source code exposure** | The repo leaks, or is read by someone who was never meant to have it — *without* live credentials or environment access | Bounded by design; see below |
| A7 | **A manipulated or jailbroken model** | The AI provider itself responds to an adversarial prompt in a way that violates the persona, attempts tool misuse, or tries to extract the system prompt | `docs/adversarial-probes/`, `scripts/adversarial_probe.py`, the two-tier moderation/adversarial-detection pipeline |
| A8 | **Insider misuse** | A parent/admin-role holder acting against their own family's data, or a demo operator misusing visitor data | Partially addressed (audit log, `require_parent` scoping); not a primary design target — see non-goals |
| A9 | **Compromised AI provider infrastructure** | Anthropic/OpenAI/Mistral's own backend being breached | Entirely outside Bede's control; `docs/VENDOR_DATA_FLOW.md` covers what's sent, not what a vendor does with it afterward |

## What's already correctly segmented — worth crediting explicitly

Two boundaries hold even under adversary classes that sound worse than
they are:

**Database-only compromise (A5) does not yield plaintext.** The DB holds
ciphertext and a KEK-wrapped `DATA_KEY`; unwrapping it needs
`MASTER_SECRET`, which lives only in the `api` container's environment,
never in the database. SQL injection or a stolen DB credential, by itself,
buys nothing decryptable.

**Source code exposure (A6) does not yield secrets.** No credential of any
kind is committed to this repository — verified directly, not assumed —
and `core/config.py`'s `reject_weak_defaults_in_production` specifically
exists to stop a deployment from combining "the code is public" with "the
code's own dev-default secrets are still in use." This is Kerckhoffs's
principle applied deliberately: security does not rest on the code staying
hidden. A source leak reveals *how* decisions get made — exact regex
patterns, rate-limit thresholds, endpoint paths — which is real
information (an attacker who knows a lockout threshold can calibrate an
attack to stay just under it) but is a bounded exposure, not a
credential-level one.

**The single most dangerous operation is deliberately not reachable over
HTTP at all.** `scripts/rotate_master_secret.py` re-keys the entire
encryption hierarchy; it exists only as an offline CLI requiring direct
DB and host access, never as an admin API endpoint. The principle —
the more destructive an operation, the further it should sit from the
always-on network-facing process — should extend to anything comparably
dangerous added later, even though this codebase is otherwise a single
monolithic process with no formal control/data/management-plane
separation (A4 is not defended against by any existing boundary; see
`docs/BLACKHAT_AIUC1_READINESS.md`'s punch list for the concrete,
proportionate mitigations planned).

## Non-goals

Stated explicitly so nobody — a family, an auditor, a future contributor —
has to infer the boundary from what's absent.

- **Nation-state-level adversaries.** Bede is a self-hosted, LAN-scoped
  application for one family's own children — the correct threat model is
  COPPA-adjacent home-network security, not resistance to an adversary
  with essentially unlimited resources. A sufficiently resourced
  state actor that specifically targets a given household defeats this via
  physical seizure, legal compulsion, or compromising the OS/hardware
  underneath the containers — none of which live at the application
  layer, and no application-layer control changes that fact. Claiming
  otherwise would be a worse failure than not claiming it: false
  confidence in a threat class this system cannot resist is a bigger risk
  than an honestly-stated limitation.
- **Post-quantum cryptanalysis of Bede's own data-at-rest encryption.**
  This is a considered "no," not an oversight, and the reasoning is worth
  stating precisely rather than waved at: Bede's confidentiality mechanism
  is AES-256-GCM with a key derived via PBKDF2 — entirely symmetric, no
  asymmetric key exchange, because the data never travels off the host to
  be encrypted in the first place. Grover's algorithm reduces AES-256 to
  roughly 128-bit effective strength, which stays infeasible; there is no
  meaningful post-quantum gap here because the mechanism was never built
  on a primitive quantum computing threatens. (Contrast this with a
  network protocol whose ciphertext is captured and stored by an observer
  today for decryption once a quantum computer exists — a real concern for
  a system like that, and not a paper reasoning applied here out of
  caution.) The two places Bede does use classical asymmetric
  cryptography are both named and scoped rather than ignored: license
  signing (`core/licensing.py`, ECC/EdDSA — a future break lets someone
  forge a license certificate, a revenue concern, not a child-safety or
  confidentiality one) and Caddy's local CA for LAN TLS (a break here only
  matters to an adversary who already has a LAN foothold, which is a much
  smaller bar than nation-state). Neither justifies a PQ migration.
- **Physical seizure or compulsion.** No application-layer design defends
  against someone with lawful or unlawful physical access to the server
  itself compelling data disclosure.
- **A compromised host OS or hardware layer beneath the containers.**
  Container hardening (`cap_drop: ALL`, `read_only`, no-new-privileges)
  raises the bar for breaking out of a container; it does not defend
  against the host kernel or hardware already being compromised before
  Bede is ever deployed onto it.
- **A malicious parent.** The parent role is treated as the trusted
  administrator of their own family's instance, by design — the entire
  self-hosted model assumes the parent is the legitimate authority over
  their own children's data. Insider misuse by the account holder
  themselves is out of scope in the way it would be for any single-tenant
  admin role; the audit log exists for accountability, not prevention.
- **Anthropic/OpenAI/Mistral's own infrastructure security.** Bede
  controls what it sends to a configured provider (`docs/VENDOR_DATA_FLOW.md`)
  and nothing about how that provider secures its own backend.
- **Availability under a determined denial-of-service attempt.** A LAN
  device or an internet-facing attacker (against the public demo) can
  degrade service via the rate limiter's own resource consumption or
  brute-force lockout mechanisms — see the next section — before any
  confidentiality boundary is touched. Reducing this is worth doing where
  cheap; eliminating it entirely is not the design target for a homeschool
  tutor.

## A note on self-defeating mechanisms

Worth naming as its own item because it's a subtler failure mode than a
missing control: a security mechanism can be *present, correct, and still
make the system easier to attack* if it gives an adversary a way to harm a
legitimate user. Fixed-threshold account lockout is the clearest example
in this codebase — `core/parent_lockout.py`'s 10-failures-in-30-minutes
rule stops a password brute force, and *also* lets anyone who knows that
threshold (source exposure, A6, makes it public knowledge) lock the real
parent out of their own admin panel on purpose, repeatably, without ever
knowing the password. Any lockout mechanism added elsewhere (a planned fix
for `CHILD_PIN`, currently undefended by anything but a shared per-IP rate
bucket) needs to be designed with this tradeoff explicit, not copied
mechanically from the pattern that already has it — see
`docs/BLACKHAT_AIUC1_READINESS.md`'s punch list.

## Where this document is used

`docs/environment-pentests/` operationalizes A1 and A2 into an actual test
plan. `docs/adversarial-probes/` and `scripts/adversarial_probe.py`
operationalize A7. Neither is a substitute for the other, and neither is
independent third-party testing — see `docs/SECURITY.md`'s open gaps for
what that still requires on top of everything referenced here.
