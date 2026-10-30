# Operator profile: hosted deployment, parent MFA, child devices, backups

Audience: whoever runs a Bede deployment for other families or a school
(a hosted or pilot instance). A self-hosted household on its own LAN can
ignore most of this; the defaults there are unchanged.

Companion documents: `docs/COPPA_READINESS_CHECKLIST.md` (the control
list and what evidences each control), `docs/COPPA_READINESS_TEMPLATES.md`
(blank templates for the incident playbook, external assessment, DPIA and
processing inventory), `docs/DATA_RETENTION.md` (what is stored and when it
is deleted).

Nothing in this document is a compliance determination. It states what the
code does and what an operator must still decide.

---

## 1. The `HOSTED_PROFILE` switch

`HOSTED_PROFILE` (env var, default `false`; `core/config.py`) turns on two
controls that a LAN household does not need:

| Control | With `HOSTED_PROFILE=false` (default) | With `HOSTED_PROFILE=true` |
|---|---|---|
| Parent password sign-in with no second factor enrolled | Opens a full parent session (unchanged) | Refused with `code: mfa_enrollment_required`; the response carries a 5-minute enrollment-only token (see §2) |
| Child PIN sign-in from a tablet | PIN alone (unchanged) | PIN **and** a tablet a parent has approved (see §3) |

Set it in `.env` for the `api` service. It is deliberately **not** in
`.env.example` or `docker-compose.yml`'s documented defaults, because it
describes how the deployment is operated, not a family's preference. Setting
it is an operator decision, and it has consequences for every family using
that instance: the current frontend does not yet handle the refusal shapes
below, so turning it on before the frontend work lands makes sign-in fail
with an unexplained error. Do not enable it on a live family instance until
the frontend change is deployed.

Turning it off again restores today's behaviour immediately. Tokens already
issued keep working until they expire.

## 2. Parent second factor (C-22)

On a hosted deployment, a parent who enrolls no security key and no
authenticator app cannot sign in with the password alone.

1. `POST /auth/login` (role `parent`) with the correct password returns
   HTTP 403:
   ```json
   {"detail": {"code": "mfa_enrollment_required",
               "message": "This deployment requires a second sign-in factor...",
               "enrollment_token": "..."}}
   ```
2. The `enrollment_token` is a `parent_pending` token with an `enroll` claim.
   It is accepted by the MFA enrollment routes only while **no** factor is
   enrolled: `POST /mfa/webauthn/register/options`,
   `POST /mfa/webauthn/register/verify`, `POST /mfa/totp/enroll`,
   `POST /mfa/totp/confirm`. Every other parent route refuses it.
3. Once a factor is enrolled, the token stops working for enrollment. The
   parent signs in normally: password, then the second factor
   (`mfa_required: true`, the existing path).
4. A wrong password still gets the plain `401 Invalid credentials`, so the
   refusal does not reveal whether a second factor exists.

Account recovery (`docs/` section on `routers/recovery.py`) still requires
two of its own factors. Recovery is unaffected by this switch.

## 3. Child devices (C-23)

On a hosted deployment the child PIN opens a session only from a tablet a
parent has approved. The PIN and its throttle are unchanged.

**Flow for a new tablet**

1. The child opens the child sign-in on the tablet and enters the PIN.
   The PIN is checked first. A wrong PIN gets the usual `401`, and creates
   nothing.
2. A correct PIN from an unknown tablet gets `403` ("waiting for parent
   approval"), and the tablet appears in the parent's pending list.
3. A parent signs in and calls `GET /auth/child-devices` (shows
   `device_id`, `state`, `user_agent`, timestamps; never a token or digest),
   then `POST /auth/child-devices/{device_id}/approve`. Check the user agent
   before approving: approving a tablet you do not recognise is the one
   decision this design relies on you to make.
4. The tablet signs in again with the PIN. This time the response includes
   `device_token`, once. The tablet must keep it (the frontend stores it in
   the device's own storage; see §6).
5. Every later child sign-in from that tablet must send `device_token` along
   with the PIN. Without it, or with a wrong one, the response is `403`.

**Revoking a tablet:** `POST /auth/child-devices/{device_id}/revoke`. The
tablet is refused even with its token. Revocation is per tablet and does
not change the child PIN, so other tablets keep working.

**What is stored:** one row per tablet in `child_device_pairings`: the
device id (a random value the browser generated), the user agent, the state,
and a SHA-256 digest of the token. The token itself is never stored, so a
copy of the table is not a working credential. The table holds no student
name and no child text.

**What this is not:** the device id is a value the browser generated, not a
cryptographic proof of the hardware. The token is what makes a pairing
meaningful, and it is held in the tablet's storage, so a stolen tablet with
its storage intact can still sign in until a parent revokes it. That is the
same limit the existing device revocation (`docs/DEVICE_IDENTITY_DESIGN.md`)
already states. Hardware-bound keys are a separate, deferred decision.

The existing device-fingerprint binding on every JWT (`core/security.py`:
IP and user agent) still applies to paired-device tokens. A token presented
from another browser fails the fingerprint check.

## 4. Backups and deletion (C-26)

### What a backup contains

`make db-backup` (see `docs/PRODUCTION_SETUP.md`) writes a full PostgreSQL
dump. Every family row in it is encrypted with the student's own data key
(`student_keys`), which is itself wrapped under the deployment's `DATA_KEY`.
Backups therefore contain ciphertext, and the plaintext of a deleted child
is recoverable from a backup only if that child's key row is also present
in the backup.

### The property this depends on, and its one trap

When a parent deletes a child (`DELETE /pod/configs/{student}`), the child's
key row is destroyed in the same transaction as the row deletes
(`services/student_deletion.py`). A backup taken **before** the deletion
still contains that key row, so restoring it **restores the child's ability
to be decrypted**. Crypto-shredding protects a backup only if the key is
gone from every restore point that matters.

**Operator procedure after any restore:** compare the students in the
restored database against the deletions made since the backup was taken.
For each student deleted after the backup, delete them again
(`DELETE /pod/configs/{student}` through the parent UI or the API) before
the restored instance serves anyone. Keep a record of deletions made
outside the app, or rely on the audit log's own `AuditEvent` entries for
student deletion, and check that record rather than memory.

> Open item: the codebase does not yet persist a deletion ledger that a
> restore can replay automatically. Until it does, the step above is manual
> and is the operator's responsibility.

### Proposed default retention for backups (OPERATOR DECISION)

| Setting | Proposed default | Who decides |
|---|---|---|
| How long a backup is kept | **30 days**, then destroyed | Operator, with counsel |
| How long a deleted child can be restored | Up to the backup window (30 days) | Operator |
| Backup encryption at rest at the storage location | Required; record the storage provider's setting | Operator |

The 30-day figure is a proposal, not a finding. It is chosen because it is
long enough to recover from a bad deploy and short enough that a deletion
is reflected in the backup set within a month. Replace it with the value
counsel approves and record the decision in `docs/DECISIONS.md`.

### Restore test (run at least once before go-live, then on a schedule)

1. Choose a backup taken at least one day after a test student was created.
2. Create a scratch environment (`make` target or a second Postgres) and
   restore the backup into it: `make db-restore FILE=...` on the scratch host.
3. Confirm the test student exists in the restored data.
4. In the live instance, delete that test student via the app.
5. Restore a backup taken **before** step 4 into the scratch environment.
   Confirm the student's key row is present (this is the trap above).
6. Repeat the deletion in the scratch environment and confirm the student's
   data is unreadable again (the key row is gone and the rows fail to decrypt).
7. Record the date, the backup file's timestamp, and the outcome in your
   operator log. An untested restore is not evidence.

## 5. Voiceprints (C-28), for operators

A child's voiceprint is one encrypted `voice_profiles` row. Deleting the
child (`Delete all data`) removes it and destroys the child's key. A parent
can also remove only the voiceprint with `DELETE /voice/profiles/{student}`.
Audio is not written to disk by any voice path, so there is no recording to
delete; the in-memory streaming buffers are discarded when a session ends.
A backup taken before deletion still holds the voiceprint row, and is
covered by the restore procedure in §4.

## 6. Open items this document does not close

- The frontend must handle `mfa_enrollment_required` (route to enrollment)
  and the `device_token` in the child sign-in response (store it; send it on
  later sign-ins). Until that ships, §1's switch must stay off on any live
  family instance.
- Parent-facing copy for the pending-tablet list and approval.
- Automatic deletion replay after a restore (§4).
- Backup retention and encryption-at-rest values: operator decisions.
