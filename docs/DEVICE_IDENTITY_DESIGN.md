# Device identity (P9) — design for review

**Status: Option C built and closed (2026-08-04). Option A still not
built** — this document's own recommendation ("C first, then A for the
parent role only") was followed, and this is the built, honest half of
it. See "What's built" below for exactly what shipped and where, and "Why
Option A stopped here" (renamed from the original "Why this stopped
here") for why the harder decision remains reserved rather than
unilaterally made.

P8 (step-up elevation) and P10 (identity domain separation) were completed
on 2026-08-03. P9 is the third of that group and the only one that changes
how every device authenticates — which is exactly why Option A specifically
still wants a decision before code, even though Option C did not.

## What's built (Option C, closed 2026-08-04)

`core/device_registry.py` implements exactly Option C as designed below —
a revocation mechanism, not a cryptographic identity. The four "open
decisions for review" this document originally posed all resolved cleanly
FOR OPTION C specifically, in ways that carry no lockout risk (the property
that made Option A's equivalent decisions genuinely reserved):

1. **Where does onboarding live?** Nowhere separate — a device is
   registered automatically on its first successful login
   (`routers/auth.py`'s `login()`, `routers/mfa.py`'s `_issue_parent_token`
   for the MFA-completion path), since Option C needs no WebCrypto ceremony
   the way Option A would. This sidesteps the `scripts/trust_service/`
   question entirely.
2. **What is the recovery path when a device forgets its key?** There is no
   key to forget. `device_id` is a plain UUID
   (`homeschool-tutor/src/utils/deviceId.ts`) persisted in `localStorage`;
   if it's lost, the next login simply registers a fresh device — genuinely
   self-healing, which is what makes Option C's lockout risk zero where
   Option A's is real.
3. **Does the child role get device identity at all?** Yes — both
   `parent` and `child` roles register and can be revoked
   (`DeviceRecord.last_role`); `demo_code` is excluded (anonymous, already
   has its own one-time-code identity). One physical tablet used by both a
   parent and a child is one row, not one per role — see `DeviceRecord`'s
   own docstring.
4. **Immediate or next-request revocation?** Next-request, matching
   `credentials_version`'s own precedent exactly — a revoked device's
   already-issued token is rejected on its very next authenticated request
   (`core/deps.py`), not just at its next login attempt, bounded by the
   same `_REFRESH_INTERVAL_SECONDS` multi-replica staleness window
   `core/parent_credential.py` already established.

Parent-facing surface: `GET/POST /admin/devices*`
(`routers/admin.py`, list is `require_parent`, revoke is
`require_elevated_parent` — P8), and `DeviceSettings.tsx`
(`homeschool-tutor/src/components/`) — the visible device list + Revoke
button this document called "the feature families actually ask for."

## The gap, precisely

`docs/ARCHITECTURE_PRINCIPLES.md` P9:

> Paired devices hold their own keypair, issued at onboarding; sessions bind
> to that key, and a single device can be deprovisioned without affecting
> others.

Today "trust" is two things, neither of which is a device identity:

1. **Caddy's local CA.** A network TLS decision. It says the tablet trusts
   *the server*, not the reverse, and every device that completes the
   `/trust` flow is indistinguishable from every other.
2. **A JWT fingerprint of `SHA-256(IP | User-Agent)`** (`core/security.py`).
   This is a *binding*, not an identity — it detects that a token moved, but
   it is not a secret, it is not per-device, and it cannot be revoked. Two
   tablets of the same model on the same LAN produce the same fingerprint.

The operational consequence, and the reason this matters more than it
sounds: **a lost or stolen tablet cannot be revoked.** The only lever is
changing the parent password (which bumps `credentials_version` and kills
every session for the whole family) or changing `CHILD_PIN` (same, for every
child). There is no way to say "that one device, no longer."

## What the pieces already in place give us

Two things landed for other reasons and make this cheaper than it would have
been a week ago:

- **Parent tokens now carry a `jti`** (P8, `core/elevation.py`). There is
  already a per-session identifier to hang a device record off.
- **`core/identity.py` owns domain-scoped signing**, so a device-bound token
  is a change to one module rather than to every issue site.

## Three options

### A. Per-device keypair, generated in the browser

The literal reading of P9. At onboarding the device generates a
non-extractable ECDSA P-256 keypair via WebCrypto, stores it in IndexedDB,
and registers the public key. Login becomes a challenge/response: the server
issues a nonce, the device signs it, the token binds to that device id.

- **Strongest.** The private key cannot leave the device (non-extractable),
  so a stolen token is useless without the device that holds the key.
- **Most work.** Frontend keypair lifecycle, a registration flow, a
  challenge/response endpoint pair, backend registry, revocation UI.
- **Real failure mode:** IndexedDB is not durable. Safari evicts it after
  ~7 days of no visits; "clear site data" wipes it; private browsing never
  persists it. A family whose tablet forgot its key needs a re-onboarding
  path that is itself as easy as the thing it replaces, or they are locked
  out of their own hardware. **This is the part that needs a decision, not
  the cryptography.**

### B. Reuse the existing WebAuthn credentials as the device identity

`services/mfa_service.py` already registers WebAuthn security keys, and a
platform authenticator (Touch ID, Windows Hello, Android biometric) *is* a
hardware-backed per-device keypair. Registering one per device gives device
identity with no new cryptography.

- **Least new code.** The registry, the attestation, and the revocation list
  already exist — `DELETE /mfa/webauthn/{id}` is already per-device
  deprovisioning, and it is already elevation-guarded as of P8.
- **Survives storage eviction**, unlike IndexedDB — the credential lives in
  the platform keystore.
- **Limitation:** it currently authenticates the *parent*, once, at login.
  Making it a per-request session binding means either re-prompting (bad UX
  for a child mid-lesson) or binding the token to the credential id at login
  and trusting the binding thereafter — which is option C's property, not a
  stronger one.
- **Does not cover the child role at all**, and the lost tablet is most
  likely the child's.

### C. Registered device records without per-request cryptographic proof

A device registry (`device_id`, label, first seen, last seen, revoked) with
the id embedded as a token claim at login, checked against a revocation list
on each request.

- **Closes the operational gap** — "revoke that tablet" becomes real, and a
  parent gets a visible list of active devices, which is the feature families
  actually ask for.
- **Weaker than P9 asks:** the device id is client-asserted, so it proves
  nothing cryptographically. An attacker who steals a token gets its device
  id too. It is a revocation mechanism, not an identity.
- **Cheapest by a wide margin**, no frontend crypto, no lockout risk.

## Recommendation

**C first, then A for the parent role only.**

C delivers the property that is actually missing today — individual
revocation and a visible device list — with no risk of locking a family out
of their own hardware. It is honest about being a revocation mechanism
rather than an identity, and P9 should stay marked ⚠️ rather than ✅ until A
lands, because calling C "device identity" would be exactly the kind of
overstatement `docs/SECURITY.md` exists to avoid.

A afterwards, scoped to the parent role: the parent's device is the one
whose compromise matters most (it holds the management plane, now behind
P8's step-up), it is the least likely to be re-imaged or shared, and a
re-onboarding prompt for a parent is acceptable where the same prompt
mid-lesson for a child is not.

B is worth revisiting once A exists, as the durable-storage answer to
IndexedDB eviction rather than as the primary mechanism.

### Performance note

C adds a revocation check to every authenticated request. On a Raspberry Pi
that is not free, and `docs/DEPLOYMENT_TOPOLOGY.md`'s multi-replica case
rules out a naive in-process cache with an unbounded TTL. The shape that
works: cache the *revoked* set (small, and only grows on an explicit
revocation) with a short refresh interval, accepting a bounded staleness
window on the order of seconds and stating it — the same pattern
`core/parent_credential.py`'s `periodic_refresh` already uses for
`credentials_version`, and for the same reason.

## Open decisions for review

**Resolved for Option C** (see "What's built" above) — each numbered
question below is kept in its original form for the historical record of
what was actually weighed, but the answer that shipped is the short version
already given above. **Still open for Option A**, which is why Option A
remains a reserved decision rather than something this pass built.

1. **Where does onboarding live?** `scripts/trust_service/` is a standalone
   stdlib HTTP server on plain :80 with no database access, deliberately —
   it exists to solve the untrusted-certificate chicken-and-egg. It is
   therefore the natural place a new device is *first* seen and the worst
   place to put anything needing the API or the database. Extending it means
   giving it a database dependency it was designed not to have; putting
   onboarding in the SPA instead means the device is already past the trust
   step, which is probably fine but changes what "onboarding" means.
2. **What is the recovery path** when a device forgets its key? Whatever it
   is, it must be at least as easy as the flow it protects, or families will
   route around it.
3. **Does the child role get device identity at all,** or does it stay on
   the PIN plus throttling (`core/child_throttle.py`)? A shared family tablet
   used by three children is a normal deployment, and per-device identity
   says nothing about which child is holding it — that is what voice
   verification is for (punch-list #8).
4. **Should revocation kill the token immediately or at next request?**
   Immediate means a server-side session check on every request; next-request
   is what C describes. This is the same trade `credentials_version` already
   makes.

## What P9 will and will not buy

Worth being explicit, since the principle's own rationale is easy to
over-read. Device identity means a stolen *token* is useless without the
device, and one device can be deprovisioned without disturbing the family.
It does not authenticate *who is holding the device* — that is voice
verification's job, and it is still advisory-only (punch-list #8). A device
identity plus a real biometric is a materially different claim than either
alone, which is why P9's own text points at #8.

## Why Option A stopped here

The instruction covering this work was to make practical decisions
autonomously and reserve the mission-critical ones. A change to how every
device authenticates, whose failure mode is a family locked out of their own
tablet, and whose central open question is a UX recovery path rather than a
cryptographic one, is on the reserved side of that line. P8 and P10 were
not: both are server-side, both fail closed into "log in again", and
neither can strand a device. Option C, built and closed above, was not on
the reserved side either, for the identical reason: its own recovery path
is "log in again and a fresh device registers itself" — self-healing, no
family ever locked out of hardware they own. Option A is the one that still
needs a founder decision before code, exactly because it cannot make that
same claim.
