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

## Tiers

| Tier | Meaning | Key strategy | AAD binding | Deletion |
|---|---|---|---|---|
| **T0** | Key material | Never in the DB in plaintext; env/hardware only | N/A | Rotation, not deletion (`scripts/rotate_master_secret.py`) |
| **T1** | Biometric / irreplaceable | Per-record key, wrapped by `DATA_KEY` | Required | Crypto-shred (destroy record key) |
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
| `voice_profiles.profile_enc` | Speaker embedding | **T1** | Shared key, no AAD | Per-record key + AAD |
| `parent_totp_config.secret_enc` | TOTP shared secret | **T2** | Shared key, no AAD | Shared key + AAD (must stay reversible — needed to compute codes) |
| `parent_webauthn_credentials.credential_enc` | WebAuthn credential | **T2** | Shared key, no AAD | Shared key + AAD |
| `parent_credential_override` | Password hash + salt | **T2** | PBKDF2 one-way ✅ | Unchanged — one-way is strictly stronger than this app's reversible default |
| `parent_recovery_*` | Recovery PIN / code | **T2** | PBKDF2 one-way ✅ | Unchanged |
| `session_transcripts.transcript_enc` | Full session transcript | **T3** | Shared key, no AAD | Per-student key + AAD |
| `student_configs.config_enc` | Daily plan, grade, context | **T3** | Shared key, no AAD | Per-student key + AAD |
| `narration_assessments.assessment_enc` | Rubric scores | **T3** | Shared key, no AAD | Per-student key + AAD |
| `learner_profiles.profile_enc` | Synthesized learner read | **T3** | Shared key, no AAD | Per-student key + AAD |
| `lesson_bookmarks.bookmark_enc` | Bede-authored resume note | **T3** | Shared key, no AAD | Per-student key + AAD |
| `mastery_profiles.profile_enc` | Skill-mastery vector | **T3** | Shared key, no AAD | Per-student key + AAD |
| `diagnostic_evidence_log.delta_enc` | Probe deltas | **T3** | Shared key, no AAD | Per-student key + AAD |
| `audit_log.event_enc` | Security event records | **T4** | Shared key, no AAD | Shared key + AAD. **Deliberately NOT per-student** — the audit log must survive a student's deletion, per `core/audit.py`'s own design note; crypto-shredding it per student would destroy the security record along with the data |
| `learner_behavior_checks.count_enc` | Adaptation counter | **T4** | Shared key, no AAD | Shared key + AAD |
| `api_usage_events` | Token counts | **T4** | Shared key, no AAD | Shared key + AAD |
| `demo_*` (codes, notes, signals) | Pseudonymous demo state | **T4** | Shared key, no AAD | Shared key + AAD. Short TTL already does most of the work here |

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
| T2 call sites migrated to v2 | ⬜ Next |
| T3 call sites migrated to v2 | ⬜ |
| T4 call sites migrated to v2 | ⬜ |
| Per-record keys (T1) | ⬜ Blocked on AAD migration completing |
| Per-student keys + crypto-shredding (T3) | ⬜ Blocked on the above; this is punch-list #6 |
