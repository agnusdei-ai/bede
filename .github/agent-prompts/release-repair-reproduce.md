# Release repair: reproduce

Read `release-repair-common.md` first.

Reproduce the failure on `revision.base_sha` in the environment the evidence
names. Reduce it without removing the behavior under test. Capture
diagnostics and sanitize them. Distinguish observation, hypothesis and
confirmed cause.

If the environment you have cannot reproduce it (for example, the failure is
macOS WebKit and you have no macOS runner), say so: `blocked`, with what
would be needed, and set `"blocked_code": "environment_unavailable"` when
that is the ONLY reason. The task then waits for a trusted diagnosis run
the coordinator dispatches (for WebKit, `webkit-reload-diagnosis.yml` on a
hosted macOS runner); the controller records that run as evidence. Do not
copy its numbers into your result as though you ran it. Never report a
result for a browser or device you did not run. A Chromium run is not WebKit
evidence, and emulation is not a device.

`status`: `reproduced` (with the reproducer in `observations`) or `blocked`.
