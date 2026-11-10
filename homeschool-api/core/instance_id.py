"""
A per-process identifier for diagnosing exactly one question: did this HTTP
request land on the same backend process as an earlier one for the same
logical session?

See docs/VOICE_SETUP.md's "single-process, in-memory only" note on
services/streaming_transcription.py — under Render autoscaling (or any
horizontally-scaled deployment), a voice-stream session's start/chunk/finish
calls can be routed to different instances, and each instance's in-memory
`_sessions` dict has no way to see another instance's sessions. That failure
was reported from a real device: a session opened successfully, then the
very next chunk/finish calls against that same session id 404'd seconds
later — "Unknown or finished streaming session" — well under the 180s TTL,
which is exactly the shape cross-instance routing produces and no other
cause in this codebase does.

`INSTANCE_ID` makes the two cases distinguishable from the OUTSIDE, without
touching how sessions are stored: `core/middleware.py`'s
`InstanceIdHeaderMiddleware` stamps every voice-stream response with it, and
the client logs it alongside the debug trace already used to report this. If
`start` and the `chunk`/`finish` that immediately follows it carry two
different instance ids, that confirms cross-instance routing directly from a
browser trace — no server log access required.

Deliberately NOT a fix and NOT a step toward one: purely observational,
resolved once at process start, and nothing else in the app reads it.
"""
import os
import uuid

# Render sets this automatically for every running instance of a service —
# https://render.com/docs/environment-variables#all-runtimes. Preferred
# because it's the real, platform-assigned identity the actual question (are
# requests landing on different replicas?) is about. The random fallback
# keeps this useful on a self-hosted single-instance deployment too (where
# RENDER_INSTANCE_ID is never set) and, as a side effect, changes on every
# process restart — a session that failed because its instance recycled
# mid-turn is a different, equally real cause this same signal happens to
# catch.
_HOST_ID = os.getenv("RENDER_INSTANCE_ID") or f"local-{uuid.uuid4().hex[:8]}"

# The process id is part of the value because one instance can run several
# worker processes, and RENDER_INSTANCE_ID is the same in all of them. Each
# worker has its own in-memory sessions, so the host id alone could not tell
# "same process" from "another worker on the same instance": a 2026-11-10
# demo trace showed a voice session 404ing on its own next request with an
# identical instance id on every line. With the pid, a worker split shows up
# as a different `.p<pid>` suffix on the failing request.
INSTANCE_ID = f"{_HOST_ID}.p{os.getpid()}"
