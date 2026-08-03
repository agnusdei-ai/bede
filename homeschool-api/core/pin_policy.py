"""
Credential policy — pure standard library, no pydantic/other dependencies.

Split out from core/config.py specifically so anything that needs the exact
same rule (like scripts/setup_wizard/wizard.py, which runs in its own
minimal container and shouldn't need to pull in pydantic just to validate a
PIN) can import this one file directly instead of re-implementing the logic
a third time in Python (bash and TypeScript already have their own
necessarily-separate copies — see setup.sh and demo/src/App.tsx).

Two rules live here, and the second is the reason the first was not enough.

`pin_is_strong` is about the SHAPE of a PIN. `is_published_credential` is
about whether the exact value has been printed somewhere public, which is a
different question with a different answer: 602656 is a perfectly
well-shaped PIN and passes every check below, but it was this repository's
recommended example for a long time — in .env.example, in setup.sh, in the
setup wizard's own hint text, in docs, and in the error messages that told
a parent what a good PIN looks like. A value published on GitHub is not a
secret, whatever its shape.

Both rules have to live in ONE place because two different programs enforce
them at two different moments: the setup wizard when a parent types a value,
and core/config.py when the API boots. When those disagreed, the wizard
accepted a PIN it had just recommended on screen and the container then
refused to start, telling the parent their PIN was "the default dev value."
Nothing was flaky about that. It was two copies of one policy, and only one
of them had been updated.
"""

MIN_PIN_LENGTH = 6

# Values this repository has published as examples. They are rejected as
# real credentials no matter how well-formed they are, because anyone can
# read them here. Add to this set whenever a concrete credential is printed
# somewhere public — and prefer not printing one at all, which is why the
# wizard now suggests a freshly generated PIN instead of naming a literal.
PUBLISHED_EXAMPLE_PINS = frozenset({"602656"})

# The placeholder secrets shipped in .env.example and used as code defaults.
# Same reasoning as the PINs: a hand-copied .env that never touched the line
# would otherwise boot in production on a value published in this repo.
WEAK_PLACEHOLDER_SECRETS = frozenset({
    "dev-secret-CHANGE-IN-PRODUCTION-must-be-32-chars-min",
    "change-me-parent",
    "change-me-master-secret-32-chars-min",
    "0000",
})


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
    a palindrome. Repeated digits are otherwise fine — only easily-guessable
    *patterns* are rejected.

    Deliberately says nothing about whether the value has been published;
    that is is_published_credential's job. A PIN can be well-shaped and
    still be a bad secret, and keeping the two questions separate is what
    lets a published example still serve as a shape example in a test.
    """
    return (
        pin.isdigit()
        and len(pin) >= MIN_PIN_LENGTH
        and not _is_sequential(pin)
        and not _is_repeating_block(pin)
        and not _is_palindrome(pin)
    )


def is_published_credential(value: str) -> bool:
    """True for any value this repository prints publicly as an example.
    Checked in addition to shape, never instead of it."""
    return value in PUBLISHED_EXAMPLE_PINS or value in WEAK_PLACEHOLDER_SECRETS


def suggest_pin() -> str:
    """A freshly generated, policy-passing PIN for TESTS AND CI, which need
    one without committing a literal to this repository.

    Deliberately NOT used by either installer, and it should not become so.
    Generating a PIN for a parent would solve the secrecy problem that
    retired 602656 and introduce a worse one: a child has to recall this
    PIN from memory at the login screen, possibly aged five, and a random
    six-digit number is close to the worst thing to hand them. Any value
    already on screen also invites a parent to accept it rather than
    decide. Both installers state the rules and check the answer instead.

    Uses `secrets` rather than `random` because these values do end up in a
    real (if throwaway) .env during a CI run.
    """
    import secrets

    while True:
        pin = "".join(secrets.choice("0123456789") for _ in range(MIN_PIN_LENGTH))
        if pin_is_strong(pin) and not is_published_credential(pin):
            return pin
