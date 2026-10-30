# Parental consent, pausing, and reviewing your child's records

This document covers the consent controls in Bede: the consent record, the
pause, the review and export, and what each one does and does not do. It is
written for two readers, the parent who runs Bede and the operator who deploys
it.

**Scope statement.** These controls are engineering readiness for a COPPA
(16 CFR Part 312) compliance review. They are not a compliance determination.
Whether a consent method is *verifiable parental consent* under the Rule, and
whether it is sufficient for a given deployment, is a question for counsel.
Nothing in this repository decides that. The code enforces whatever method the
parent records and refuses methods that are not wired.

## What happens by default

A child's information is not collected until a parent has given consent.
Collection means: a tutoring turn, a saved transcript, a narration profile,
and a voice enrollment. Until consent is recorded, those routes refuse with
HTTP 403 and the error `parental_consent_required`. The gate runs before the
collection route stores anything, so a refused request writes no transcript,
narration, profile, or voiceprint. Saving a student's name and grade is a
separate route and is not gated yet (see "What is still open").

The public demo is a separate, pseudonymous role with its own retention
(see `RETENTION_POLICY.md`). It is not parent-consented and is not gated here.

There is no mode switch and no grace period. The gate is closed for every
child who is not covered by one of the two ways below.

## The two ways a child is covered

1. **A parent records consent**: per child (`POST /consent/{student}`), for
   the whole household at once (`POST /household/consent`), or by ticking the
   consent box when saving the pod in Parent Setup (`POST /pod/configs` with
   `consent_notice_hash`). All of these use the method
   `parent_attested_checkbox`.
2. **The person who installed Bede acknowledged the family notice at install
   time.** The installers read the shared notice (`data/consent_notice.txt`),
   ask the person installing to confirm they are the operator and custodian of
   the children's records and are the parent or legal guardian (or are acting
   with their authority), and write `CONSENT_INSTALL_ACK_HASH` and
   `CONSENT_INSTALL_ACK_AT` to `.env`. The acknowledgement is valid only if the
   hash equals the **current** notice hash (an acknowledgement of an older
   notice is not valid) and the time is an ISO-8601 UTC time not more than five
   minutes in the future. When valid, a child who has **never had a consent
   record** is permitted, and the first collection writes one ledger row with
   method `install_custodian_attestation`, dated at the acknowledgement time,
   labelled "install-time custodian acknowledgement". A child whose consent was
   withdrawn is never covered by it: withdrawal cannot be undone by the install
   acknowledgement. That method is recorded by the product only and cannot be
   requested through the API.

Hosted or pilot deployments never set the acknowledgement, so a parent's tick
(or the Parent Setup banner) is what covers a child there.

## The notice

The notice text is the file `homeschool-api/data/consent_notice.txt`, the
single source shared by the installers and the API. Its first line is
`Notice version: <X>`. The notice hash is the hex SHA-256 of the file's exact
bytes, so the shell installer, the Python wizard and the API compute the same
value. Any edit to the file changes the hash.

A consent recorded against an older notice is **stale**. A stale consent never
blocks collection. It only makes the household status report
`needs_consent: true`, so Parent Setup can ask the parent to review the new
notice; accepting records a fresh consent and revokes the old row, so the
ledger keeps both.

**Counsel.** The notice wording, the custodian wording, any notice a hosted
deployment would need, and whether either method is sufficient are drafts for
counsel to settle. This repository does not decide them.

## Household status and acknowledgement

- `GET /household/consent` (parent only) returns
  `{needs_consent, install_ack, notice_hash, notice_version, notice_text, students: [{student_name, consented, stale}]}`.
  A child covered by a valid install acknowledgement and not revoked counts as
  consented. Reading it writes nothing.
- `POST /household/consent` with `{notice_hash, parent_label}` records consent
  for every configured child that lacks it and refreshes stale ones, returning
  `{granted, already, refreshed}`. A wrong hash returns 409 `notice_changed`.
  It is idempotent.
- `POST /pod/configs` accepts an optional `consent_notice_hash` (and
  `parent_label`). Correct: the children being saved get consent recorded. Wrong:
  409 `notice_changed` and nothing is saved. Absent: no change.

The refusal body is `{error: "parental_consent_required", message, parent_action: "open_parent_setup"}`.

## Giving consent

1. Fetch the current notice: `GET /consent/notice`. It returns the text, its
   hash (`hash`), and the available methods.
2. Show the parent the notice text.
3. Record consent: `POST /consent/{student}` with
   `{"method": "parent_attested_checkbox", "notice_hash": "<hash from step 1>", "parent_label": "Mum"}`.

Rules the endpoint enforces:

- `notice_hash` must be the hash of the notice that is current on the server.
  A stale hash returns **409 `notice_changed`**, so the parent is never recorded
  as agreeing to text they were not shown.
- `method` must be a method listed as available. `payment_transaction` is named
  but **not wired**. Asking for it returns **422 `method_not_available`**.
- While a consent is active, a second grant returns the existing record
  (`created: false`) and does not change its method or notice. To change them,
  revoke first.

`parent_label` is an alias you choose. It is stored encrypted under the child's
key, and it is never a legal name the product requires.

## Withdrawing consent

`POST /consent/{student}/revoke` with an optional `reason`. This stops further
collection immediately. It **does not delete** existing records. Deletion is a
separate act (`DELETE /pod/configs/{student}`), and it removes the consent
record and the pause state along with everything else for that child.

## Pausing collection

`POST /consent/{student}/pause` stops collection for that child while keeping
consent in place. Collection routes return **423 `collection_paused`**. Reads
still work, including review.

`POST /consent/{student}/resume` restores collection.

Both are audited with a row in the audit log (`collection.paused`,
`collection.resumed`). A refused collection attempt is recorded too
(`collection.refused`) with the reason only.

Refusal order: a child with no consent is refused as unconsented (403), even
if they are also paused. The more basic fact is reported first.

## Reviewing and exporting everything held about your child

`GET /pod/students/{student}/review` returns every record held for the child,
decrypted, grouped by table. Its table list is the same list the deletion
cascade uses, so the review cannot cover fewer tables than deletion removes.
Each table's name appears in the response even if it is empty.

Two things are deliberately not returned in readable form:

- **The voice profile embedding.** The row is listed, but its contents read
  `withheld: biometric template, not exported`. A voiceprint is a biometric
  template, and copying it out of the store is not a review of anything your
  child said.
- **Rows that cannot be decrypted** are reported as `{"unreadable": true}`.
  They are not dropped, so a missing row never looks like a clean record.

Each review is audited (`data.exported`) with counts only.

The review route is named `/review` rather than `/export` because the
deployment's exfiltration guard blocks any path containing `/export`. The
guard exists for good reason and was not weakened.

## What is still open

These are gaps in this change. They are listed here so nobody mistakes them
for done.

- **The parent screens live in `homeschool-tutor/`** and are built
  separately from this API. Until they are in the build you run, consent is
  recorded by the installer's acknowledgement or through the API.
- **Pod configuration save is not gated.** Saving a student's name and grade
  (`POST /pod/configs`) is allowed before consent; it is also where the parent
  can tick consent.
- **Voice streaming is not gated.** `POST /voice/stream/start` and its chunks
  send the child's speech to transcription before any tutoring turn. The
  stream route does not know which student a child's token is for, so it needs
  the client to send the student name. Only voice enrollment is gated today.
- **Direct assessment entry is not gated.** `POST /diagnostic/{student}/assessment-records`
  lets a parent record an externally administered result. It is outside this
  change's file list and needs the same one-line gate.
- **Pilot and campus learners have no consent record.** Institutional learners
  are not `StudentConfig` households. Their consent is a school-authorization
  question for counsel (see `COPPA_PROVIDER_NO_TRAINING_GATE.md`).
- **Existing students need consent after an upgrade.** A household that
  already uses Bede and did not go through the new installer has no install
  acknowledgement, so collection returns 403 until a parent consents in Parent
  Setup. That is the intended fail-closed behaviour, but operators must plan
  for it.
- **A pause does not stop a turn already in flight.** The check runs when a
  turn starts. A turn that began before the pause finishes.
- **Consent evidence is deleted with the child.** Deletion removes the consent
  record. Whether a consent record must outlive the child's data is a
  retention question for counsel.

## For operators: where the code lives

- `core/consent.py`: notice text and hash (from `data/consent_notice.txt`), install acknowledgement, the method registry, grant,
  revoke, pause, and the gate (`require_collection`).
- `routers/consent.py`: the endpoints above.
- `services/student_export.py`: the review. Each encrypted column is decrypted
  with the same associated data its writer used.
- `services/student_deletion.py`: `student_scoped_models()` is the one table
  list for both deletion and review.
- `core/database.py`: `ConsentRecord` and `StudentCollectionState`.

To add a consent method, add a `ConsentMethod` to `METHODS` in `core/consent.py`,
set `wired` to true only once the flow behind it exists and counsel has
approved it, and add a test. Editing `data/consent_notice.txt` (bump its version line) changes the hash,
so every new grant must be made against the new text and existing consents
become stale.
