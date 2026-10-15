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


## Mandatory Bede recovery-enclave isolation

Bede must have its own administration and recovery trust domain, entirely independent of campus directory accounts. No Entra ID, campus Active Directory, campus SSO, campus domain administrator, campus-managed backup agent, or campus-wide ransomware response automation may control Bede's recovery environment. Bede educators can have scoped educational roles without privileged host or recovery rights.

- Separate dedicated backup identity and key custody from school IT administrator identities; require Bede owner-approved, hardware-backed phishing-resistant MFA for recovery operators.
- Firewall deny by default between campus networks and the Bede management/recovery plane. Allow only required learner/educator app access through narrowly defined ingress; backup traffic is outbound-only to an isolated target where available.
- Keep a clean recovery host and signed, reproducible golden build/configuration materials separate from the affected campus. The Apple Secure Enclave protects suitable hardware-bound keys; it is not a VM, complete OS isolation boundary, or substitutable disaster-recovery copy.
- No campus credential, agent, shared drive, mounted file system, CI deploy token, or campus backup account may delete protected backups or change retention.
- Preserve independently encrypted, immutable or physically offline recovery sets with geographically separate custody. A campus-local full-disk image alone cannot survive building loss or widespread compromise.
- During campus incident, freeze remote synchronization, quarantine the campus-facing appliance, use clean independently administered recovery hardware, verify image signatures, validate backup authentication, restore into an isolated environment and explicitly approve reconnection.
- Backup/restore encryption credentials and Bede MASTER_SECRET must be escrowed securely and separately; restoring encrypted application rows requires the correct original keys.
- Product qualification tests must prove that compromised campus administrator credentials cannot authenticate to or erase the recovery target, and that restoring into clean hardware works. Never promise absolute immunity: privilege vulnerabilities, supply-chain compromise, malicious insiders, physical disasters and stolen recovery keys remain risks.

The requested one-full-plus-30-day-incrementals schedule is a proposed retention profile, not yet an implemented platform snapshot capability. Keep at least one complete independently recoverable restore chain before archive or deletion, and test that archives can be restored within the agreed RTO. Offsite object storage and cold archive remain opt-in, not mandatory SDK dependencies.


## Hardware-agnostic and OS-neutral contract (mandatory)

Linux, Windows and macOS are examples of possible host environments, **not an exclusive supported-platform list**. The implementation must be independent of CPU manufacturer, machine model, host OS, hypervisor, and cloud provider to the extent the selected container runtime, PostgreSQL and cryptographic primitives permit. A platform must be explicitly qualified before being advertised as supported.

- Keep portable application data backups in a documented encrypted, authenticated and versioned format. Capture database-consistent state, container image digests, deployment manifests, schema version, operational configuration and a separately escrowed recovery-key inventory.
- Treat **whole-host images** as optional platform-specific acceleration, not the portable canonical recovery artifact. Disks, bootloaders, virtualization drivers, TPM/Secure Enclave capabilities and filesystems vary. Offer a documented provider/host adapter interface for filesystem snapshots and host images; never imply that a full-disk image from one OS boots on another.
- For container deployments, separately prove a reproducible clean-host restoration: deploy pinned images, provision independent secrets, restore application data, check schema and authorizations, then verify service health. No automatic failover into an untrusted campus host.
- Keep the Bede recovery administrator and backup credential domain independent of campus Entra ID, AD, school SSO and campus admin accounts irrespective of host OS. Hardware-based key protection is opportunistic, not a hard Apple-only dependency; require portable protected-key escrow for disaster recovery.
- Backup transport adapters may optionally support immutable remote storage selected by policy after a school explicitly enables it. No cloud SDK or external identity provider is a baseline runtime dependency.
- Support a configurable full baseline plus 30 days of incremental snapshots only where the selected storage/snapshot engine can guarantee chain integrity. The recovery plan must preserve each increment's dependencies and verify restoration before deletion or transition to cold tiers.
- Qualification matrix: container engine, OS/architecture, PostgreSQL backup/restore, app key escrow, user/tenant isolation, encrypted archives, offline/immutable retention, clean-host restore, CI/CD roll-forward and rollback. Mark untested combinations unsupported rather than guessing.
