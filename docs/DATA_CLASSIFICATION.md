# Data Classification

Every encrypted data entity in Bede, its sensitivity tier, and the controls
that follow from that tier. This is the artifact
`docs/ARCHITECTURE_PRINCIPLES.md` P2 requires ("data is classified by
sensitivity, and controls differ by class") and the one
`docs/ARCHITECTURE_ASSESSMENT.md` identified as the root cause behind two
separately-tracked findings — AAD binding (#5) and cryptographic deletion
(#6) — which are the same gap expressed twice.

**Why this exists.** Today a voice biometric embedding, a TOTP secret, an
encrypted session transcript, and an internal lesson-bookmark note are all
encrypted identically: one global `DATA_KEY`, no context binding, one blast
radius. Undifferentiated controls mean the *weakest justified* control is
applied to the *most sensitive* asset. Classification is what lets the
controls diverge.

**Companion to** `docs/DATA_RETENTION.md`, which states what is kept and for
how long. This document states how strongly each thing is protected and why.
Retention answers "when does it go away"; classification answers "what
guards it while it's here."

## What AAD is

Referenced throughout this document and `docs/ARCHITECTURE_PRINCIPLES.md`
(P5) as a requirement, so it's worth stating plainly rather than assuming
the reader knows the acronym.

Bede encrypts with **AES-256-GCM**, an *AEAD* cipher — Authenticated
Encryption with Associated Data. AEAD gives two properties in one operation:

- **Confidentiality** — nobody without the key can read the plaintext.
- **Authenticity** — nobody without the key can produce ciphertext that
  decrypts successfully. Tampering makes decryption *fail*, rather than
  silently returning altered data.

The "AD" is a second input the cipher accepts alongside the plaintext.
Associated data is **not encrypted** — it isn't secret and isn't stored in
the ciphertext — but it *is* mixed into the authentication tag. Decryption
requires being handed the same associated data; supply different data, or
none, and the tag check fails even though the ciphertext is genuine and the
key is correct.

Its purpose is to bind ciphertext to **context**: to make a given encrypted
value valid only in the place it was meant to live, rather than valid in the
abstract.

### What that buys here, concretely

Bede uses one global `DATA_KEY` for every encrypted column in every table.
Without associated data, a ciphertext proves exactly one thing: *this was
encrypted by whoever holds `DATA_KEY`*. It proves nothing about where it
belongs. So the bytes in one student's `bookmark_enc` are cryptographically
interchangeable with another's.

Anyone who can write to the database — a stolen DB credential, SQL injection
elsewhere in the stack, a malicious restore, an insider — can copy one row's
ciphertext into another row and it decrypts **perfectly**. No tag failure,
no error, no log line. A student's data silently becomes attributed to a
different student, and nothing in the system can detect it.

With AAD bound to `table/column/row_key`, that same swap fails
authentication. The attack goes from undetectable to impossible.

"Does this AEAD usage bind context, or is ciphertext portable between
records?" is close to a rote question in a professional cryptographic
review, which is the other reason this is worth closing before an external
assessment rather than after.

## Feasibility for Bede

Assessed rather than assumed, because the migration touches ~50 call sites
across 15 modules and a botched one makes a family's data permanently
unreadable — a worse outcome than the gap staying open longer.

### The load-bearing requirement: row-key stability

AAD must be reconstructible at read time from data the reader already has.
If the `row_key` component ever *changes* for an existing row, that row
becomes undecryptable — permanently, since the original AAD is gone.

Most rows here are scoped by `student_name`, which makes "can a student be
renamed?" the single largest feasibility question. **Verified: there is no
rename path.** `routers/pod.py`'s `save_pod_configs` matches existing rows
on `student_name` and updates in place; a config submitted under a different
name creates a *new* row and leaves the old one untouched. No code path
mutates `student_name` on an existing row in any table.

So the row key is stable by construction, not by convention — which is the
strongest form this requirement can take, and it means the primary
feasibility risk is structurally absent rather than merely unlikely.

**A caveat that must survive future work:** this property is now
load-bearing for decryptability, and nothing in the code says so. Adding a
rename feature later — updating `student_name` in place — would silently
break every AAD-bound row for that student. If a rename is ever wanted, it
has to be implemented as *decrypt-under-old-key, re-encrypt-under-new*, not
as an `UPDATE`. Recorded here because it is exactly the kind of constraint
that gets violated by someone who never read this document.

**Unrelated issue surfaced by the same analysis:** because an effective
rename creates a new row rather than moving one, the old student's rows are
orphaned — and `services/student_deletion.py` deletes by `student_name`, so
those orphans are never cleaned up by deleting either name. Pre-existing,
nothing to do with AAD, tracked here because this is where it was found.

### Migration cost and risk

The envelope supports both formats simultaneously (v1 unbound, v2 bound),
and `core/encryption.py` dispatches on the version byte in the blob it was
handed — not on whether the caller passed an AAD. That yields:

| Property | Consequence |
|---|---|
| v1 rows stay readable indefinitely | No flag-day, no downtime |
| Rows upgrade on next write | No migration script, no bulk rewrite, no long-running job |
| A migrated read path handles unmigrated rows | Call sites migrate independently, in any order |
| v2 rows **require** their exact AAD | The binding cannot be downgraded away by omitting an argument |

That last row is the asymmetry that matters. A v2 blob read without its
context raises rather than silently succeeding, so a partially-migrated
codebase can't quietly lose the protection it just gained.

Risk is therefore per-call-site rather than global: an error affects one
table's future writes, is caught by that call site's tests, and leaves
every already-written row readable.

### Performance

Measured, since performance is a differentiating constraint on this
hardware:

| Operation | Without AAD | With AAD | Delta |
|---|---|---|---|
| `aad_for()` construction | — | 0.12 µs | — |
| encrypt, 200 B | 60.97 µs | 66.29 µs | +8.7% |
| decrypt, 200 B | 73.95 µs | 76.59 µs | +3.6% |
| encrypt, 64 KB transcript | 138.28 µs | 144.23 µs | +4.3% |
| decrypt, 64 KB transcript | 145.75 µs | 150.50 µs | +3.3% |

Roughly 5 µs absolute per operation, on paths that run per stored record,
not per request.

Worth noting where that cost actually sits: `AES.new(MODE_GCM)` alone is
~41 µs, about 74% of a small encryption, because constructing a GCM context
does the key schedule and GHASH subkey precomputation. AAD is nowhere near
the dominant term. That construction cost is inherent to the library's API —
a GCM cipher object cannot be safely reused across messages, since each
needs its own nonce — so it isn't recoverable without changing libraries.

A 12-byte nonce would save ~5.5 µs (GCM derives its counter directly from a
96-bit IV, and must hash any other length). Deliberately **not** taken: the
current 16-byte random nonce gives a 2⁶⁴ collision bound against a 12-byte
nonce's 2⁴⁸, and trading a documented security margin for 10% of an already
minor cost is the wrong direction for data that is retained for years.

### Alternatives considered

Recorded after the fact, honestly: AAD was chosen because it is the
standard mechanism for this problem and costs nothing extra — it uses a
slot AES-GCM already provides. A documented comparison was not made first.
This is that comparison, so the choice is defensible to a reviewer rather
than merely conventional.

| Mechanism | Binds context? | Authenticated? | Extra storage | Extra key | Verdict |
|---|:--:|:--:|---|---|---|
| **AAD in AES-256-GCM** (chosen) | ✅ | ✅ | none | none | Free, standard, ~5 µs |
| Per-record derived keys — `KDF(DATA_KEY, table‖column‖row_key)` | ✅ implicitly | ✅ | none | derived | **Complementary, planned** — see below |
| Encrypt-then-MAC — separate HMAC-SHA256 over ciphertext ‖ context | ✅ | ✅ | +32 B/record | +1 | Redundant; GCM already authenticates |
| Context hash in a sibling column, checked in application code | ⚠️ | ❌ | +32 B/record | none | **Rejected** — not cryptographic; anyone who can write the blob can write the hash |
| Per-row asymmetric signature (Ed25519 over the row) | ✅ | ✅ | +64 B/record | +1 keypair | **Rejected** — huge cost, and the only option here with a real quantum weakness |
| AES-GCM-SIV (RFC 8452) | ✅ (same AAD slot) | ✅ | none | none | Viable; buys nonce-misuse resistance we don't currently need |
| XChaCha20-Poly1305 | ✅ (same AAD slot) | ✅ | none | none | Viable; better random-nonce margin, no advantage on context binding |
| Tweakable-cipher tweak (XTS-style, tweak = row identity) | ✅ | ❌ | none | none | **Rejected** — XTS provides no authentication at all, which is the property we most need |
| Merkle tree / hash chain over the table | ⚠️ detects, doesn't prevent | ✅ | root + proofs | none | Table-level tamper *evidence*, not per-record binding; needs a trusted root. This is what Locuto's attestation chain does, and it's the wrong weight here |
| Fully homomorphic encryption (FHE) | ❌ | ❌ | large ciphertext expansion | none | **Rejected — wrong problem.** See below |

**Per-record derived keys deserve a note**, because they're the one
alternative that isn't rejected — they're the *next step*. Deriving a
distinct key per record from the context achieves binding implicitly: wrong
context yields the wrong key, so decryption fails. That's equivalent
protection against the swap attack. It is on the roadmap for T1 and T3
regardless, because it's the prerequisite for crypto-shredding (punch-list
#6) — you can only destroy a key that exists per record.

AAD is still the right thing to do first: it protects every tier
immediately at zero storage cost, including the T4 tables that will never
justify per-record keys, and it's a change to one function rather than a
key-hierarchy redesign. The two compose — a per-record-keyed value should
*also* carry AAD, so a bug in key derivation can't silently degrade to an
unbound read.

### On homomorphic encryption

Worth recording separately because it comes up, and because the honest
answer has two halves that point in different directions.

**For context binding, FHE is not a candidate.** FHE lets a party *compute
on* ciphertext without decrypting it. AAD binds ciphertext to *where it
lives*. Those are different problems, and FHE does not solve ours: a
validly-encrypted blob is validly encrypted wherever it sits, so nothing
about homomorphic capability detects that a value was moved between rows.
The trade would be a 1,000×+ slowdown and substantial ciphertext expansion
in exchange for not gaining the property, against AAD's zero extra bytes
and ~5 µs.

**The place it would genuinely matter is the AI provider boundary** — the
one documented exception in `docs/ARCHITECTURE_PRINCIPLES.md` P18, where
full tutoring context reaches Anthropic/OpenAI/Mistral in plaintext because
a model cannot reason over ciphertext. That is the largest privacy
concession in the system, and private inference is exactly FHE's dream
application.

As of this writing it is not viable for that. CKKS-based frameworks have
demonstrated end-to-end private inference on LLMs up to roughly 8B
parameters, and GPU acceleration has improved encrypted GPT-2-class
inference substantially — real progress, not stagnation. But the overhead
remains on the order of 1,000× against plaintext, concentrated in the
polynomial approximation of nonlinear operations (softmax, GELU), and these
are research implementations rather than production systems. FHE is
currently practical for private lookups, small-model inference, and batch
analytics at tens of transactions per second; it struggles precisely where
strict sub-second interactive latency is required. A Socratic tutoring turn
with a child waiting for a reply is close to the worst-fitting workload
available, and the target hardware is a Raspberry Pi.

**The deployable alternative for that boundary today is confidential
computing, not FHE** — GPU TEEs (NVIDIA H100/H200 with encrypted VRAM,
attested jointly with Intel TDX or AMD SEV-SNP) run at roughly 90–99% of
native performance with a one-off attestation cost of a second or two. Note
the guarantee is different in kind: a TEE means the operator cannot see the
data and can prove the hardware is genuine, which is a hardware-trust
assumption. FHE's guarantee is mathematical. Neither is free of trust; they
place it differently.

**Bede's actual answer is better than either, and already exists.**
`LOCAL_LLM_BASE_URL` points at a self-hosted open-weight model with zero
egress — no third party, no homomorphic overhead, no TEE vendor dependency,
no attestation chain to verify (`docs/VENDOR_DATA_FLOW.md`: "nothing leaves
your machine at all"). That closes the P18 exception completely, at no
cryptographic cost.

Which reframes the question in a way worth stating plainly: **for this
product the provider-boundary problem is not cryptographic, it is a
capability question** — whether a locally-runnable model tutors well enough
on modest hardware. If yes, the boundary is already closed. If no, no
encryption scheme makes a frontier provider stop being a third party; it
only changes what that third party can observe. Revisit if FHE inference
reaches interactive latency at useful model scale, or if a family's
threat model requires a cloud provider *and* forbids it seeing content —
a combination this product does not currently have to serve.

### Quantum tolerance

The honest framing first: **AAD has no quantum posture of its own.** It adds
no key material and no new hardness assumption — it feeds extra bytes into
an authentication tag the cipher was already computing. Its resistance is
whatever AES-256-GCM's is. So the real question is how the *primitive* holds
up, and the answer differs sharply by threat model.

**In the realistic model (classical queries, quantum offline computation —
"Q1"):** AES-256-GCM is fine. Grover's algorithm halves effective key
strength, so AES-256 offers roughly 128-bit security against a quantum
adversary, which remains infeasible. Nothing here rests on factoring or
discrete log, so Shor's algorithm is irrelevant. This is the same reasoning
`docs/THREAT_MODEL.md` uses to scope post-quantum cryptanalysis of Bede's
at-rest encryption out as a non-goal, and it holds for the AAD binding
specifically.

**In the superposition-query model ("Q2"):** GCM and GMAC are *completely
broken*. Kaplan, Leurent, Leverrier and Naya-Plasencia showed in 2016 that
Simon's algorithm recovers the hidden period in Wegman-Carter-style
constructions with O(n) superposition queries, and their result covers
CBC-MAC, PMAC, GMAC, GCM and OCB alike. Tag forgery becomes cheap.

That sounds alarming and is not, for a specific and checkable reason: **Q2
requires the adversary to query Bede's encryption oracle with quantum
superposition inputs** — to run the cipher, with the real key, on
superposed plaintexts. For encryption at rest, an attacker who can do that
already has code execution inside the process that holds `DATA_KEY`
unwrapped in memory (`docs/THREAT_MODEL.md`'s adversary A4), at which point
they read the plaintext directly and never bother forging a tag. The attack
model presupposes a compromise strictly worse than the one it enables.

It also would not be fixed by switching: the same paper breaks the obvious
alternatives (CBC-MAC, PMAC, OCB) in the same model, and Poly1305 is a
Wegman-Carter MAC of the same family. Sponge-based AEADs — Ascon, the NIST
lightweight-cryptography selection — have a better-studied Q2 story and
would be the direction to look if this model ever became relevant. It
isn't, and adopting a less-deployed primitive to defend against an
adversary that already owns the process would be a poor trade.

**The one genuinely quantum-vulnerable alternative** in the table above is
per-row asymmetric signatures: Ed25519 falls to Shor outright, and a
post-quantum replacement (ML-DSA) costs ~4.6 KB per signature against AAD's
zero. That option was rejected on cost long before quantum entered the
picture; the quantum weakness merely confirms it.

**Verdict:** AAD's quantum tolerance is AES-256-GCM's, which is adequate in
every threat model that applies to a self-hosted family server. The
alternatives are either equivalent (other symmetric AEADs, all sharing the
same Q2 caveat), complementary (per-record keys, planned), or strictly
worse (signatures — expensive *and* the only real quantum liability).

*Sources: [Kaplan, Leurent, Leverrier, Naya-Plasencia, "Breaking Symmetric
Cryptosystems using Quantum Period Finding" (CRYPTO
2016)](https://who.rocq.inria.fr/Gaetan.Leurent/files/Simon_CR16.pdf);
[Bonnetain et al., "Quantum Attacks without Superposition Queries: the
Offline Simon's Algorithm"](https://arxiv.org/pdf/2002.12439); [Quantum
Linearization Attacks](https://eprint.iacr.org/2021/1239.pdf).*

### Where AAD deliberately does not apply

`encryption_config.data_key` — the KEK-wrapped `DATA_KEY` itself (T0) —
stays on the v1 envelope. There is exactly one such row, so there is no
second location to swap it with and nothing for context binding to defend
against. Changing it would also mean touching the boot path and
`scripts/rotate_master_secret.py` for no security gain.

### Row keys where `student_name` isn't the scope

Not every encrypted table is student-scoped. These need their key chosen
deliberately as they migrate:

| Table | Row key | Note |
|---|---|---|
| `audit_log` | Row `id` | Deliberately not student-scoped — the log must outlive any student's deletion |
| `demo_*` | Demo `code` | Short TTL already bounds exposure |
| `api_usage_events` | Row `id` | Student-scoped rows exist but household-wide rows have `student_name=None` |

## Tiers

| Tier | Meaning | Key strategy | AAD binding | Deletion |
|---|---|---|---|---|
| **T0** | Key material | Never in the DB in plaintext; env/hardware only | N/A | Rotation, not deletion (`scripts/rotate_master_secret.py`) |
| **T1** | Biometric / irreplaceable | Per-student key, wrapped by `DATA_KEY` | Required | Crypto-shred (destroy student key) |
| **T2** | Authentication secrets | Shared `DATA_KEY`, or one-way hash where never re-read | Required | Crypto-shred where per-student; hash destruction otherwise |
| **T3** | Child session content / PII | Per-student key, wrapped by `DATA_KEY` | Required | Crypto-shred per student |
| **T4** | Derived / internal operational | Shared `DATA_KEY` | Required | Ordinary row delete acceptable |

Two properties are deliberately **required at every tier T1–T4**: AAD
binding, and AES-256-GCM (never an unauthenticated mode). Tiering changes
the *key strategy* and the *deletion mechanism*, not whether the data is
authenticated. A control that should be universal is not a tiering decision.

### Why biometrics get their own tier above session content

A voice embedding is not replaceable. A child can be given a new PIN, a new
password, a new session; they cannot be given a new voice. Compromise is
permanent in a way no other asset here is, and that asymmetry justifies the
strictest key handling even though the *volume* of biometric data is tiny
compared to transcripts.

## Entity classification

| Table / column | Contents | Tier | Current state | Target |
|---|---|---|---|---|
| `encryption_config.data_key` | KEK-wrapped `DATA_KEY` | **T0** | Wrapped by KEK from `MASTER_SECRET` ✅ | Unchanged — already correct |
| `encryption_config.device_salt` | PBKDF2 salt | **T0** | Plaintext (correct — a salt is not secret) ✅ | Unchanged |
| `voice_profiles.profile_enc` | Speaker embedding | **T1** | Per-student key + AAD ✅ | Reached, with one deviation: **per-student**, not per-record — see note below |
| `parent_totp_config.secret_enc` | TOTP shared secret | **T2** | Shared key + AAD ✅ | Reached (stays reversible — needed to compute codes) |
| `parent_webauthn_credentials.credential_enc` | WebAuthn credential | **T2** | Shared key + AAD ✅ | Reached |
| `parent_credential_override` | Password hash + salt | **T2** | PBKDF2 one-way ✅ | Unchanged — one-way is strictly stronger than this app's reversible default |
| `parent_recovery_*` | Recovery PIN / code | **T2** | PBKDF2 one-way ✅ | Unchanged |
| `session_transcripts.transcript_enc` | Full session transcript | **T3** | Per-student key + AAD ✅ | Reached |
| `student_configs.config_enc` | Daily plan, grade, context | **T3** | Per-student key + AAD ✅ | Reached |
| `narration_assessments.assessment_enc` | Rubric scores | **T3** | Per-student key + AAD ✅ | Reached |
| `learner_profiles.profile_enc` | Synthesized learner read | **T3** | Per-student key + AAD ✅ | Reached |
| `lesson_bookmarks.bookmark_enc` | Bede-authored resume note | **T3** | Per-student key + AAD ✅ | Reached |
| `mastery_profiles.profile_enc` | Skill-mastery vector | **T3** | Per-student key + AAD ✅ | Reached |
| `diagnostic_evidence_log.delta_enc` | Probe deltas | **T3** | Per-student key + AAD ✅ | Reached |
| `audit_log.event_enc` | Security event records | **T4** | Shared key + AAD ✅ | Reached. **Deliberately NOT per-student** — the audit log must survive a student's deletion, per `core/audit.py`'s own design note; crypto-shredding it per student would destroy the security record along with the data |
| `learner_behavior_checks.count_enc` | Adaptation counter | **T4** | Per-student key + AAD ✅ | Exceeds the T4 target deliberately: the row is `student_name`-scoped and dies with the student, so keying it per student costs nothing and makes it shreddable too |
| `api_usage_events` | Token counts | **T4** | No encrypted column (counts only) | Unchanged — nothing to bind |
| `demo_*` (codes, notes, signals) | Pseudonymous demo state | **T4** | Shared key + AAD ✅ | Reached. Bound to the demo code/session token, not a student — these have no student identity to key on |

### Deviation: per-student keys, not per-record

T1 originally specified a *per-record* key. What shipped is one key per
student, shared across all of that student's rows in every table. The
reasoning, recorded here because the deviation is deliberate:

* **Nothing asks for per-record shredding.** The erasure unit in the product
  and in COPPA is the child, not an individual transcript. A per-record
  scheme would buy a granularity no feature uses.
* **A per-student shred cannot partially succeed.** It is a single row
  delete. A per-table or per-record scheme can destroy six keys of eight and
  leave two tables readable — a worse failure than either extreme, and one
  that would present as successful deletion.
* **Cost.** Per-record keys mean a wrap/unwrap and a key row per transcript,
  on a Raspberry Pi. Per-student, the unwrap is once per student per cache
  TTL (`core/student_keys.py`, 300 s).

The property T1 actually needs — that a compromised biometric row cannot be
recovered after erasure, and that voice data is not openable under the same
key as everything else in the deployment — holds either way.

## AAD composition

For every T1–T4 entity, the associated data binds the ciphertext to its
location:

```
aad = b"bede/v2/" + table_name + b"/" + column_name + b"/" + row_key
```

`row_key` is the row's primary key or its `student_name` scope, whichever
identifies the row uniquely. The envelope's magic and version bytes are
included in the authenticated data as well, closing the separate
malleable-header issue noted in the original review.

**What this stops:** moving a ciphertext blob between rows, columns, or
tables. Without AAD, a blob proves only "encrypted by whoever holds
`DATA_KEY`" — so someone with database write access can copy student A's
`bookmark_enc` into student B's row and it decrypts cleanly, with no tag
failure and no signal. With AAD, that same swap fails authentication.

## Migration posture

Changing the envelope format across ~50 call sites in 15 modules is not a
flag-day change, and attempting it as one would be the riskiest possible
way to ship a security improvement — a botched migration makes a family's
data permanently unreadable, which is a worse outcome than the gap being
closed.

The envelope therefore supports **both formats simultaneously**:

- **v1** (`_VERSION = 1`) — no AAD. Still readable, forever. Written before
  this change.
- **v2** (`_VERSION = 2`) — AAD-bound. Written by any call site that has
  been migrated.

Decryption dispatches on the version byte in the blob it was handed, so a
migrated read path transparently handles rows written before the change.
Call sites migrate tier by tier, highest sensitivity first, each with its
own tests. A row is upgraded from v1 to v2 the next time it is written —
no bulk rewrite, no migration script, no downtime.

**Ordering:** T1 (biometric) → T2 (auth secrets) → T3 (session content) →
T4 (operational). Per-record and per-student keys land after AAD binding is
complete, since crypto-shredding depends on the key hierarchy that AAD
binding's call-site audit establishes.

## Status

| Step | State |
|---|---|
| Classification artifact (this document) | ✅ Done |
| v2 envelope with AAD support + v1 fallback | ✅ Done — `core/encryption.py` |
| T1 call sites migrated to v2 | ✅ Done — `services/voice_auth.py` |
| T2 call sites migrated to v2 | ✅ Done — `services/mfa_service.py` |
| T3 call sites migrated to v2 | ✅ Done — `routers/pod.py`, `routers/transcripts.py`, `routers/narration.py`, `services/ai_service.py`, all four `services/diagnostic/` modules |
| T4 call sites migrated to v2 | ✅ Done — `core/audit.py`, `core/demo_code_session.py`, `services/interaction_signals.py`, `scripts/export_interaction_signals.py` |
| Regression guard against unmigrated call sites | ✅ Done — `tests/test_aad_coverage.py` (AST check over every production module) |
| Per-record keys (T1) | ⬜ Blocked on AAD migration completing |
| Per-student keys + crypto-shredding (T3) | ⬜ Blocked on the above; this is punch-list #6 |
