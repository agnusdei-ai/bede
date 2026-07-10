"""
Regression tests for the PIN strength policy (core/pin_policy.py).

These exact cases were verified by hand across all three implementations
(Python here, bash in setup.sh, TypeScript in demo/src/App.tsx) when the
policy was relaxed from "no repeated digit at all" to "reject only
guessable patterns" — this file is what keeps that verification from
being a one-time thing.
"""
import pytest

from core.pin_policy import pin_is_strong


@pytest.mark.parametrize("pin,expected", [
    ("602656", True),    # repeated digits are fine if not patterned
    ("384756", True),    # the original "good PIN" example
    ("666666", False),   # all one digit
    ("669966", False),   # palindrome
    ("123123", False),   # repeated block
    ("121212", False),   # repeated block
    ("123456", False),   # ascending sequential
    ("654321", False),   # descending sequential
    ("789012", False),   # ascending sequential, wraparound
    ("901234", False),   # ascending sequential, wraparound
    ("111111", False),   # repeated block (and palindrome)
    ("12345", False),    # too short
    ("abcdef", False),   # not digits
])
def test_pin_is_strong(pin, expected):
    assert pin_is_strong(pin) is expected


def test_pin_is_strong_accepts_long_non_pattern_pins():
    assert pin_is_strong("60265789") is True


def test_pin_is_strong_rejects_long_sequential():
    assert pin_is_strong("12345678") is False
