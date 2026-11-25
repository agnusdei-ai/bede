# Automatic public demo closure

Owner-approved public beta endpoint: **December 31, 2026, end of day
America/Chicago**. Access closes at January 1, 2027, 00:00 CST
(`2027-01-01T06:00:00Z`). This does not change paid licenses, family trial
terms, private parent/child sessions, or Pilot HOLD.

## Enforcement

- `core/public_demo_beta.py` owns the fixed server deadline.
- Code creation and demo-code login return HTTP 410 after the cutoff,
  before minting or redeeming a code.
- New demo JWTs cannot expire later than the deadline. The shared signed
  token verifier also rejects all existing `demo_code` JWTs at the cutoff,
  including tokens issued before this change with a later expiry.
- Protected requests use server time, independent of browser clocks.
  Requests already processing at the cutoff may finish; this is not a
  process shutdown or deletion of data.
- The browser checks the matching deadline every second and on tab resume.
  It unmounts demo flows and clears saved authentication when closed,
  including restored sessions. Changing a device clock cannot bypass
  server enforcement.
- The closed screen keeps `/inquire/` and `info@agnusdei.ai` available.
  Business inquiry and survey endpoints are not disabled.
- `GET /auth/demo-status` exposes only the fixed deadline, its time zone,
  and whether server time has reached it. It is a read-only deployment
  verification surface, not an extension switch.

Any extension requires a new owner-approved change. No scheduler, external
account change, new secret, or midnight deployment is required.

## Validation

Boundary tests cover the last microsecond before closure, exact closure,
mint/redeem refusal, existing demo JWT rejection, and unaffected family
roles. Frontend tests cover an open tab crossing the deadline, mobile
resume, timer cleanup, API/browser date parity, and the closed screen's
onboarding contacts. No live email or tutoring session is needed to verify
the behavior.
