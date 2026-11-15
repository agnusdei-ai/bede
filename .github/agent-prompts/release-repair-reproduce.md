# Release repair: reproduce

Read `release-repair-common.md` first.

Reproduce the failure on `revision.base_sha` in the environment the evidence
names. Reduce it without removing the behavior under test. Capture
diagnostics and sanitize them. Distinguish observation, hypothesis and
confirmed cause.

If the environment you have cannot reproduce it (for example, the failure is
macOS WebKit and you have no macOS runner), say so: `blocked`, with what
would be needed. Never report a result for a browser or device you did not
run. A Chromium run is not WebKit evidence, and emulation is not a device.

`status`: `reproduced` (with the reproducer in `observations`) or `blocked`.
