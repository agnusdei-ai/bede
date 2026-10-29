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

There is no setting that turns the gate off. A bypass would need its own
configuration value passed through `docker-compose.yml`, which is an operator
decision and was not added in this change.

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

- **There is no parent UI yet.** The consent screen, the pause and review
  controls, and the notice display all need frontend work in
  `homeschool-tutor/`. Until that lands, a parent using the app will hit the
  403 on tutoring and cannot consent through the product. This is the most
  important open item.
- **Pod configuration save is not gated.** Saving a student's name and grade
  (`POST /pod/configs`) still happens before consent. Gating it means the
  parent UI must consent first, so it waits for the frontend work.
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
- **Existing students need consent after an upgrade.** Every household that
  already uses Bede will see 403 on collection until a parent consents. That is
  the intended fail-closed behaviour, but it is a change operators must plan
  for.
- **A pause does not stop a turn already in flight.** The check runs when a
  turn starts. A turn that began before the pause finishes.
- **Consent evidence is deleted with the child.** Deletion removes the consent
  record. Whether a consent record must outlive the child's data is a
  retention question for counsel.

## For operators: where the code lives

- `core/consent.py`: notice text and hash, the method registry, grant,
  revoke, pause, and the gate (`require_collection`).
- `routers/consent.py`: the endpoints above.
- `services/student_export.py`: the review. Each encrypted column is decrypted
  with the same associated data its writer used.
- `services/student_deletion.py`: `student_scoped_models()` is the one table
  list for both deletion and review.
- `core/database.py`: `ConsentRecord` and `StudentCollectionState`.

To add a consent method, add a `ConsentMethod` to `METHODS` in `core/consent.py`,
set `wired` to true only once the flow behind it exists and counsel has
approved it, and add a test. Changing the notice text bumps `NOTICE_VERSION`,
which changes the hash, so every new grant must be made against the new text.
