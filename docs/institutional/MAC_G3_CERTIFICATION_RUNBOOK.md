# Bede | G3 physical-Mac certification runbook

**Document owner:** Agnus Dei Technologies, LLC — Bede engineering / release owner  
**Scope:** Invite-only institutional pilot, synthetic identities and learner records only  
**Application baseline:** `agnusdei-ai/bede` main merge `d3eb645c2de1058bb8056005a09c7d40446cea20` (#616, incorporating #618)  
**Automated qualification provenance:** candidate `6574a0e1b69ed3b162c39c626be316c4e457db4e`; synthetic matrix 146 PASS / 0 FAIL / 0 ABSENT / 0 BLOCKED / 0 UNVERIFIED  
**Disposition:** Test procedure only. No physical-Mac acceptance, certificate, real-data permission or Pilot GO is implied.

This is the controlling G3 test procedure for the above code baseline. Use [MAC_G3_CERTIFICATION_RECORD.md](MAC_G3_CERTIFICATION_RECORD.md) to record every observation, missing capability, failure and sign-off. A change to any application, installer, recovery, authorization or test-criterion code requires impact-based requalification of the new exact code SHA. Documentation-only updates do not require rerunning already qualified code tests.

## 1. Certification is a chain of distinct evidence

| Evidence | Real implementation | Proves | Does not prove |
| --- | --- | --- | --- |
| 146/146 synthetic matrix | `scripts/qualification/`, CI qualification workflow | G1/G2/deletion and scoped synthetic HTTP security behavior at qualified SHA | Physical Mac, actual Touch ID or packaged installer |
| **Mac real-device browser check** | `scripts/qualification/mac_check.py` | Six browser/teacher passkey and roster outcomes on physical Mac; virtual authenticator for administrator | Packaged delivery, lost-device recovery, school offboarding, physical capacity |
| **Operator package smoke** | `packaging/bundle/Install-Bede.command`, `Verify-Bede.command` | Architecture matched, Compose validates, app starts, CA-validated HTTPS health | Teacher, G1/G2, disaster recovery or Pilot GO |
| **G3 owner-executed scenarios** | This procedure and the release build | Actual Mac setup, authorization, recovery, offboarding, restart and independent recovery boundary | Automatic certification; outcomes must be observed and signed |
| **Mac mini workload assessment** (when hardware SKU/capacity is in scope) | `homeschool-api/core/mac_bundle_qualification.py` | Evaluates submitted physical-device measurements for named Mac mini SKU | Collecting measurements itself, educational effectiveness or unlimited inference |

**Do not call the Mac browser check or `Verify-Bede.command` "G3 PASS."** The owner must complete and record the full applicable G3 sequence.

## 2. Test configuration and restrictions

Record exact physical **server Mac** model, chip, CPU architecture, unified memory, internal storage, macOS build, FileVault state, Docker Desktop/Compose versions and local AI model/runtime version. If using a **second educator Mac**, separately record its model, macOS version, Safari/Chrome version, passkey type and network trust. The educator Mac needs only a compatible HTTPS browser and authenticator: it does **not** require Docker, a model or a repository checkout.

The packaging workflow `.github/workflows/build-bede-operator.yml` creates `bede-operator-<40-char SHA>-amd64.tar.gz` or `...-arm64.tar.gz`, with a `.sha256` sidecar. Verify that the artifact was built for the **exact source SHA selected for certification**; the archived `RELEASE`, `ARCH`, image tags and Docker engine architecture must agree. The previously qualified 146/146 candidate commit is evidence for its code, but does **not** certify a different package or a rebuilt image without traceable provenance.

Preconditions:

- Only **disposable, explicitly synthetic** school identities, educator mailboxes, campus UUIDs, learners, assessments, transcripts and backup data. No Valor/student production records, school production credentials, real external inference keys or billing activation.
- A separately controlled test administrator with a **real** Bede user-verified WebAuthn session, and at least one synthetic educator test mailbox and authenticator. For the loopback `mac_check.py`, only the **teacher** authenticator is physical; the administrator authenticator is virtual.
- Docker Desktop and Docker Compose started on the host Mac; a package for its native Docker architecture, trusted HTTPS hostname, configured Postgres, and a suitable locally controlled inference service for the actual tutoring test. A loopback inference stub proves qualification plumbing, **not** model quality or physical inference capacity.
- For two Macs, stable **private** IPv4 and organization-controlled **private DNS** for the server. Enable LAN mode expressly in the wizard, restrict host/network firewall ingress, and trust the **specific** exported Bede CA on the client only after fingerprint comparison. Never expose Bede with router port-forwarding, use a bare LAN IP as WebAuthn origin, or accept unexplained browser certificate warnings.
- Do not rerun setup against an established encrypted database to change network settings. Setup can regenerate master keys and render existing encrypted records inaccessible. Test on a fresh disposable instance.
- Record actual administrator identity approval/out-of-band affiliation verification; a campus directory/SSO account must **not** become Bede recovery or backup administrator by virtue of directory membership.

Keep the package folder, `.env`, CA private material, backup passphrase and one-time invitation links private. Evidence exports must be reviewed and redacted. Do not use `docker compose down -v` or replace a database containing real records.

## 3. Phase A — source-free installed build (G3-01)

**On the server Mac**, retrieve the matching operator workflow artifact and `.sha256` sidecar from the approved GitHub Actions run. Verify the checksum with a native local command (substitute the actual artifact filename):

```bash
shasum -a 256 bede-operator-<SHA>-<ARCH>.tar.gz
# Compare this output to the approved .sha256 sidecar, byte-for-byte.
tar -xzf bede-operator-<SHA>-<ARCH>.tar.gz
cd bede-operator
cat RELEASE
cat ARCH
docker info --format '{{.Architecture}}'
./Install-Bede.command
./Verify-Bede.command
```

Select a **fresh disposable local PostgreSQL** instance and the approved provider; for two-Mac LAN mode follow [TWO_MAC_TEACHER_PILOT.md](../../packaging/bundle/TWO_MAC_TEACHER_PILOT.md). The bundled launcher imports sealed application images, rejects the wrong architecture, starts the wizard on `http://localhost:8765` when needed and checks `https://localhost/api/health` against `bede-root-ca.crt`. `Verify-Bede.command` creates `bede-evidence/<UTC timestamp>/` including `summary.txt`, `container-status.txt`, `health.json` and `manual-acceptance.txt`.

**PASS:** package identity, SHA, native architecture, verified HTTPS, healthy Compose and private intended listener are evidenced. **BLOCKED/FAIL:** missing package/CA, mismatched image architecture, invalid certificate, untrusted public listener, installer failing or health check failing. Health alone cannot approve G3.

## 4. Phase B — actual passkey and isolation on Mac (G3-02 / G3-03)

The separate source-checkout test has a **real teacher WebAuthn ceremony** with Safari or Chrome, six mechanically scored observations and a **virtual administrator**. It needs the repository/tooling on the Mac, a sacrificial local Postgres instance and preinstalled harness dependencies; it is **not** shipped in the source-free operator archive.

```bash
# From a checkout of the exact selected code SHA, with harness dependencies installed:
export QUAL_DB_ADMIN_URL='postgresql://<LOCAL_TEST_ADMIN>@127.0.0.1:5432/postgres'
python scripts/qualification/mac_check.py --browser safari
# Repeat in Chrome only if Chrome is an in-scope supported client.
```

This command **recreates** a scratch database named `bede_mac_check` and drops it on exit. Use an **isolated sacrificial Postgres server only**; never point it at a shared or production server. The tool uses a synthetic mail sink and loopback local model stub, and produces `mac-check-out/mac-check-result.json` and `mac-check-calls.json`. It proves: real teacher passkey enrollment/login; invitation replay refusal; zero learners before grant; precisely one after grant; identical denial for another campus's same-name learner and an unknown UUID; and no accessible roster after revocation/relogin. Inspect that every item actually passed; skipped operator observations are not a substitute for full G3 sign-off.

On the **installed package**, separately test real browser-origin passkeys and educator identity/roster routes (no stub or virtual administrator unless a separately documented synthetic fixture is deliberately used). The implemented API contract includes:

| Operation | Exact route |
| --- | --- |
| Admin invitation | `POST /auth/educator-passkey/invite` |
| Teacher enrollment | `POST /auth/educator-passkey/register/options`, `/register/verify` |
| Teacher sign-in | `POST /auth/educator-passkey/login/options`, `/login/verify` |
| Authorized roster | `GET /pilot/me/learners`, `GET /pilot/me/learners/{learner_id}` |
| Roster grant / revoke | `POST` / `DELETE /pilot/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}` |

The operator must establish two synthetic campuses with the **same learner display name but distinct UUIDs**, and evidence both successful in-campus access and uniform cross-campus/unassigned/refused access. No name-based institutional learner identifier is accepted.

**PASS:** verified UV passkey on the actual client, no downgraded educator login path, matching trusted HTTPS origin, and the expected grant/denial outcomes. Browser cancellation must be retryable; one reused invitation must fail.

## 5. Phase C — authorized classroom and local tutor (G3-04 / G3-05)

Run one synthetic teacher journey on the **packaged** Mac build using the actual teacher-facing UI/API:

1. Authorized learner evidence is entered or retrieved at `/pilot/me/learners/{learner_id}/evidence`.
2. A recommendation is requested at `/recommendations`; inadequate source evidence must abstain, never fabricate diagnostic measures.
3. The educator **approves, edits or rejects** through `POST /recommendations/{recommendation_id}/decision`. Check `GET /decisions` for durable, hash-chained decision evidence and `GET /instruction` for **approved/edited only** instruction.
4. Query `GET /pilot/me/learners/{learner_id}/diagnostic` and `GET /pilot/me/learners/{learner_id}/tutoring/history` against **real stored synthetic records**; no fabricated historical records or scores.
5. Test supervised `POST /pilot/me/learners/{learner_id}/tutoring/chat` SSE **only** after educator approval, with the configured **local-only** model adapter; verify bounded generation and no remote model fallback. Revoke the teacher's grant *during an active stream* and prove stream termination, refusal of later writes/reconnect and no leaked neighboring-campus output.

The campus tutoring route is restricted to nonproduction synthetic qualification; **no learner-facing automatic delivery/session-launch authorization** is added by these G2 records. Persist a redacted record of expected/actual status, persistence after restart and denied negative operations. Local model behavior/safeguarding and observed resource limits are separate from the loopback-stub synthetic matrix.

## 6. Phase D — lost device, offboarding, recovery isolation (G3-06 / G3-07 / G3-08)

**Lost educator authenticator (synthetic account only):** an independently authenticated, passkey-elevated Bede administrator verifies continuing educator affiliation out of band, then calls `POST /auth/educator-passkey/recovery/{educator_id}` with the educator's **previously verified institutional email**. Complete the short-lived one-use recovery enrollment on a *different* physical authenticator; then prove the old key is disabled, old session is refused, and only the freshly enrolled key can sign in. Check that email alone or a campus login cannot perform administrator recovery. This code does not substitute for manual identity vetting.

**Offboarding:** revoke the specific roster grant with the `DELETE` route above and/or call `POST /pilot/campuses/{campus_id}/educators/{educator_id}/disable`. For **whole-account** offboarding also use the separately elevated `POST /educators/accounts/{educator_id}/disable`: campus membership disable alone must not be described as account-wide termination. Test old token, refreshed browser, new login, direct UUID API, active voice SSE and active tutor SSE; all former authorized operations must be refused or terminate without post-revocation protected output. Other educators and campuses must remain accessible.

**Independent recovery trust domain:** use separate Bede-controlled recovery credentials and a recovery environment isolated from school AD, Entra ID, SSO, directory admin and school backup agents. Attempt an explicitly authorized, **non-destructive negative test** using a synthetic campus directory administrator: it must not access recovery console, decrypt/alter backup keys, change retention or administer recovery enrollment. Then prove the distinct Bede recovery operator **can** perform the authorized recovery operation. A design document or a failed login alone does **not** prove network, identity and backup-enclave separation; collect environmental policy/authorization evidence. If an independent recovery plane is not deployed, mark **BLOCKED**, not PASS.

## 7. Phase E — stop, restart and isolated recovery (G3-09 / G3-10)

- With disposable state, stop and restart the installed application, without removing named volumes or regenerating keys. Confirm health, previously authorized teacher decisions/history, valid authorized access, and **continued denial** of previously revoked tokens/credentials. Retest one previously open SSE connection on stop/restart; it must fail closed.
- Recheck configured private DNS/TLS and the CA trust from the educator Mac after restart. Verify a deliberate administrator shutdown and documented recovery/rollback path, with timestamps and outcome.
- For backup/restore evidence, use `scripts/campus_backup.py` only in its documented deployment mode and **only an isolated disposable recovery environment**. A restore requires separately protected `MASTER_SECRET` and other original keys to read encrypted records; never restore onto the operational pilot DB. The source-free operator bundle does not include the source-tree backup script. Refer to [CAMPUS_DISASTER_RECOVERY.md](CAMPUS_DISASTER_RECOVERY.md).
- If qualifying a **Mac mini hardware capacity SKU**, collect real local model workload measurements and submit them to `python -m core.mac_bundle_qualification --sku classroom|campus --evidence <measured.json>` from a qualified code checkout. This evaluator validates supplied physical-device metrics; it does not execute the workload or attest to its authenticity. Reference [MAC_MINI_BUNDLES.md](../MAC_MINI_BUNDLES.md). Do not imply measured classroom concurrency from a stub or a successful install.

## 8. Evidence, verdict and sign-off

Fill [MAC_G3_CERTIFICATION_RECORD.md](MAC_G3_CERTIFICATION_RECORD.md) with actual UTC times, operator identity, source SHA, installed `RELEASE`/image architecture, test hardware and OS, browser, model/runtime, scenario results, immutable evidence hashes/locations, incident IDs, negative-test results and separate reviewer/owner signatures. Mask UUIDs in public-facing copies where necessary; never include bearer tokens, passkeys, invitations, raw child content, credentials, `.env`, private CA keys or plaintext backups.

A G3 certification decision is **PASS only if every applicable mandatory row passed on physical hardware with traceable evidence**, no recovery boundary is unverified, and no critical security defect is open. Any FAIL, BLOCKED, NOT RUN or inconclusive mandatory row means **NOT CERTIFIED**. Do not convert scope omissions into PASS.

Record two separate decisions: **(1) G3 engineering/device acceptance** and **(2) Bede owner's explicit invite-only Pilot GO**. G3 success is neither authorization for real student data nor public launch; those require their own expressly approved scope, privacy, security and contractual conditions.
