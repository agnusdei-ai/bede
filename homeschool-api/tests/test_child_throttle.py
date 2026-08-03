"""
Child-PIN brute-force throttling (punch-list #7).

The property under test is not just "guessing gets slower" — it's that
slowing guessing did NOT hand anyone a way to deny a child their own
session. See core/child_throttle.py's docstring and
docs/THREAT_MODEL.md's "self-defeating mechanisms" note for why a
fixed-threshold lockout (the pattern core/parent_lockout.py uses) would
have been the wrong shape here.
"""
import pytest

from core import child_throttle


@pytest.fixture(autouse=True)
def _clean():
    child_throttle.reset()
    yield
    child_throttle.reset()


# ── The honest-mistake path must be invisible ───────────────────────────────

def test_first_attempts_are_free():
    """A child mistyping their own PIN a couple of times must notice
    nothing at all."""
    for _ in range(child_throttle._FREE_ATTEMPTS):
        assert child_throttle.record_failure() == 0.0


def test_delay_only_starts_after_the_free_allowance():
    for _ in range(child_throttle._FREE_ATTEMPTS):
        child_throttle.record_failure()
    assert child_throttle.record_failure() > 0.0


def test_success_clears_accumulated_failures():
    for _ in range(6):
        child_throttle.record_failure()
    assert child_throttle.delay_for_next_attempt() > 0.0
    child_throttle.record_success()
    assert child_throttle.delay_for_next_attempt() == 0.0


def test_stale_failures_are_forgotten(monkeypatch):
    """An occasional typo over weeks must never accumulate into a delay."""
    fake = [1000.0]
    monkeypatch.setattr(child_throttle.time, "monotonic", lambda: fake[0])

    for _ in range(6):
        child_throttle.record_failure()
    assert child_throttle.delay_for_next_attempt() > 0.0

    fake[0] += child_throttle._WINDOW_SECONDS + 1
    assert child_throttle.delay_for_next_attempt() == 0.0
    assert child_throttle.record_failure() == 0.0


# ── Escalation ──────────────────────────────────────────────────────────────

def test_delay_escalates_then_caps():
    delays = [child_throttle.record_failure() for _ in range(20)]
    escalating = [d for d in delays if d > 0]
    assert escalating == sorted(escalating), "delay must never decrease"
    assert max(delays) == child_throttle._MAX_DELAY_SECONDS
    assert delays[-1] == child_throttle._MAX_DELAY_SECONDS


def test_sustained_guessing_becomes_expensive():
    """The actual defensive claim: at the capped delay, exhausting a
    6-digit keyspace is infeasible even with unlimited source addresses."""
    for _ in range(20):
        child_throttle.record_failure()
    per_guess = child_throttle.delay_for_next_attempt()
    keyspace = 10 ** 6
    assert per_guess * keyspace / 86400 > 30, "should exceed a month of continuous guessing"


# ── The property that makes this NOT a lockout ──────────────────────────────

def test_throttling_never_refuses_a_correct_pin():
    """The whole point. However many failures accumulate, a correct PIN
    still authenticates — there is no state an attacker can push the child
    role into that requires a parent to clear it, which is exactly what a
    fixed-threshold lockout would have created."""
    for _ in range(500):
        child_throttle.record_failure()
    # Delay is capped, and success is still success.
    assert child_throttle.delay_for_next_attempt() == child_throttle._MAX_DELAY_SECONDS
    child_throttle.record_success()
    assert child_throttle.delay_for_next_attempt() == 0.0


def test_delay_is_bounded_so_it_cannot_become_a_hang():
    """An unbounded backoff would be its own denial of service — a child
    made to wait minutes is locked out in practice even if the code never
    says 'locked'."""
    for _ in range(10_000):
        child_throttle.record_failure()
    assert child_throttle.delay_for_next_attempt() <= child_throttle._MAX_DELAY_SECONDS


# ── Keying ──────────────────────────────────────────────────────────────────

def test_state_is_keyed_on_the_credential_not_the_source_address():
    """Keying on the credential is what makes IP rotation — trivial on a
    LAN, and the reason the per-IP rate limiter alone is insufficient —
    buy an attacker nothing."""
    for _ in range(6):
        child_throttle.record_failure()
    assert child_throttle.delay_for_next_attempt() > 0.0
    # A different credential key is unaffected.
    assert child_throttle.delay_for_next_attempt("some_other_pin") == 0.0


def test_reset_clears_one_key_or_all():
    child_throttle.record_failure("a")
    child_throttle.record_failure("b")
    child_throttle.reset("a")
    assert child_throttle._current("a", 0.0) == 0
    assert child_throttle._current("b", child_throttle.time.monotonic()) == 1
    child_throttle.reset()
    assert child_throttle._failures == {}


# ── Performance ─────────────────────────────────────────────────────────────

def test_read_path_is_cheap():
    """This runs on the family's own hardware and a child logs in every
    school morning. Deliberately in-process rather than DB-backed like
    parent_lockout — assert it stays that way."""
    import time as _t
    child_throttle.reset()
    N = 100_000
    t0 = _t.perf_counter()
    for _ in range(N):
        child_throttle.delay_for_next_attempt()
    per_call_us = (_t.perf_counter() - t0) / N * 1e6
    assert per_call_us < 5.0, f"{per_call_us:.2f} us/call — should be a dict lookup"
