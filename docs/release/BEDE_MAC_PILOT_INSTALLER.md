# Bede Mac pilot installation and evidence

## Pilot scope

One approved Mac installation, one manually issued campus license, and the G1, G2, G3 acceptance record. Only synthetic learner data is allowed. Commercial payment integration, Cloudflare licensing deployment, and production key custody are separate work.

## 1. Issue a dedicated pilot entitlement

The original Ed25519 private signing key is unavailable. Bede's embedded public key cannot reconstruct it. This prepilot path generates an **ephemeral replacement keypair on the owner's Mac** and uses it once to create one approved campus license. The private key is never saved, copied to Git, sent to CI, or loaded into an agent. The saved license file has owner only permissions.

From the existing checkout, with the existing `.venv` and PyCryptodome installed:

```bash
cd ~/Documents/Bede-License-Tools
git fetch origin feat/pilot-single-mac-installer
git switch --track origin/feat/pilot-single-mac-installer
./.venv/bin/python scripts/pilot/issue_one_time_campus_license.py \
  --location-id bede-mac-pilot-2026 --licensee "Bede Mac G3 Pilot" --days 60
git add homeschool-api/core/licensing.py
git diff --cached --check
git diff --cached -- homeschool-api/core/licensing.py
git commit -m "pilot: embed public verification key for Mac qualification"
git push
```

Only the public half of the keypair is committed. The license is saved under the owner's `~/Library/Application Support/Bede Pilot/pilot-license.txt`, **not** in the repository. Keep that file private, and do not paste the license or private material into agent sessions. The replacement public key is baked into the exact next signed installer build. A source update alone does not alter an already downloaded bundle.

**Limitation:** As the private key is intentionally discarded, the pilot entitlement can be reobtained from the saved file, but a fresh differently scoped or renewed license cannot be signed with that identity. A new issuer and installer rebuild would be needed. This is suitable only for one authorized synthetic pilot and does not establish commercial signing custody.

The wizard must use `bede-mac-pilot-2026` as its Pilot campus ID, matching the signed entitlement.

## Campus and homeschool installation layout

The same Bede application supports either an approved **Campus** installation or a **Homeschool** installation. The Mac application selects context before starting setup and stores its working configuration, logs and local files separately:

```text
~/Library/Application Support/Bede/
  Campus/
    <approved-campus-id>/
      bede-operator/
  Homeschool/
    local/
      bede-operator/
```

These are local runtime directories, not separate application products or source code copies. The existing `homeschool-api/` and `homeschool-tutor/` source directory names remain internal implementation names during the pilot and do not determine which experience an installed campus receives. The native installer shows the Bede logo and a Campus or Homeschool choice before setup. For this pilot, select **Campus** and retain the licensed `bede-mac-pilot-2026` ID.

Each context uses a separate Compose project and local database volume. The installer refuses an unrecognized campus ID and the browser setup binds the context to the approved ID. Bede's API receives the same `BEDE_LOCATION_ID`, and campus setup enables educator pilot mode, which is governed by educator passkeys and roster authorization. Both contexts still use local loopback HTTPS, so attempting to run two different Bede installations simultaneously on the same port must fail safely rather than claim both are available.

The saved approval file `~/Library/Application Support/Bede Pilot/pilot-license.txt` is an owner controlled **issuance artifact**, separate from either installation directory. Do not copy it into the source tree or commit it.

## 2. Install the next exact candidate

Use the latest successful **Bede Standard and Offline operator bundles** GitHub Actions run associated with the public key commit from step 1. Download only the `bede-mac-pilot-arm64-<sha>` artifact. Verify the accompanying SHA256 checksum before opening the DMG.

Start Docker Desktop or the separately qualified container engine. Open `Bede Installer.app`. The app shows real checks for Mac prerequisites, runtime preparation, settings, services and trusted HTTPS health. The browser setup is part of the same installation and uses the same Bede portrait and language. Paste the saved approved `LICENSE_KEY` value into the license field. Use the location ID from step 1.

The bundle remains an **ad hoc signed engineering artifact**, not a public notarized distribution. Physical Mac preflight, publisher trust approval, OS permissions, passkeys, and model operation must be verified on the device. Never disable signature or TLS verification to get a passing result.

## 3. Qualification evidence

Store a private redacted evidence packet for the *exact artifact digest* and candidate Git SHA. Record tester, reviewer, UTC date, hardware, macOS version, container engine/version, passkey method, model and inference mode. No real learner names or assessment records.

| Gate | Required action | Evidence | Acceptance |
| --- | --- | --- | --- |
| G1 Campus isolation | Set up two synthetic campuses with the same learner name, distinct campus identifiers and teacher permissions. Attempt authorized and cross campus access, role changes and revocation. | Request / response outcomes, identity roles, and denied cross campus attempts with fake IDs only. | No cross campus access, data leakage or unauthorized roster changes. |
| G2 Human teaching workflow | Load independently administered synthetic DIBELS evidence, review source corrections, then record teacher approve, edit and reject decisions plus the authorized follow up. | Assessment provenance, teacher decisions, immutable audit event references, and next teaching action. | Bede supports but never silently replaces the educator's decision. |
| G3 Native Mac and recovery | Open the exact DMG, complete guided install and passkey enrollment, validate trusted local HTTPS, stop/restart, revoke/re enroll an approved teacher, and prove installation can recover without deleting existing settings. | Archive SHA256, device and OS details, boot and HTTPS check, administrator passkey, revoke and restart trace, support report. | Real installation and recovery pass without bypasses. |

Each gate needs a human reviewer and an explicit **PASS**. CI tests alone are not sufficient. A STOP or NOT RUN remains a blocking result.

## 4. Pilot GO decision

Review all three evidence packets for the **same candidate**. Owner signs the explicit pilot decision only when G1, G2, and G3 have passed. Approve a separate limited synthetic evaluation before any real learner data is introduced. No automated test or model may declare Pilot GO.

## Mac user experience

The native app is the only supported public Mac pilot entry point. Older `.command` launchers remain internal repository compatibility utilities but are excluded from the Mac app bundle. The browser setup must share its logo, palette, copy, progress language, and completion states. No license bypasses, secret extraction, or background student data collection are permitted.
