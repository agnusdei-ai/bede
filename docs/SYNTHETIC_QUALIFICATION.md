# Synthetic qualification

`.github/workflows/qualification.yml` and `scripts/qualification/` answer one
question about one fixed commit:

> At candidate SHA `X`, does the system as it would ship enforce G1 isolation,
> the DIBELS/Data Day rules, the G2 decision guarantees and the deletion
> lifecycle, on synthetic data, through the same roles, routes, connection
> path, pooling and SSE behaviour production uses?

It produces evidence. It decides nothing: no gate, no Engineering Complete,
no GO. It never merges, deploys, releases, dispatches another workflow, or
touches billing, enrollment, email or real data.

`homeschool-api/tests/test_qualification_workflow.py` guards every property
below against the parsed workflow YAML and the harness's own logic.

## What is real and what is not

Synthetic qualification differs from a live pilot only in data, environment
configuration and secrets. In this harness:

| Concern | How it runs |
| --- | --- |
| App process | `uvicorn main:app`, one worker, with the real lifespan (constitution check, DB init, encryption init). Stopped with SIGTERM and relaunched mid-run. |
| Database | A Postgres service container. The app connects as a **non-superuser** role (`QUAL_APP_DB_ROLE`, default `bede_qual_app`: `NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`) through production's `_build_engine()`. The role owns its database, so startup `CREATE TABLE IF NOT EXISTS` works as on a self-hosted install. |
| Admin login | Password, then a passkey enrolled and asserted through a **Chromium CDP virtual WebAuthn authenticator** (`webauthn_driver.cjs`), via the real `/mfa/webauthn/*` routes. Only that `webauthn_uv` session reaches the `/pilot` admin routes. |
| Teacher login | The real invite route (`POST /auth/educator-passkey/invite`) sends its enrollment email to the loopback mail sink. The harness reads the ticket from that email, then enrolls and signs in through `/auth/educator-passkey/register/*` and `/login/*` on the same virtual authenticator. See "Teacher login" below. |
| Seeding | Real HTTP routes only. Every name is checked against a synthetic allowlist. The two learners share one display name on purpose. |
| SSE | Real HTTP streams read in a background thread. Data events, keep-alive pings, a server-ended stream and a client-side error are recorded separately, so a client error is never read as the server closing a stream. |
| Browser vs API | The same read is made through the browser page's `fetch` and through the API client, which presents the browser's User-Agent (tokens are IP+UA fingerprinted). |
| AI vendor | `ai_stub.py`, a loopback OpenAI-compatible server, forced with `BEDE_FORCE_ADAPTER=local`. Its request log records route, model and message count, never content. |
| Mail | `mail_sink.py`, a loopback Resend-compatible endpoint. The application's own `send_email` reaches it through `RESEND_API_BASE_URL`. |
| TLS | The stack is served over https with a self-signed certificate generated for the run, because the invite route requires an https `WEBAUTHN_ORIGIN`. Chromium trusts exactly that certificate's key (`--ignore-certificate-errors-spki-list`) and the API client verifies against it. |

The AI stub and the mail sink are the **only** two stubbed dependencies.

Environment differences from a production install, all configuration:
`PRODUCTION=false`, `WEBAUTHN_ORIGIN=https://localhost:8765` with the run's
own certificate, `RESEND_API_BASE_URL` pointing at the loopback sink, and raised
`RATE_LIMIT_AUTH_PER_MINUTE` / `RATE_LIMIT_API_PER_MINUTE`, because one
client IP drives every principal's ceremonies. `DISABLE_API_DOCS=true` as in
production: route presence is read from the app object, not `/openapi.json`.

## Pipeline

1. **Candidate SHA.** `workflow_dispatch` takes `candidate_sha`, a full
   40-character SHA. A pull-request run uses the PR head SHA. The workflow
   refuses anything else, checks that commit out, and fails if `HEAD` differs.
   A branch name is never accepted, because a branch can move mid-run.
2. **Preflight, fail closed** (`preflight.py --phase pre-start`). Every check
   is written to `preflight-pre-start.json`, pass or fail. It exits non-zero on:
   - `PRODUCTION` not `false`;
   - any commercial AI key, notification address, license server, licence
     key, Stripe or operator credential, or any `STRIPE_*` variable;
   - mail aimed anywhere but this run's sink. Specifically:
     - `RESEND_API_BASE_URL` must be exactly `http://127.0.0.1:8767`;
     - `RESEND_API_KEY` and `RESEND_FROM_ADDRESS` are only accepted together
       with that sink;
     - the key must be a `synthetic-` key, so a real Resend `re_...` key
       fails;
     - the sender, and `EDUCATOR_INSTITUTION_EMAIL_DOMAIN`, must be the
       synthetic domain;
     - `EDUCATOR_BOOTSTRAP_EMAILS` must be empty;
     - any other `RESEND_*` variable fails;
   - any variable named for real data, billing, auto-enrollment, an auth
     bypass or delivery that is switched on;
   - `EDUCATOR_PILOT_ENABLED` off, which would close the routes under test so
     everything passes vacuously; or `ELEVATION_ENFORCED` off;
   - a non-loopback AI provider, or any adapter but `local`;
   - a `DATABASE_URL` outside the service host allowlist, an app role that is a
     superuser or can create roles or bypass RLS, or a database that already
     holds tables;
   - any route under `/pilot` whose path words name a session, launch, start,
     delivery, tutoring, chat or stream; `routers/tutor.py` or
     `services/ai_service.py` mentioning `authorized_instruction` or
     `pilot_session`; or a `TutorRequest` field naming `pilot`. This mirrors
     #604's `test_valor_pilot_delivery_disabled.py`.
3. **Image (optional, dispatch default on).** The API image is built at the
   candidate SHA with an `org.opencontainers.image.revision` label. Its digest
   is recorded. It is never pushed.
4. **Run** (`run.py`). Start the stub and the server, seed, re-check the
   database role, run the matrix, and write the reports.
5. **Package** (`package.py`, always). The credential scan runs first and
   fails closed: credential-shaped strings and every secret value the run
   generated are searched for in every collected file. A hit quarantines the
   file and stops the upload. Otherwise it writes `manifest.json` and
   `SHA256SUMS`.
6. **Upload** (always, but only after a clean scan) as
   `qualification-<sha>`, with retention from `artifact_retention_days`.
7. **Final verification** (always) fails the job unless both the matrix and
   the package succeeded.

## The matrix

`matrix.py`'s `TABLE` is the one declarative list of protected record types
and the routes that serve them, grouped G1, DIBELS, G2 and DELETION. Route
templates can be overridden without a code change via
`QUAL_ROUTE_OVERRIDES='{"assessment.read": ["GET", "/pilot/me/learners/{learner_id}/x"]}'`,
for when another lane lands a route under a different path.

| Status | Meaning |
| --- | --- |
| `PASS` | The rule held, observed over the wire. |
| `FAIL` | The rule was violated, or the route misbehaved. |
| `ABSENT` | The route the rule needs is not in the candidate's route table. |
| `BLOCKED` | A precondition outside the rule failed, for example no teacher session could be obtained. |
| `UNVERIFIED` | The route exists but the rule cannot be observed over HTTP by this harness. The reason is stated. |

**Every status except `PASS` fails the run.** A missing route is never
skipped. Several routes are still being built in other lanes, so their rows
are `ABSENT` until those land. That is the candidate's honest state.

Rules exercised per record type: own access; cross-campus read and write;
random, malformed, non-canonical and nil ids, each required to return the
byte-identical response an absent id returns; and same-name isolation.

Scenario cells cover:

- browser/API agreement;
- voice-session owner binding;
- G2: evidence-linked recommendation, recommendation not an approval,
  approve/edit/reject, replay, true concurrency over two connections,
  cross-campus and substituted-id decisions, ledger chain, and
  instruction recorded rather than delivered;
- revocation: old session, new session, list, active voice stream,
  reconnect, post-revocation write and voice start, decision after
  revocation, audit evidence, and the other teacher unaffected;
- restart persistence, before and after revocation;
- deletion.

Two cells are `UNVERIFIED` by design and say why:

- **Failed-audit-write atomicity** cannot be induced over HTTP without fault
  injection into the server. The in-process test lives with #604.
- **Post-delete cache eviction** is not observable over HTTP beyond the read
  denial.

DIBELS/Data Day rows are bound to the canonical campus-scoped routes
(`/pilot/campuses/{campus_id}/learners/{learner_id}/assessments...` and
`/data-day?cycle=`, `routers/pilot_assessments.py`). `path()` fills
`{campus_id}` with the addressed learner's own campus, so a teacher copying
another campus's learner copies that learner's whole path. Before the DIBELS
rows the harness sets each campus's Valor default calendar through the real
elevated admin route (cell `campus_calendar_configured`). Each semantic cell
is a real probe over HTTP on synthetic progress-monitoring records (no
licensed-benchmark authorization is needed):

| Cell | What is observed |
| --- | --- |
| `progress_monitoring_not_benchmark` | A PM record carrying an official window is refused (422); a finalized PM appears only in the progress-monitoring series, with window `none`. |
| `skipped_measure_not_zero` | A skipped measure with `raw_score: 0` is refused (422); a stored skipped measure has no score, is listed as skipped, and is in no growth series. |
| `interrupted_not_finalized` | From `INTERRUPTED`, finalize and submit are 409, and resume without a written resolution is 409. |
| `interpretation_never_overwrites_score` | Evidence, Bede's proposal and a teacher edit leave the finalized scores and snapshot hash unchanged; re-scoring after finalization is 409. |
| `packet_changes_no_official_score` | Reading the packet changes no score; its `boundaries` deny changing scores or placement. |
| `packet_starts_no_instruction` | `boundaries` deny starting or delivering instruction; every prior decision outcome is `NOT_REQUESTED`; no delivery wording. |
| `packet_shows_skipped_and_invalid_states` | An invalid administration is listed as not valid and excluded from valid results; skipped measures are shown. |

`revocation_is_audited` requires an audit entry whose event is the admin
revoke action itself (`pilot.roster_grant_revoked`) and whose detail names
the revoked learner's UUID. A loose substring such as "revoke" is not
accepted, because #606's `authz.revoked_in_flight` also contains it and
exists only when a stream happened to be open.
`revocation_closes_active_voice_stream` treats any data event after
revocation as protected output, except the server's exact terminal notice
`{"type": "error", "message": "unknown or expired session"}`.

Learner deletion has no HTTP route on the G1 integration head (the service
`services/pilot_learner_deletion.py` exists; its owner route ships with
#609), so the deletion cells are `ABSENT`. Its stream, cache and reconnect
behaviour is covered in-process by
`homeschool-api/tests/test_g1_integration_streams.py`.

SQLite/Postgres agreement belongs to the pytest suites. This harness runs on
Postgres only.

## Teacher login

The application has one mail transport, Resend. `RESEND_API_BASE_URL` in
`core/config.py` is the narrowest change that lets a run capture the invite
email:

- empty, the default, is `api.resend.com` exactly as before;
- only an `http(s)` loopback URL with no credentials is accepted;
- **any** value is refused when `PRODUCTION=true`.

`homeschool-api/tests/test_mail_endpoint_loopback.py` pins all three, plus
the real `send_email` reaching the configured URL. Each was verified by
breaking it. No product route, enrollment path or bypass was added.

The sink (`mail_sink.py`):

- binds loopback only;
- requires the run's synthetic key as the bearer token;
- refuses any recipient outside the synthetic domain;
- writes raw messages only to the run's temp directory (`QUAL_MAIL_SINK_DIR`,
  default `<out>-tmp/mail`), never to the evidence directory, because they
  carry live enrollment tickets;
- writes a redacted line per message to the evidence (`mail-sink-messages.jsonl`:
  recipient domain, subject, body SHA-256).

`package.py`'s credential scan covers both:

- it scans the sink store for credential shapes;
- it refuses any evidence file that contains a ticket token the sink captured.

On base `1b48e234` this takes the default mode through the real invite route
(202), the email to the sink, the real register and login ceremony (200 at
every step), and the roster grants.

**Documented fallback:** `teacher_auth_mode: minted_token` creates the teacher
accounts with the production `provision_educator` service. It mints tokens
with exactly the payload, fingerprint and lifetime that
`educator_passkey_runtime.verify_authentication` and `login_verify` produce.
It is the only harness path that touches the database directly. The manifest
records it under `deviations`, and it never exercises the teacher ceremony.
Default: off.

## Concurrency

The workflow uses the brief's block verbatim:

```yaml
concurrency:
  group: qualification-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

A superseded PR run is cancelled. An **in-progress** dispatched run is never
cancelled by a newer run, and no job-level concurrency or cancel step exists.

GitHub's documented semantics leave one gap this block cannot close. When a
run is already in progress in the group, a newly queued run waits, and a
*third* queued run replaces the *waiting* one. So a dispatched run that is
still pending, behind another dispatch to the same ref, can be superseded
before it starts. Closing that needs a per-dispatch group, which would change
the block the brief fixes. That is an owner decision.

## Inputs

| Input | Default | Purpose |
| --- | --- | --- |
| `candidate_sha` | required | The commit qualified. |
| `teacher_auth_mode` | `virtual_authenticator` | Or the documented `minted_token` fallback. |
| `app_db_role` | `bede_qual_app` | Non-superuser application role. |
| `postgres_image` | `postgres:16` | Service image. |
| `python_version` | `3.12` | API and harness Python. |
| `playwright_version` | `1.56.0` | Chromium driver for the virtual authenticator. |
| `build_images` | `true` | Build the API image at the SHA and record its digest. |
| `artifact_retention_days` | `30` | Evidence retention. |
| `mac_package` | `none` | **G3 placeholder only.** |

Every harness setting also has a `QUAL_*` environment override in
`scripts/qualification/qualconfig.py`, including the synthetic names, the
forbidden-variable lists, the delivery markers, ports and timeouts.

## G3 / Mac

Not implemented. `mac_package` accepts only `none`. The manifest records
`built: false` and `physical_mac_verification: NOT RUN`. Physical Mac
verification is a human step for the release owner, and this workflow never
performs it or claims it.

## Running it locally

```bash
export QUAL_CANDIDATE_SHA=$(git rev-parse HEAD)
export QUAL_DB_ADMIN_URL=postgresql://postgres@127.0.0.1:5433/postgres   # bootstrap superuser
export QUAL_APP_DB_PASSWORD=synthetic-$(openssl rand -hex 12)
export DATABASE_URL=$(python scripts/qualification/db_setup.py --db bede_qualification_local)
export RESEND_API_BASE_URL=http://127.0.0.1:8767                         # the loopback sink
export RESEND_API_KEY=synthetic-$(openssl rand -hex 16)                   # accepted only by the sink
# plus SECRET_KEY, MASTER_SECRET, PARENT_PASSWORD and the application
# environment block from qualification.yml's job env
python scripts/qualification/preflight.py --phase pre-start
python scripts/qualification/run.py        # 0 all PASS, 1 some cell not PASS, 2 harness error
python scripts/qualification/package.py
```

`playwright` must resolve from the repository's `node_modules` or from
`NODE_PATH`. Evidence lands in `qualification-out/`, which is gitignored.
