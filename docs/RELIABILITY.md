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
`turn_id`, made once and reused by every retry of that turn, and each piece of
the child's work in it (one skill's evidence, the narration's scores, the
learning-style counter) is saved by only one attempt:

- **Marked only once it actually saved.** A save that failed, or never ran because
  the connection dropped first, is left for the retry to make. A turn that saved
  the skill evidence and then dropped before the narration has its narration
  saved by the retry, not lost.
- **Overlapping attempts take turns.** A retry that arrives while another
  attempt is in the middle of the same save waits for it, then skips the save if
  it went through or makes it if it did not.
- **A retry reports what was saved.** If the narration was already saved, the
  retry hands the screen and the model the summary that was saved, never a new
  one built from its own scoring.
- **The first saved answer stands.** A retry whose model records a different
  value for something already saved (the same skill, another outcome) does not
  overwrite it, since the child answered once. A different skill is saved.

The retry still answers the child in full.

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

- the app registers no service worker, and removes the one an older version
  left behind, with its `bede-*` caches. It removes only a worker running Bede's
  own `/sw.js` from this origin, and leaves any other on the origin alone (`src/utils/serviceWorker.ts`, called from
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
("Something went wrong") for a problem one reload fixes. Now, when a page file
fails to load, the app asks the server whether a new release is out: it fetches
the start page uncached and compares the script it names with the one this tab
is running. Only if they differ does it reload, once, which fetches the new
release. A marker stops it reloading again within a minute, so a server that is
genuinely missing a file shows the error screen rather than reloading forever.

The check matters. A browser also cancels the page files it was loading when
the page navigates away, for example on signing out or following a link, and
that failure looks the same. An earlier version reloaded on the failure alone,
and the browser journeys caught it on WebKit: a parent opening Parent Setup was
sent back by a reload of the page they were leaving. A failed page file with no
new release behind it is now logged and never reloads.

- `homeschool-tutor/src/utils/staleBuild.ts` (`releaseChanged`,
  `reloadOnceForNewRelease`), used by `src/components/ErrorBoundary.tsx`.
  `src/main.tsx` only records Vite's `vite:preloadError` event; the error
  screen alone decides whether to reload.
- Tests: `homeschool-tutor/src/components/ErrorBoundary.test.tsx`.

## A second reload no longer crashes the lesson on WebKit 26.0

Safari and iOS 26.0 (WebKit 26.0) have an engine bug, tracked by WebKit as
bug 300402. When the app moves to a new page within itself, WebKit does not
record that move. One reload then leaves the record empty, and the next reload
crashes the tab. The browser journeys caught this on a child's lesson page
(#861), and a blank test page with no Bede code crashes the same way. WebKit
26.6 does not have the bug.

A page cannot refuse a reload, so Bede removes what makes the second one fatal
(`homeschool-tutor/src/utils/webkitNavigationGuard.ts`). When the browser shows
it failed to record an in-app move, the app loads that same address once
properly, straight away. From then on reloads are safe. Other browsers, and
WebKit versions without the bug, never take this extra load. Words a child has
typed survive it (see "Unsent words survive a reload"), and so does sign-in.

The public demo carries the same guard (`demo/src/webkitNavigationGuard.ts`,
checked to match the app's copy). The demo does not move between pages that
way today, so there it only protects against a future change.

## A crash is recorded, not just shown

Any other error that reaches the error screen is a real bug. It is now written
to the debug log (the panel opened from the lesson header, and the way a family
reports a problem), telling a page that failed to load apart from a rendering
error. The error screen speaks the session's language.

## Unsent words survive a reload

What a child has typed or dictated but not yet sent is kept in the browser's own
storage for that tab, so a reload, a crash or the one-time update reload above
does not take it. It belongs to one sign-in and one learner: if the learner
changes, or someone else signs in, while the chat is open, the box shows that
person's own draft or nothing. It is removed once sent, at sign-out (including a
sign-out forced by an expired session), and when the tab closes. It lives in
that tab only, not on the device: another tab never sees it. Only one draft is
kept per tab, and a draft older than six hours, or stamped with an impossible
time, is discarded. Nothing is sent to the server until the child presses send.
See `docs/DATA_RETENTION.md`.

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
error naming the job if it ever stops, with the error's type and where it was
raised but never its message, which could carry a learner's name or a key.
Stopping at shutdown is normal and is
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
