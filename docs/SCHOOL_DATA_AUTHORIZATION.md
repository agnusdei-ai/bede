# School Data Authorization

Status: readiness control. All wording is a draft for counsel. Nothing in this
document or in the notice states that any law is satisfied.

## 1. Purpose

Where a school deploys Bede, a passkey-verified pilot administrator must
read a notice and record an authorization before
any student information is stored for that campus. Until the authorization is
recorded, the campus's write routes refuse with HTTP 403.

This is the school counterpart of the household parental consent ledger
(`core/consent.py`). It records what a school official agreed to; it does not
decide whether that agreement is sufficient.

## 2. Who may authorize

| Actor | May record | Constraint |
| --- | --- | --- |
| Administrator (verified passkey session) | `authorizer_role: administrator` | Any enabled campus. |
| Teacher (educator passkey session) | Read authorization status only | Must be an enabled campus member. Cannot grant or withdraw campus-wide data authorization. |

The authorization POST rejects teacher sessions with 403 regardless of their
campus membership, and rejects an administrator payload claiming the teacher
role. A GET from a nonmember teacher or an unknown campus returns the usual
404 without disclosing campus existence. Only the verified pilot administrator
can grant or withdraw an authorization. This passkey role does NOT by itself
establish institutional authority: separate evidence of authorization by the
participating school's authorized administrator or executive must be
verified before real learner-data qualification or Pilot GO.

## 3. The notice and its hash

The notice is `homeschool-api/data/school_data_notice.txt`. Its first line is
`Notice version: <version>`. The notice hash is the hexadecimal SHA-256 of the
file's exact bytes, computed at request time, so editing the file changes the
hash with no separate constant to keep in step.

A grant must present the current hash. A client that displayed an older notice
receives `409 {"error": "notice_changed"}` and must display the current text.

If the notice changes after a school has authorized, the record is **stale**.
A stale record does not authorize new writes. The verified pilot administrator
must read the new notice and authorize again, which adds a new row. The earlier row is kept
as history and is not edited.

## 4. Endpoints

All under `/pilot/campuses/{campus_id}/data-authorization`.

- `GET`: `{authorized, stale, notice_hash, notice_version, notice_text,
  authorized_at, authorized_by}`. Callable by the administrator or by an
  enabled member educator.
- `POST {notice_hash, authorizer_name (1-100), authorizer_role}`: `201` on a
  first grant, `200` and no new row when already authorized against the
  current hash.
- `POST .../revoke {reason}`: administrator only. Stops further storage.
  Deletes nothing.

## 5. The ledger

Table `pilot_campus_data_authorizations`: `id`, `campus_id`,
`authorizer_role`, `authorizer_ref` (educator id, or `administrator`),
`authorizer_name_enc` (encrypted, associated data bound to the campus and
row), `notice_hash`, `scope`, `granted_at`, `revoked_at`,
`revocation_reason_enc`.

The table is campus-level and has no `learner_id`. It is therefore not part of
the learner deletion cascade, and deleting a learner does not remove it. It is
kept deliberately: it is the school's record of what it agreed to, not learner
data. Disabling a campus (`/pilot/owner/campuses/{id}/disable`) also leaves it
in place, for the same reason. No route deletes it; removal is a
retention-policy decision for the operator and counsel.

Audit events `pilot.school_data_authorized` and
`pilot.school_data_authorization_revoked` carry the campus UUID, the role and a
twelve-character notice hash prefix. They never carry a name, a reason or any
notice text.

## 6. What is gated

Refused with `403 {"detail": {"error": "school_authorization_required",
"message": ..., "authorize_path": "/pilot/campuses/<id>/data-authorization"}}`
when the campus has no active authorization against the current notice:

- creating a learner (stores a display name);
- approving an educator-to-learner roster grant;
- every assessment write: create, scores, transitions, supersede, evidence,
  proposal, proposal decision, plan, progress monitoring, follow-ups;
- recording evidence, requesting a recommendation and deciding it
  (`/pilot/me/learners/...`);
- a tutoring turn, which stores a transcript.

Mechanism: the assessment routes pass `write=True` to `_scope`, which gates
early, and `_recheck`, which every assessment commit passes through, gates
again as a backstop so a future write that forgot the early gate is still
refused. The journey routes gate in `_write_context`, which every write calls.
`tests/test_school_data_authorization.py` enumerates every `/pilot`
POST/PUT/PATCH/DELETE route and fails if one is neither in the gated set (with
a behavioural case proving the exact 403) nor on the named exemption list with
a reason.

Not gated, by design: reads, revocation of grants and memberships, campus
disable, learner deletion, the calendar and benchmark-licence records (no
learner data), and the authorization endpoints themselves. After withdrawal a
school can still review and delete.

Household behavior, the demo role and educator passkey login are unchanged.

## 7. Questions for counsel

1. Authority. The API now requires a verified administrator passkey for
   all campus-wide grants; a teacher cannot grant even if they are a member.
   Does the named administrator also have independently verified authority
   from the school to permit storing learner data? The passkey is not that proof.
2. Parental notice. The draft places notice to parents and any parental
   consent on the school. Is that allocation correct for each deployment, and
   does the school need a template from the Provider (see
   `docs/COPPA_READINESS_TEMPLATES.md`)?
3. FTC position on school authorization. May a school authorize collection in
   place of a parent, and is the educational-purpose-only limit in the notice
   sufficient for that? Does that position hold where the Provider receives no
   data (self-hosted) versus a hosted deployment?
4. FERPA. Is the school treating Bede as a school official under a direct-
   control arrangement, and does the notice need to say so?
5. Re-authorization. Is requiring a fresh authorization on every notice change
   the right trigger, or should only material changes require it?
6. Retention of the ledger after a campus is disabled or deleted.
7. Whether the administrator's name must be stored in the clear for an
   auditor, rather than encrypted.
