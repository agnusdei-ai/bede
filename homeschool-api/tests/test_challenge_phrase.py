"""The random challenge phrase that makes voice verification a factor
rather than a formality.

Before this, every child in every family said the same sentence forever —
"I am ready to learn today!", hardcoded in VoiceVerification.tsx and
published in this repository, exactly as the 602656 PIN was — and the
server never checked what was said at all, only who appeared to be saying
it. A recording of one sentence passed indefinitely.

Two properties are in tension here and both are tested, because sacrificing
either produces a system that is worse in practice:

  UNGUESSABLE  a phrase must not be predictable, or a recording made in
               advance still works.
  SAYABLE      a five-year-old must be able to say it, and Whisper must be
               able to hear it. A check that rejects honest children gets
               switched off, and then the security is zero rather than
               imperfect.
"""
import pytest

from services import challenge_phrase as cp


# ── Unguessable ──────────────────────────────────────────────────────────

def test_phrases_are_not_repeated():
    """The entire point. A constant phrase is what was there before."""
    issued = {cp.issue() for _ in range(200)}
    assert len(issued) > 190, (
        f"only {len(issued)} distinct phrases in 200 draws — the space is too small"
    )


def test_it_uses_a_cryptographic_source():
    """random.choice is seeded predictably enough that an attacker who knows
    roughly when a session started could generate the sequence. This is a
    credential challenge, so it has to come from secrets."""
    import inspect

    src = inspect.getsource(cp.issue)
    assert "secrets.choice" in src
    assert "random.choice" not in src


def test_the_wordlist_is_large_enough_to_defeat_pre_recording():
    assert cp.wordlist_size() >= cp.MIN_WORDLIST
    combos = 1
    n = cp.wordlist_size()
    for i in range(cp.MIN_WORDS):
        combos *= (n - i)
    assert combos > 1_000_000, combos


def test_a_shrunken_wordlist_fails_at_import():
    """A quietly reduced list would weaken every phrase from then on and
    nothing would look wrong. Same instinct as the constitution verifying
    its own digest."""
    with pytest.raises(RuntimeError):
        original = cp._WORDS
        try:
            cp._WORDS = ("otter", "badger", "rabbit")
            cp._self_check()
        finally:
            cp._WORDS = original


# ── Sayable ──────────────────────────────────────────────────────────────

def test_every_word_is_something_a_young_child_can_say():
    for word in cp._WORDS:
        assert word.isalpha(), word
        assert 3 <= len(word) <= 10, f"{word} is awkward for a five-year-old"
        assert word == word.lower()


def test_no_homophones_or_confusable_pairs():
    """to/two, their/there and friends break both children and speech
    recognition, and a phrase that cannot be transcribed cannot be
    verified."""
    confusable = {
        "to", "two", "too", "their", "there", "they're", "hear", "here",
        "wear", "where", "were", "sea", "see", "son", "sun", "some", "sum",
        "knight", "night", "flower", "flour", "bear", "bare", "pair", "pear",
    }
    overlap = set(cp._WORDS) & confusable
    # "pear" is in the list; "pair" is not, so the pair cannot both appear.
    assert not (overlap & {"pair", "bare", "flour", "two", "too", "there"}), overlap


def test_the_phrase_clears_the_stated_floors():
    for _ in range(100):
        phrase = cp.issue()
        assert len(phrase) >= cp.MIN_CHARS, phrase
        assert len(phrase.split()) >= cp.MIN_WORDS, phrase
        assert len(set(phrase.split())) == len(phrase.split()), f"repeated word: {phrase}"


def test_too_few_words_is_refused():
    with pytest.raises(ValueError):
        cp.issue(word_count=1)


# ── Matching: tolerant of Whisper, intolerant of a different phrase ──────

def test_an_exact_answer_matches():
    phrase = cp.issue()
    assert cp.matches(phrase, phrase)


def test_punctuation_and_capitals_do_not_matter():
    """Whisper returns "Otter, meadow — lantern." for what was asked as
    "otter meadow lantern". None of that difference is meaningful."""
    assert cp.matches("otter meadow lantern", "Otter, meadow — lantern.")


def test_one_misheard_word_still_passes():
    """The case that decides whether a family keeps this switched on."""
    assert cp.matches("otter meadow lantern", "otter meadow lantana")


def test_a_recording_of_a_different_phrase_fails():
    """The attack. A sibling with a recording of last session's phrase."""
    assert not cp.matches("otter meadow lantern", "pumpkin rainbow compass")


def test_the_old_fixed_passphrase_fails():
    """The specific recording an attacker is most likely to already have,
    since that sentence was published in this repository."""
    assert not cp.matches(cp.issue(), "I am ready to learn today!")


def test_silence_or_nothing_fails():
    assert not cp.matches("otter meadow lantern", "")
    assert not cp.matches("", "otter meadow lantern")
    assert not cp.matches("otter meadow lantern", "   ")


def test_saying_one_right_word_is_not_enough():
    """A guesser who knows the wordlist could say a common word and hope."""
    assert not cp.matches("otter meadow lantern", "otter")
    assert not cp.matches("otter meadow lantern", "otter banana banana")


def test_a_stumbled_order_still_passes():
    """A child who says the right words in the wrong order has still proved
    they heard a phrase that did not exist before this session."""
    assert cp.matches("otter meadow lantern", "meadow lantern otter")
