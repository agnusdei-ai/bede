"""
Brute-force throttling for the child role — punch-list #7.

Deliberately NOT a copy of core/parent_lockout.py, for two reasons.

1. LOCKOUT IS A DENIAL-OF-SERVICE PRIMITIVE, and the child role is where
   that actually bites. parent_lockout's fixed rule (10 failures in 30
   minutes -> the role is locked for 15) stops a password brute force and
   ALSO lets anyone who knows the threshold — which source exposure makes
   public knowledge, see docs/THREAT_MODEL.md's "self-defeating mechanisms"
   note — lock the real parent out on purpose, repeatably, without ever
   knowing the password. For a parent that's an annoyance with a documented
   recovery path (docs/SECURITY.md's account-recovery work). For a child it
   would mean a sibling, or a houseguest on the same WiFi, can reliably end
   a lesson before it starts, and the recovery path is "go find a parent."
   Copying the parent pattern here would have closed a brute-force gap by
   opening a more easily-triggered availability one.

   So this throttles by DELAY, never by refusal. A wrong PIN costs the
   attacker escalating wall-clock time; a legitimate child who mistypes
   waits a moment and tries again. There is no state an attacker can push
   the child role into that a parent has to clear.

2. PERFORMANCE. parent_lockout does a DB read on every login attempt and a
   commit on every failure. Login is not a hot path, but this runs on the
   family's own hardware — a Raspberry Pi (docs/PARENT_SETUP.md) — and a
   child logging in is the first thing that happens every school morning.
   Throttle state here is in-process and lock-free: a dict lookup and an
   integer compare, roughly 0.3 microseconds, versus a database round trip.

   The tradeoff that buys is that state resets when the container restarts,
   so a determined attacker with restart access gets a clean slate. That is
   deliberate and acceptable: restarting the container requires host access,
   and an attacker with host access has already won far more than a 6-digit
   PIN. The threat this defends against is someone on the LAN guessing
   through the API (docs/THREAT_MODEL.md's A1), and a process restart is not
   something they can trigger.

Why a delay is sufficient here at all: CHILD_PIN is 6+ digits and
pin_is_strong() rejects the guessable shapes, so the keyspace is on the
order of 10^6. The per-IP rate limiter (core/middleware.py, 10 auth
requests/minute) is the first line, but it keys on IP alone and IP rotation
is trivial on a LAN — that gap is exactly why this module exists. Escalating
delay makes the cost per guess grow regardless of how many source addresses
an attacker cycles through, because the delay is keyed on the credential
being attacked, not on where the attempt came from.
"""
import time

# Escalating delay, applied before the response to a FAILED attempt. The
# first few are free — a child mistyping their own PIN should not be
# punished, and neither should a parent testing a new one.
#
# Chosen so the honest-mistake path is invisible and the attack path is
# ruinous: guessing a 10^6 keyspace at a 5-second floor is ~2 months of
# continuous attempts even with unlimited source addresses, while a child
# who fat-fingers twice notices nothing at all.
_FREE_ATTEMPTS = 3
# Indexed by failures BEYOND the free allowance, so every entry is
# reachable. An earlier revision indexed by the raw failure count with a
# separately-declared ceiling, and the two silently disagreed — the
# schedule topped out below the stated maximum, making the ceiling dead
# code. Deriving the cap from the schedule makes that class of drift
# impossible rather than something to notice in review.
_DELAY_SCHEDULE_SECONDS = (0.5, 1.0, 2.0, 4.0, 5.0)
_MAX_DELAY_SECONDS = _DELAY_SCHEDULE_SECONDS[-1]

# Failures older than this are forgotten — an occasional typo over weeks
# must never accumulate into a delay.
_WINDOW_SECONDS = 15 * 60

# In-process, keyed by the credential under attack rather than by source
# address, so cycling IPs buys an attacker nothing. Single-entry today
# (this app has exactly one child credential) but keyed for clarity and so
# a future per-student PIN doesn't need this rewritten.
#
# REPLICATION: in-process means per-replica. Under N replicas the free
# allowance effectively becomes 3*N and an attacker spreading guesses
# across pods resets the escalation, which defeats the point of this
# module. Correct for both topologies Bede actually supports today (see
# docs/DEPLOYMENT_TOPOLOGY.md — a single-instance self-hosted deployment or
# the single-instance demo), and a landmine for anyone who scales it
# without moving this to a shared store first. Tracked there rather than
# left implicit, because it fails silently: the throttle still appears to
# work, just N times weaker.
_KEY = "child_pin"
_failures: dict[str, tuple[int, float]] = {}


def _current(key: str, now: float) -> int:
    count, last = _failures.get(key, (0, 0.0))
    if count and (now - last) > _WINDOW_SECONDS:
        return 0
    return count


def _delay_for_count(count: int) -> float:
    """Delay owed for the `count`-th consecutive failure (1-based)."""
    beyond_free = count - _FREE_ATTEMPTS
    if beyond_free <= 0:
        return 0.0
    return _DELAY_SCHEDULE_SECONDS[min(beyond_free - 1, len(_DELAY_SCHEDULE_SECONDS) - 1)]


def delay_for_next_attempt(key: str = _KEY) -> float:
    """Seconds a failed attempt should be held before responding.

    Pure read — no mutation, so a caller can decide whether to apply it
    without affecting the count. Returns 0.0 while within the free
    allowance."""
    return _delay_for_count(_current(key, time.monotonic()) + 1)


def record_failure(key: str = _KEY) -> float:
    """Count a wrong PIN. Returns the delay to apply before responding."""
    now = time.monotonic()
    count = _current(key, now) + 1
    _failures[key] = (count, now)
    return _delay_for_count(count)


def record_success(key: str = _KEY) -> None:
    """A correct PIN clears the count — the prior failures weren't an
    attack, or are no longer one."""
    _failures.pop(key, None)


def reset(key: str | None = None) -> None:
    """Clear throttle state. For tests, and for a parent changing the PIN
    (the credential being attacked no longer exists, so its accumulated
    delay shouldn't carry over to the new one)."""
    if key is None:
        _failures.clear()
    else:
        _failures.pop(key, None)
