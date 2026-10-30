# Installation authorization flow

Status: design contract for review. Supersedes the family behavior of the
install-time acknowledgement in `PARENTAL_CONSENT.md` (an acknowledgement alone
no longer unlocks child-data processing) and extends `SCHOOL_DATA_AUTHORIZATION.md`.
Notice wording and the sufficiency of every verification method are for counsel.

## Flow

```
Install software
 -> adult selects family or school
 -> adult reads the applicable notice and identifies their authority
 -> the applicable verification / authorization step completes
 -> a local receipt is created (append-only)
 -> the permitted installation is registered (local record + license server)
 -> authorized child-data processing is enabled
```

Processing is enabled only by a receipt in state `verified`. Every other state
(`pending_verification`, `invalid`, `withdrawn`, `superseded`) leaves child-data
processing off. An incomplete or invalid receipt never unlocks anything.

## Receipt states

| State | Meaning | Processing |
| --- | --- | --- |
| `pending_verification` | Notice accepted and attested; verification not complete | off |
| `verified` | Required verification/authorization complete | on |
| `invalid` | Failed a check (bad hash, wrong location, bad signature, tampered chain) | off |
| `withdrawn` | Authorizer withdrew | off |
| `superseded` | Replaced by a later receipt (material notice change, reauthorization) | off (the successor governs) |

Transitions are recorded by appending, never by editing. The original receipt is
preserved: each record carries `prior_receipt_sha256`, forming a hash chain.

## Family

1. Installer shows `consent_notice.txt`; the adult accepts it and enters their
   name and attests they are the parent or legal guardian and the data custodian.
2. Receipt is created `pending_verification`. Attestation is recorded as an
   attestation, never labeled verified consent.
3. The reviewed parental-verification method (see
   `PARENTAL_VERIFICATION_PROPOSAL.md`) completes -> `verified`.
4. Until a method is approved and wired, `POST /installation/verification/*`
   answers 409 `verification_method_unavailable` and the receipt stays pending.
   This is an intentional, disclosed consequence: no approved method, no
   child-data processing.

## School

1. Installer validates the campus credential with the existing signed
   `campus_location` key and `BEDE_LOCATION_ID` (fails closed on mismatch).
2. The key proves the campus, not the person. The installer separately requires
   the authorizing representative's name, role (administrator or teacher), a
   documented-delegation reference (who delegated, when, document identifier),
   and explicit acceptance of `school_data_notice.txt`.
3. Receipt `verified` only when the key check, delegation record and notice
   acceptance are all present and valid. Otherwise `pending_verification` or
   `invalid`.
4. At startup the API imports a `verified` school receipt idempotently into
   `pilot_campus_data_authorizations` (keyed by receipt id; re-running creates
   no duplicate and requires no second approval). An invalid receipt imports
   nothing.
5. Each campus (location id) has its own receipt and its own authorization.
6. The runtime school panel remains for review of the receipt, withdrawal,
   authorizing a new campus, and reauthorization after a material notice change.
   Runtime enforcement stays on every covered path (existing 403
   `school_authorization_required`).

## Receipt (`bede.installation_receipt.v1`)

```json
{
  "schema": "bede.installation_receipt.v1",
  "receipt_id": "uuid",
  "mode": "family | school",
  "state": "pending_verification | verified | invalid | withdrawn | superseded",
  "notice": {"file": "consent_notice.txt", "version": "...", "sha256": "..."},
  "accepted_at": "UTC ISO-8601",
  "authorizer": {"name": "...", "capacity": "parent_guardian | administrator | teacher", "attestation": "..."},
  "delegation": {"reference": "...", "issued_by": "...", "dated": "YYYY-MM-DD"},
  "campus": {"location_id": "...", "license_key_sha256": "..."},
  "verification": {"method": null, "completed_at": null},
  "installer": {"name": "setup.sh|wizard|windows|unix", "version": "..."},
  "prior_receipt_sha256": null,
  "receipt_sha256": "..."
}
```

`delegation` and `campus` apply to `school` only. No identity documents are
collected or stored. The receipt file is `install/installation_receipt.json`,
mounted read-only into the api container; state changes append a new record.

## API

- `GET /installation/status` (parent/educator): current receipt state, chain
  validity, whether processing is enabled.
- `POST /installation/withdraw`: appends a `withdrawn` record.
- `POST /installation/verification/start` and `/complete`: stubs returning 409
  `verification_method_unavailable` until a method is approved.
- Consent enforcement (`core/consent.py`) treats the install acknowledgement as
  valid only when the current receipt is `verified`.

## Installation inventory

A local `installation_inventory` table records each permitted installation
(install id from `get_or_create_install_id`, receipt id, mode, location id for
schools, registered_at, license-server outcome). Registration with the license
server reuses the existing `/v1/activate` call (`{license_key, install_id}`,
wire format unchanged); its outcome (registered, cap reached, unreachable) is
recorded locally. With `LICENSE_SERVER_URL` unset the install works offline and
the local record stands alone; the activation cap is the permitted-installation
limit.

## Installer implementation (what writes the receipt)

`scripts/setup_wizard/install_receipt.py` is the one implementation. `setup.sh`
runs it as a CLI (`create`, `verify`); the browser wizard imports it. Every
launcher (`setup-gui.*`, the Windows and Unix installers, the macOS app) goes
through one of those two.

**File format.** `install/installation_receipt.json` is JSON Lines: one record
per line, each line exactly `canonical_bytes(record) + "\n"`, UTF-8, append-only.
The first line is the first record; a later record carries the previous line's
`receipt_sha256` in `prior_receipt_sha256` and supersedes it; the last line
governs. A re-installation appends a new record rather than editing the old.
Mode 0644, in `install/` at the repo root (git-ignored). `delegation` and
`campus` are JSON `null` for a family receipt. The file holds the authorizer's
name and capacity but never an identity document, a licence key (only
`license_key_sha256`) or a credential.

**Canonicalization (the API's validator must match this exactly).**

```
receipt_sha256 = sha256( canonical_bytes(record minus "receipt_sha256") ).hexdigest()
canonical_bytes(x) = json.dumps(x, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode("utf-8")
```

Keys sorted at every level, no whitespace, non-ASCII written as itself (not
`\uXXXX`), UTF-8; lowercase hex. `notice.sha256` is the SHA-256 of the exact
bytes of the notice file shown (`consent_notice.txt` or `school_data_notice.txt`),
`notice.version` its `Notice version:` line. `install_receipt.validate_record` /
`validate_chain` are the reference checks (schema, hash, notice hash, chain, and
"verified requires its evidence").

**What the installer decides.**

| Mode | Result |
| --- | --- |
| Declined / not accepted | No receipt, no `.env`, non-zero exit. |
| Family | Always `pending_verification` (name + parent/guardian attestation recorded as an attestation; `verification` is null). The attestation and a name are required and never assumed, including with `--accept-consent-notice`. |
| School, all of: signed campus key valid (Ed25519 via `core/licensing.py` `verify_license`, tier `campus_location`, unexpired, signed `location_id` equal to `BEDE_LOCATION_ID`), authorizer name, role administrator or teacher, delegation reference + issued-by + a past date, notice accepted | `verified`, `verification.method = signed_campus_key_and_documented_delegation`. |
| School, valid key but delegation or role missing/malformed | `pending_verification`. A campus key alone never yields `verified`. |
| School, key fails (signature, tier, expiry, location) or delegation dated in the future | `invalid`: reported, not written, install stops with no `.env`. |
| School, verifier cannot run (no pycryptodome) | Install stops (fail closed); an unsigned decode is never trusted. |

The notice is hashed from the bytes shown; the receipt tool re-hashes the file
again at write time and refuses a notice that changed in between. `.env` gets
`CONSENT_INSTALL_ACK_*` for family installs only. The wizard image installs
pycryptodome and copies `core/licensing.py`, both notices and the receipt module.
Optional `BEDE_INSTALLER_NAME` (`windows`/`unix`, set by those launchers) fills
`installer.name`; otherwise `setup.sh` or `wizard`.

Not done by the installers (API side): the read-only mount of `install/` into the
api container, the startup import into `pilot_campus_data_authorizations`, and
the license-server registration / inventory row.

## Out of scope

A general identity platform; collecting identity documents; changing the
license-server wire format; the demo.
