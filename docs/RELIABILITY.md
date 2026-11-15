# Reliability: how Bede recovers by itself

Bede runs on a family's own machine, with children on tablets. Nobody is
watching a dashboard, so when something goes wrong Bede should either recover
on its own or say plainly what happened. This document lists what recovers by
itself today, how, and what does not yet.

Every item below is pinned by a test that fails when the behavior is removed.
Each test was checked by putting the old behavior back and watching it fail.

## A lesson turn survives a dropped connection

**What happens.** When the connection drops before any of Bede's reply reaches
the tablet, the app sends the turn again: up to six attempts over about 25
seconds, waiting for the browser to come back online if it reports being
offline. The child's words are never lost to a weak signal. See
`docs/DIAGNOSTICS.md` for the full rules, including what is deliberately never
retried.

**And the work is recorded once.** The server saves the child's work while it
builds the reply: skill evidence, the work ledger, a narration's scores, the
learning-style counters. A retry that reached the server after an earlier
attempt had already saved something used to save it again, so the parent's
Progress page showed work done once as work done twice. Each turn now carries a
`turn_id`, made once and reused by every retry of that turn, and the server lets
only the first attempt that saves anything save at all. The retry still answers
the child in full.

The server remembers turn ids for ten minutes, in memory, in one process. A
retry that reached a different server process, or arrived after a restart,
would save again, which is the old behavior rather than a new failure. Both
supported deployments run one process. The public demo sends no turn id and
behaves as before.

- Server: `homeschool-api/services/turn_replay.py`, checked before every save
  in `services/ai_service.py`'s `stream_tutor_response`, built from the request
  in `routers/tutor.py`.
- App: `homeschool-tutor/src/services/api.ts`'s `streamTutorChat`.
- Tests: `homeschool-api/tests/test_turn_replay.py`,
  `homeschool-tutor/src/services/tutorRetry.test.ts`.

## An update reaches every tablet

**The offline cache is retired.** Bede used to install a service worker that
kept the app's pages in a cache with a fixed name and served them from that
cache first. Wherever it ran, a tablet could keep running an old release after
`make update` until the cache happened to be cleared.

On the family Docker deployment it never ran at all. nginx refused
`/manifest.json` (a rule blocks every `.json` file), the worker's install step
fetched that file, and so the install failed every time. Families lost nothing
by its removal. The same refusal also broke the home-screen app manifest, so a
tablet that added Bede to its home screen got no name, icon or display mode
from it.

So:

- the app registers no service worker, and removes any an older version left
  behind, with its caches (`src/utils/serviceWorker.ts`, called from
  `src/main.tsx`);
- `public/sw.js` now only removes itself: a browser that still has the old
  worker fetches it, deletes the old caches and unregisters, and from then on
  nothing is intercepted. Open pages are never reloaded, so a lesson in
  progress is not interrupted;
- nginx serves `/manifest.json`, and serves `/sw.js` uncached, both with the
  same security headers as every other page, and still refuses every other
  `.json` file (`homeschool-tutor/nginx.conf`).

This fits `docs/DECISIONS.md` entry 19, which rejected offline-tolerance work
(service workers among it): a household's server is in the same building as
its tablets.

- Tests: `homeschool-tutor/src/serviceWorker.test.ts`;
  `homeschool-api/tests/test_nginx_manifest_and_worker.py`, which also runs the
  real nginx against the real config when nginx is installed (GitHub's Ubuntu
  runners have it). The browser journeys check that no worker is left in
  control of the page.

**A tab left open across an update reloads itself once.** Most of the app's
pages are loaded on demand, from files named after their contents. After an
update those files are replaced, so a tab opened before the update fails to
load the next page it opens. That used to show the child the error screen
("Something went wrong") for a problem one reload fixes. Now a page file that
fails to load reloads the app once, which fetches the new release. A marker
stops it reloading again within a minute, so a server that is genuinely missing
a file shows the error screen rather than reloading forever.

- `homeschool-tutor/src/utils/staleBuild.ts`, used by
  `src/components/ErrorBoundary.tsx` and `src/main.tsx` (Vite's
  `vite:preloadError` event).
- Tests: `homeschool-tutor/src/components/ErrorBoundary.test.tsx`.

## A crash is recorded, not just shown

Any other error that reaches the error screen is a real bug. It is now written
to the debug log (the panel opened from the lesson header, and the way a family
reports a problem), telling a page that failed to load apart from a rendering
error. The error screen speaks the session's language.

## Unsent words survive a reload

What a child has typed or dictated but not yet sent is kept in the browser's own
storage for that tab, so a reload, a crash or the one-time update reload above
does not take it. It is removed once sent, when anyone signs out (so the next
person on a shared tablet never sees it), and when the tab closes. Only one
student's draft is kept per tablet, and a draft older than six hours is
discarded. Nothing is sent to the server until the child presses send. See
`docs/DATA_RETENTION.md`.

- `homeschool-tutor/src/utils/chatDraft.ts`, used by
  `src/components/SocraticChat.tsx` and cleared in `src/store/sessionStore.ts`'s
  `logout`.
- Tests: `homeschool-tutor/src/components/SocraticChat.draft.test.tsx`.

## A background job that stops is reported

The API runs several jobs on a timer: purging expired data, re-reading the
license, refreshing revoked devices and changed credentials, checking a local
AI model is reachable, and (when configured) the license heartbeat. Each
catches its own errors and tries again next time, so none should ever finish.
One that did, through an error escaping its handler or a loop that returns,
used to stop with nothing in the logs, and its work simply stopped happening.
Every job now starts through `main.py`'s `_start_background`, which logs an
error naming the job if it ever stops. Stopping at shutdown is normal and is
not reported, and the one-time voice-model warm-up is reported only if it
fails.

- Tests: `homeschool-api/tests/test_background_jobs.py`, which also checks the
  real `main.lifespan` starts no job without the watcher.

## Already in place before this work

- A tutoring stream that stalls or errors always ends with a clean `done`, so
  the child's send button never spins forever (`routers/tutor.py`,
  `tests/test_tutor_stream_resilience.py`).
- A failing AI provider fails over to the next configured one, with a short
  cooldown on the failed one, and three backend failures in ten minutes email
  the parent (`services/adapters/router.py`, `core/audit.py`'s
  `AI_BACKEND_FAILURE`; see `CLAUDE.md`'s "AI backend failure alerting").
- The voice pipeline recovers from a dropped stream (see `docs/VOICE_SETUP.md`).

## Not yet covered

- **A container that stops answering is not restarted.** `docker-compose.yml`
  restarts a container that exits, not one that is still running but stuck.
- **No single reliability record.** Recoveries above are logged where they
  happen; there is no one place a parent or operator can read "what went wrong
  this week and what recovered".
- **More than one server process.** Turn ids and voice sessions are held in one
  process's memory. Neither supported deployment runs more than one.
