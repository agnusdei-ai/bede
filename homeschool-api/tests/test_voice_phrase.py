"""The phrase a child says to prove they are themselves.

Before this, every child in every family said one sentence — "I am ready to
learn today!", hardcoded in VoiceVerification.tsx and published in this
repository exactly as the 602656 PIN was — and the server never checked
what was said at all, only who appeared to be saying it. A recording of one
published sentence passed indefinitely.

The family now chooses the phrase and the child says it from memory. Three
properties are in tension, and all three are tested, because sacrificing
any one of them produces something worse in practice:

  KNOWN     the child must recall it unprompted, or it is a script rather
            than a factor and the only secret left is the voice.
  SAYABLE   a five-year-old must manage it, and Whisper must hear it. A
            check that rejects honest children gets switched off, and then
            the security is zero rather than imperfect.
  THEIRS    a phrase this repository prints is not a secret, whoever says
            it.
"""
import pytest

from services import voice_phrase as vp


# ── Theirs: the published default must be impossible to keep ─────────────

def test_the_old_published_passphrase_is_refused():
    """The specific sentence every existing deployment is using, and the one
    an attacker is most likely to already have a recording of."""
    assert vp.check_phrase("I am ready to learn today!")
    assert "public" in vp.check_phrase("I am ready to learn today!")


def test_punctuation_does_not_smuggle_the_retired_phrase_back():
    for variant in [
        "i am ready to learn today",
        "I AM READY TO LEARN TODAY!!!",
        "I am, ready to learn today.",
    ]:
        assert vp.check_phrase(variant), variant


# ── Sayable: the floors, and that the suggestions clear them ─────────────

def test_a_phrase_must_be_long_enough_to_match_reliably():
    assert vp.check_phrase("up")
    assert vp.check_phrase("go now")
    assert "4 words" in vp.check_phrase("one two three")


def test_a_phrase_must_be_short_enough_to_remember():
    assert vp.check_phrase("word " * 40)


def test_the_same_word_repeated_is_refused():
    assert vp.check_phrase("apple apple apple apple apple")


@pytest.mark.parametrize("suggestion", vp.SUGGESTIONS)
def test_every_suggestion_is_actually_acceptable(suggestion):
    """Offering a family a phrase the form then rejects is the exact defect
    core/pin_policy.py exists to record, one screen over. _self_check also
    fails the import, so this is belt and braces on purpose."""
    assert vp.check_phrase(suggestion) == "", suggestion


def test_a_family_can_use_something_of_their_own():
    """Nursery rhymes are a starting point, not a menu. A line from the book
    they are reading has to work too."""
    assert vp.check_phrase("the wind in the willows by the river bank") == ""
    assert vp.check_phrase("grandpa always says mind the step") == ""


# ── Known: matching is tolerant of a child, not of a stranger ────────────

def test_saying_it_correctly_passes():
    phrase = "Hey diddle diddle the cat and the fiddle"
    assert vp.matches(phrase, phrase)


def test_whisper_punctuation_and_capitals_do_not_matter():
    assert vp.matches(
        "Hey diddle diddle the cat and the fiddle",
        "Hey, diddle diddle — the cat and the fiddle.",
    )


def test_a_misheard_word_still_passes():
    """The case that decides whether a family keeps this switched on."""
    assert vp.matches(
        "Hey diddle diddle the cat and the fiddle",
        "hey diddle diddle the cat and the fiddler",
    )


def test_a_stumbled_order_still_passes():
    assert vp.matches(
        "Hey diddle diddle the cat and the fiddle",
        "the cat and the fiddle hey diddle diddle",
    )


def test_a_different_rhyme_fails():
    """Someone who guesses the family picked a nursery rhyme, but the wrong
    one."""
    assert not vp.matches(
        "Hey diddle diddle the cat and the fiddle",
        "Twinkle twinkle little star how I wonder what you are",
    )


def test_the_retired_phrase_never_satisfies_a_chosen_one():
    """A recording made before the family chose their own phrase."""
    assert not vp.matches(
        "Hey diddle diddle the cat and the fiddle",
        "I am ready to learn today",
    )


def test_a_couple_of_shared_words_are_not_enough():
    """Two phrases both containing "the" and "and" must not cross-match."""
    assert not vp.matches(
        "Hey diddle diddle the cat and the fiddle",
        "the dog and the bone",
    )


def test_silence_fails():
    assert not vp.matches("Hey diddle diddle the cat and the fiddle", "")
    assert not vp.matches("Hey diddle diddle the cat and the fiddle", "   ")
    assert not vp.matches("", "anything at all here")


def test_a_short_phrase_still_needs_three_words_heard():
    """MATCH_RATIO alone would let a 4-word phrase pass on 3 words; the
    floor of 3 is what stops one passing on 2."""
    assert not vp.matches("mind the garden step", "mind the")
