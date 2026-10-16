# G1 inventory: authorization, voice, tutoring and search

This is the inventory for the G1 authorization, voice, tutoring and search
lane. It covers every educator-reachable protected path on base
`1b48e23495c8d673ab0755d83b0caae0de20311e` (the head of #596,
`feat/valor-pilot-campus-identity-g1`). The lane branch is
`g1/authz-voice-tutor-r2`.

The inventory came first and nothing was edited before it. Each path is
classified with one of four labels:

- `BUILT_AND_QUALIFIED`
- `BUILT_BUT_UNQUALIFIED`
- `DISABLED_AND_TESTED`
- `NOT_BUILT_OR_DEFERRED`

A path the UI never calls is still in scope if a token can reach it.

The "Before" column records the state on the base. The "After this lane"
column records what this branch changes. It was written as the target before
any code changed. Each later commit on the branch carries the tests that make
its row true. Rows this lane does not remediate
name their reason and the owner decision they need.

## Defects confirmed on the base

All five known defects were re-confirmed by reading the code at the base SHA.

| # | Defect | Where (base) |
| --- | --- | --- |
| D1 | `_stream_owner` returns `auth["code"] or auth["role"]`, so every educator shares the owner string `"educator"`. Any educator holding another educator's voice session id can push audio into it or read its transcript. | `homeschool-api/routers/voice.py:222` |
| D2 | `/voice/stream/{id}/events` compares the owner once, at attach, and never re-checks the grant. A revoked educator's open stream keeps delivering transcript items. | `routers/voice.py:250-261`, `services/streaming_transcription.py:274` |
| D3 | The educator branch of `/tutor/chat` checks the roster grant only when the turn starts. A turn that is already streaming keeps emitting output and writing narration, evidence and bookmarks after revocation. | `routers/tutor.py:188-201`, then `stream_tutor_response(db=db)` |
| D4 | `_require_legacy_name_route_safe` is instance-wide. It has three callers: `require_assignment` (:147), `roster_configs` (:157) and `assign_class_roster` (:186). | `services/educator_access.py:130` |
| D5 | The legacy `assign_class_roster` replacement removes a teacher's learner without bumping `credential_version`. The pilot revoke and disable routes do bump it. | `services/educator_access.py:179-229`; contrast `routers/pilot_campuses.py:191-192, 209-210` |

D4 is narrower than it first looks. The guard denies every name-keyed educator
path once any pilot campus row exists. That is the safe direction, because
name-keyed rows (`StudentConfig`, `EducatorAssessmentEvidence`,
`LessonBookmark`, and the rest) are global by display name. They cannot say
which campus owns them.

The guard ignores a campus's `enabled` flag, and that is also correct. If it
honoured the flag, disabling every campus would reopen name routes over data
that same-named learners on two campuses could share.

So the remediation for D4 does not change the guard's scope. It routes the
guard through the shared authorization module, which makes it the only place
the "legacy mode" question is answered. It also adds real HTTP tests that every
caller fails closed.

## Paths an educator token can reach

An educator token passes `require_educator` and `require_auth`
(`core/policy.py`: `educator.roster`, `session.self`, `tutor.chat`). It fails
`require_real_user` and `require_parent` (`family.data.*` and `admin.*` exclude
the educator role).

### Pilot campus routes (UUID-keyed)

| Path | Before | After this lane |
| --- | --- | --- |
| `GET /pilot/me/learners` | Built. Query-level join on campus, membership and grant, all `enabled`. Function-level tests only. | `BUILT_AND_QUALIFIED`. Real HTTP tests on SQLite and Postgres. |
| `GET /pilot/me/learners/{learner_id}` | Built. Uniform 404. Function-level tests only. | `BUILT_AND_QUALIFIED`. HTTP uniformity matrix covers random, malformed, valid-but-unauthorized and stale ids. |
| Learner search / autocomplete | Did not exist. | `BUILT_AND_QUALIFIED`: `POST /pilot/me/learners/search`. It returns only UUID-backed learners this teacher holds a live grant for. The query travels in the body so a learner's name never lands in an access log. |
| Admin routes: create campus, learner, membership, grant, revoke, disable | Built. Elevated parent passkey only. | Unchanged, except that revoke and re-approve now advance the grant's version (see "Grant identity"). |

### Legacy name-keyed educator routes (`/educators/me/...`)

These routes are `routers/educators.py`'s roster, config, assessments,
activity, diagnostic, dibels-progress and locuto-capacity.

- **Before:** Built. Guarded by `require_assignment` / `roster_configs` →
  `_require_legacy_name_route_safe`.
- **After this lane:** `DISABLED_AND_TESTED` in campus mode. Every route
  answers 404 over real HTTP once a campus exists. The guard now delegates to
  `services/pilot_authz.legacy_name_routes_allowed`.
- **Single-household mode** (no campus exists) is unchanged and remains
  `BUILT_BUT_UNQUALIFIED` for the G1 matrix. It is not a multi-campus
  surface.

### Assessments

| Path | Before | After this lane |
| --- | --- | --- |
| UUID-keyed assessment record | Did not exist. | `NOT_BUILT_OR_DEFERRED`. **Reason:** the canonical assessment domain (`AssessmentAdministration` / `Response` / `Score`) is a separate lane. **Owner decision needed:** whether G2's `PilotEvidence` counts as the pilot assessment record or a UUID-keyed assessment domain is built. |

### Tutoring

| Path | Before | After this lane |
| --- | --- | --- |
| `POST /tutor/chat`, educator role, legacy mode | Built. Grant checked at turn start only (D3). | `BUILT_AND_QUALIFIED` for revocation. The grant is re-checked at every point in the turn (see "Tutoring"). |
| `POST /tutor/chat`, educator role, campus mode | Denied: `require_assignment` 404s. | `DISABLED_AND_TESTED`. **Reason:** no learner-UUID-keyed `SessionConfig` and no UUID-keyed narration, bookmark or evidence tables exist yet. **Owner decision needed:** see "Decisions needed". Delivery of approved instruction into learner sessions stays disabled. |
| `GET /tutor/demo-config`, `POST /tutor/extract-narration`, `POST /tutor/speak` | Reachable by an educator. They read no learner record. | `BUILT_BUT_UNQUALIFIED`. No protected data, so no change. |
| `POST /tutor/summary`, `POST /tutor/email-summary` | Parent and demo only. | Not reachable by an educator. |

### Voice

| Path | Before | After this lane |
| --- | --- | --- |
| `POST /voice/stream/start` | Owner is `"educator"` for every educator (D1). | `BUILT_AND_QUALIFIED`. Bound to the full context (see "Voice"). |
| `POST /voice/stream/{id}/chunk`, `POST /voice/stream/{id}/finish` | Owner compared, but the owner is shared (D1). | `BUILT_AND_QUALIFIED`. The full owner is compared, and the grant is revalidated on every call. |
| `GET /voice/stream/{id}/events` | Owner compared once at attach (D2). | `BUILT_AND_QUALIFIED`. Revalidated between items and while idle. Ends and discards the session on revocation. |
| `POST /voice/transcribe` | Stateless; nothing stored. | `BUILT_BUT_UNQUALIFIED`. Reads no learner record and stores nothing. |
| `/voice/enroll`, `/voice/verify`, `/voice/override`, `/voice/profiles` | Parent or real-user only. | Not reachable by an educator. |

### SSE mechanics

| Path | Before | After this lane |
| --- | --- | --- |
| SSE replay | Not built. Voice events are consumed once from an in-memory queue, and there is no `Last-Event-ID`. | `NOT_BUILT_OR_DEFERRED`. Nothing to replay is the safe state. |
| SSE reconnect | A second attach returns immediately (`active_reader`). After discard, it reads as "unknown or expired session". | `BUILT_AND_QUALIFIED`. Reconnect after revocation is denied, and a mismatched owner reads the same as an unknown session. |
| SSE heartbeat | sse-starlette `ping` comments carry no data. | `BUILT_BUT_UNQUALIFIED`. No protected content. |

### Caches

The affected caches are the `ai_service.py` prompt caches (`_mastery_vector_cache`
:3723, `_processing_style_cache` :3724, `_lesson_bookmark_cache` :3725,
`_music_vector_cache` :3589) and `core/student_keys.py` `_cache` :66. All are
keyed by display name.

- **Before:** Built, keyed by display name.
- **After this lane:** `NOT_BUILT_OR_DEFERRED` here.
- **Reason:** another lane owns those cache functions. This lane does not
  touch them. Campus mode never reaches them because educator tutoring is
  disabled there.
- **Owner decision needed:** none beyond the cache lane's own scope.

### Exports, background work and frontend

| Path | Before | After this lane |
| --- | --- | --- |
| Exports / downloads for educators | None exist. `ExfiltrationGuard` blocks `/export`, `/download` and `/dump`. | `NOT_BUILT_OR_DEFERRED`. Nothing to export. |
| Background work | The streaming-transcription worker task (per voice session, in memory) and `log_event_nowait` audit tasks. | Voice worker: `BUILT_AND_QUALIFIED`. It is cancelled when the session is discarded on revocation. No queue or job runs per learner. |
| Frontend: educator voice start | `voiceApi.startVoiceStream(token, lang)` sends no learner scope. | `BUILT_AND_QUALIFIED`. An educator session sends its learner scope. Covered by a vitest invocation test. |
| Frontend: educator name routes (`api.ts:1227-1254`, `EducatorDesk.tsx`) | Name in URL. | Unchanged. In campus mode the backend 404s them. |

### Schemas and fixtures

| Path | Before | After this lane |
| --- | --- | --- |
| Request schemas | No `learner_id` or `campus_id` in any request model except pilot path params. | `StreamStartRequest` gains an optional `learner_id`, `campus_id` and `student_name`. A client-supplied campus is only ever compared, never trusted. |
| Fixtures | `tests/valor_synthetic_fixture.py`: deliberate same-name collision. | Reused. New tests seed through the real admin HTTP routes. |

## Shared authorization context (`services/pilot_authz.py`)

One immutable `PilotAuthzContext` carries these fields:

- principal UUID
- server-resolved campus UUID
- learner UUID
- action
- grant id
- grant version
- the educator's credential version

One function, `revalidate()`, re-reads all of it in a fresh database session.
It fails closed on any exception, because a check that cannot ask is
indistinguishable from one that said no.

### Grant identity

`PilotRosterGrant` gains a surrogate `grant_id` (UUIDv4) and a `version`.
Revoke and re-approve advance the version. A context minted under an older
version never revalidates, even if the grant is later re-enabled.

These are new columns on a table that exists only on #596. No deployed
database has the table, so `create_all` is a sufficient migration.

Legacy mode has no grant row. Its grant version is the educator's
`credential_version`, which `assign_class_roster` now bumps whenever a
replacement removes a learner (D5).

## Decisions needed from the owner

1. **Campus-mode tutoring.** Choose between:
   - building a learner-UUID-keyed tutoring path, which needs a UUID-keyed
     session configuration and UUID-keyed narration, bookmark and evidence
     tables; or
   - keeping educator tutoring disabled in campus mode until G2 and the cache
     lane land.

   This lane keeps it disabled.

2. **Assessment record of record for the pilot.** See the Assessments row
   above.
