# Capacity: how many children one Bede backend serves at once

Bede runs as **one** API process (`homeschool-api/Dockerfile` starts uvicorn
with `--workers 1`, because voice sessions and turn-replay records live in
memory). So "how many children can use Bede at the same time" is a question
about one process, one database pool and one machine. The capacity run
measures it and publishes the curve and the limit.

**It is a report, not a gate.** Nothing reads its result: it blocks no merge
and no release. A step that misses a threshold is a finding in the report.

## What it does

`.github/workflows/capacity.yml` (dispatch only) boots the real stack on one
runner (Caddy, nginx, the API and Postgres, exactly as `make start` does, with
a throwaway licensed production `.env`) and then:

1. **Real Chromium sessions, the primary result.** 1, 2, 4, 6, 8 and 10
   sessions at once, each a full child session: sign in with the learner's
   name and PIN, lesson turns, one answer to a parent-approved practice
   question through the app's own practice card, and a reload that must land
   back in the lesson. The report states **PASS, FAIL or NOT_RUN at 10
   sessions**. A run that could not reach 10 sessions is NOT_RUN at 10, never
   a pass.
2. **API clients, for headroom above 10.** The same child requests, sent by
   lightweight clients (1 to 64 by default), to find where the backend stops
   meeting the thresholds.

The model is the loopback stub with fixed delays (one second for the
moderation check, half a second to the first streamed words), so the stub's
own share of every turn is a known constant.

### Every device has its own address

The per-IP rate limit (`core/middleware.py`) keys on the client address, and a
household's tablets each have their own LAN address. Browsers on one runner
would all share one, so each sample device goes through its own relay
(`scripts/qualification/capacity/relay.py`) bound to its own address on the
stack's network. The report records the address the API actually saw for each
device, and also what it sees for several devices on the runner's own
loopback reaching the published port 443, which is the "everyone on one
address" case.

On a real network nothing needs a relay: Caddy passes the tablet's own address
in `X-Forwarded-For`, nginx appends its own, and uvicorn (`--proxy-headers
--forwarded-allow-ips=*`) hands the first one to the app. On the local target
the same check runs through `vite preview` with `xfwd`, and the API saw one
distinct address per browser and per client.

## Dispatching a run

Actions, then **Capacity (report only)**, then **Run workflow**:

| Input | Meaning |
|---|---|
| `candidate_sha` | The full 40-character commit to measure. Required. |
| `target` | `stack` (the real compose stack, the result) or `local` (uvicorn and `vite preview` on the runner, SQLite; a quick look). |
| `parts` | `browser,api`, `browser` or `api`. |
| `browser_steps`, `api_steps` | Comma-separated session counts. Empty uses `capacity.json`. Browser steps stop at 10 (one learner per browser, ten per pod). |
| `window_seconds` | Steady-load seconds per step. Empty uses `capacity.json`. |
| `model` | `stub`. `ollama` is reported NOT_RUN: a run against a small local model is not built yet. |
| `db_pool_size`, `db_max_overflow`, `rate_limit_api_per_minute` | Optional overrides. Empty means the shipped default. A run with any override is labelled **NON-DEFAULT** in the report. |

To compare a raised setting against the shipped one, dispatch twice on the same
commit: once with the overrides empty, once with them set, and read the two
reports side by side.

The evidence is the `bede-capacity-<target>-<sha>` artifact: `report.md`,
`report.json`, the service logs, the stub's call log and `SHA256SUMS`. The
report is also on the run's summary page. Before anything is written, a
credential scan checks for the run's own secrets and every learner PIN; if it
finds one, the evidence is withheld and the run fails.

## Reading the report

For each step: first-token time (when Bede's first words reach the child),
full-turn time, every 5xx and 429, dropped and duplicated turns and practice
answers, the API's memory (against its `mem_limit`), CPU, threads, open file
descriptors and disk I/O, the database pool (peak demand, meaning the most
connections wanted at once, against the pool's size plus overflow, and the time
to get one; demand above capacity means requests queued, and a wait at the
30-second ceiling is the pool's own timeout), Postgres's data size and free
space, the container's OOM and restart state, and the runner's own CPU and
memory.

- **Supported sessions** is the largest step that met every threshold, with
  every smaller step meeting them too. A passing step above a failing one is
  noise, not capacity.
- **Closest limit** names what binds first: the database pool, the rate limit,
  CPU, memory, or the model stub. It is judged at the first failing step, or,
  if nothing failed, at the supported step (what is nearest).
- **First step each failure class appeared**: response (5xx, timeout, dropped
  or duplicated turn, a stalled reply stream, slow first words), I/O (disk or
  database errors in the API log), memory (OOM, restart, memory above 90% of
  the limit), threads/fds (exhaustion errors in the log), or client-side (the
  runner itself saturated, which is a limit of the test, not of Bede).
- The **Family Membership's six seats** appear as a reference line on the
  table, not as a gate.

Every threshold lives in
[`scripts/qualification/capacity/capacity.json`](../scripts/qualification/capacity/capacity.json):
zero 5xx, zero 429, zero dropped or duplicated turns, no OOM and no restart,
and a p95 first-token time no more than 3 seconds over the one-session median.

## What it does not measure

- **Stub latency is not model latency.** A real model, local or cloud, adds its
  own time per turn and its own limit on concurrent requests. The curve says
  how much Bede itself adds as sessions grow, not how fast a given model is.
- **A CI runner is not a family's server.** The runner has 4 cores and 16 GB;
  a Raspberry Pi or a mini PC is smaller and differently shaped. Read the shape
  of the curve and which limit binds, not the absolute count.
- **Voice is not exercised.** Transcription is serialized on purpose
  (`VOICE_TRANSCRIPTION_MAX_CONCURRENCY` is 1, see
  [VOICE_SETUP.md](VOICE_SETUP.md)), so many children speaking at once queue
  behind each other. That queue is not measured here.
- **The browsers and the stack share one runner** (one job, one machine). The
  runner's own CPU and memory are recorded at every step so a saturated runner
  reads as client-side, never as a Bede limit. Measured on a machine the size
  of the runner (4 cores, 16 GB): 10 Chromium sessions plus the API, the UI
  server and the stub used about 4.4 GB of browser memory, 14% of memory and a
  sustained 48% of CPU, so the single-job layout fits with room to spare. If a
  stack run ever reports client-side, split the browsers onto a second job.
- The instrumented launcher (`instrumented_api.py`) runs the same app with the
  same uvicorn flags as the image, plus read-only counters. It is never part
  of a family's deployment.

## What the first runs found

Measured on 2026-11-15 at commit `2352598`, **local target** (one 4-core,
16 GB machine, SQLite, no docker), 60-second windows, model stub. The stack
target, with Postgres, has not run yet; treat these as the first reading, not
the result.

| Run | Browser sessions supported | At 10 browsers | API clients supported | What failed first |
|---|---|---|---|---|
| Shipped pool (5 + 5) | 8 | **FAIL** | 8 | the database pool |
| Raised pool (20 + 20, NON-DEFAULT) | 10 | PASS | 32 | the database pool, again, at 48 |

The failure is a cliff, not a slope. Up to 8 sessions every turn's first words
arrived in about 1.6 seconds (the stub's own 1.5 plus Bede's overhead); at 10
browsers or 12 clients, demand for connections passed the pool's 10, requests
waited the pool's full 30-second timeout, first words took over 31 seconds,
some turns ended in a 500, and audit writes failed in the log. Memory stayed
near 250 MB of the 1024 MB limit and the API's CPU stayed low throughout: the
process was waiting, not working. Peak pool demand ran at roughly one and a
quarter connections per active session, because a lesson turn holds its
request's connection for the whole streamed reply while the same turn opens
further short sessions (usage and audit records).

Every sample device reached the API from its own address in both runs (one
distinct client per browser and per API client), so the per-IP rate limit
refused nothing at 60-second windows. A shorter smoke run (20-second windows,
so one device signed in and reloaded twice in two steps inside one minute)
drew three 429s from the sign-in bucket (`RATE_LIMIT_AUTH_PER_MINUTE`, 10 a
minute per device), and the refused reload put that child back at the sign-in
screen. Each page load checks the session against `/auth/`, so the sign-in
bucket was spent by reloads as well as sign-ins. That is a per-device pattern,
not a capacity limit, but it is the one a tablet that keeps reloading would
meet first. **Fixed:** the read-only status checks every page load makes
(`GET /auth/validate`, `/auth/locales`, `/auth/educator-mode`, `/auth/elevate`)
now count against the general API bucket; every credential attempt still
counts against the sign-in bucket (`core/middleware.py`,
`tests/test_middleware.py`).

## The database pool setting

`DB_POOL_SIZE` and `DB_MAX_OVERFLOW` (default 5 and 5, the values the engine
always used) are settable in `.env`. Do not raise them without a capacity run
that shows the pool binding, and keep their sum below your database's
connection limit.

## Running it on your own machine

Without docker, from the repository root, with the API's dependencies
installed, the UI built (`npm run build` in `homeschool-tutor/`) and Playwright
available:

```bash
python scripts/qualification/capacity/run_capacity.py --sha "$(git rev-parse HEAD)" \
  --target local --parts browser,api --out /tmp/bede-capacity
```
