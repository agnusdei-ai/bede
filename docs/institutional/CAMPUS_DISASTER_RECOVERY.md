# Bede single-campus disaster recovery: offline-first, encrypted

Status: implementation candidate; NOT disaster-recovery qualified until on-device rehearsal passes.

## Minimal implementation boundary
- No new cloud SDK, required external accounts, outbound data flow, telemetry or change to Bede's learner/API schema.
- Reuses local Docker Compose PostgreSQL and PyCryptodome already present in Bede's requirements.
- Run from the project root using the environment containing the Python dependency and Docker access.
- Backup contents are an AES-256-GCM encrypted SQL stream with authenticated header, fresh nonce/salt and a memory-hard scrypt-derived key. No host-side plaintext SQL intermediate file.
- Use an **independent long, randomly generated backup passphrase**, distinct from MASTER_SECRET, stored in an offline protected escrow under dual-control; retaining the database dump without Bede's MASTER_SECRET will NOT make application-encrypted student records recoverable.
- Preserve the original deployment secrets, student crypto key state, signing keys, license, versions and restore instructions in a separately protected disaster recovery escrow, **not** in the backup object itself.
- Restore only after authenticating the entire archive, then apply a single SQL transaction; explicitly acknowledges replacing the target database. Execute restore on an isolated recovery device first, never on the live campus for a rehearsal.
- Automatic scheduling, rotation, immutable offsite copies, restore rehearsal, and alerts must be configured and evidenced by the campus operator. This PR does NOT silently configure background jobs or upload data offsite.

## Commands (local PostgreSQL deployment only)
From repository root:
```
export BEDE_BACKUP_PASSPHRASE='<load securely from protected vault>'
python3 scripts/campus_backup.py backup backups/campus-2026-10-14.enc
python3 scripts/campus_backup.py verify backups/campus-2026-10-14.enc
# Only on isolated recovery system, with preserved separate master keys:
python3 scripts/campus_backup.py restore backups/campus-2026-10-14.enc --ack-replace-local-db
```
Avoid putting the passphrase in shell history or GitHub secrets/artifacts. Use a restricted credential file or operator-approved system secret store and clear the environment after use.

## Survival of disasters and ransomware
A same-host backup cannot survive building loss, flood or ransomware that compromises the host. Recommended ultimate posture is 3-2-1-1-0: three copies, two media, one geographically remote, one offline/immutable and zero untested restores. Local scheduled encrypted archives without remote immutable copies are **not sufficient** for campus survival.

Optional future transport boundary: copy already-encrypted artifacts with native AWS CLI to S3 Object Lock, gcloud CLI to retention-locked GCS buckets, or Azure CLI to immutable blobs. Select **one provider per campus only if the school chooses to enable it**, independently authenticate the upload-only workload, prohibit delete/bypass-retention, enforce TLS and lifecycle retention. Never add a mandatory dependency or credential to the application API; never place student data or backup private keys in GitHub Actions.

## CI/CD boundaries
GitHub CI runs synthetic crypto round trips, corruption/incorrect-key rejection, no-overwrite, and mandatory restore acknowledgement. CI may simulate immutable retention configuration but cannot truthfully assert a real cloud immutability policy or disaster survival. Never put real child data, DB backups, backup passphrases, or MASTER_SECRET in CI.

Before production: run scheduled daily backups, continuously verify integrity, alert on missed execution, enforce geographic and administrative separation, test full restored service from a fresh appliance, measure recovery point/recovery time objectives, verify school enrollment and teacher credentials after recovery, and provide signed owner acceptance.
