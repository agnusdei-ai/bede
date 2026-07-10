"""
PIN strength policy — pure standard library, no pydantic/other dependencies.

Split out from core/config.py specifically so anything that needs the exact
same rule (like scripts/setup_wizard/wizard.py, which runs in its own
minimal container and shouldn't need to pull in pydantic just to validate a
PIN) can import this one file directly instead of re-implementing the logic
a third time in Python (bash and TypeScript already have their own
necessarily-separate copies — see setup.sh and demo/src/App.tsx).
"""

MIN_PIN_LENGTH = 6


def _is_sequential(pin: str) -> bool:
    """True if every digit steps by the same +1/-1 from the last, mod 10 —
    catches not just 123456/654321 but wraparound runs like 789012/901234
    that a naive non-modular check would miss."""
    diffs = {(int(b) - int(a)) % 10 for a, b in zip(pin, pin[1:])}
    return diffs in ({1}, {9})


def _is_repeating_block(pin: str) -> bool:
    """True if the whole PIN is one short block repeated to fill the length —
    catches 111111 (block "1"), 123123 (block "123"), 121212 (block "12")."""
    n = len(pin)
    for block_len in range(1, n // 2 + 1):
        if n % block_len == 0:
            block = pin[:block_len]
            if block * (n // block_len) == pin:
                return True
    return False


def _is_palindrome(pin: str) -> bool:
    """True if the PIN reads the same forwards and backwards — catches
    symmetric patterns like 669966 that _is_repeating_block misses (it's
    not a repeated block, but it's still an obviously guessable shape)."""
    return pin == pin[::-1]


def pin_is_strong(pin: str) -> bool:
    """At least 6 digits, not a simple sequential run (ascending or
    descending, wraparound included), not a repeated-block pattern, and not
    a palindrome. Repeated digits are otherwise fine — e.g. 602656 is a
    perfectly good PIN — only easily-guessable *patterns* are rejected."""
    return (
        pin.isdigit()
        and len(pin) >= MIN_PIN_LENGTH
        and not _is_sequential(pin)
        and not _is_repeating_block(pin)
        and not _is_palindrome(pin)
    )
