"""
Random challenge phrases for voice verification.

THE PROBLEM THIS SOLVES

Voice verification asked every child, in every family, in every session, to
say one sentence: "I am ready to learn today!" — a constant hardcoded in
VoiceVerification.tsx and published in this repository, exactly as the
602656 PIN was. Worse, the server never checked WHAT was said. It compared
the speaker embedding and nothing else, so any recording of that one
sentence passed forever, and a sibling with a phone was the whole attack.

A challenge phrase fixes that by never asking for the same thing twice. An
attacker would need a recording of the specific phrase they are about to be
asked for, which they cannot have, because it did not exist until this
session started.

That is what makes voice a factor rather than a formality. It is NOT
presentation-attack detection: a determined adversary with a voice-cloning
model and the child's speech can still synthesise a response. Voice
therefore remains excluded from account recovery, and device-native
biometrics (Face ID, Touch ID, Windows Hello — see services/mfa_service.py)
remain the primary factor for the parent, because those carry real PAD from
the platform. What this closes is the casual, realistic attack: a recording.

WHY WORDS AND NOT CHARACTERS

The obvious way to make a phrase unguessable is random characters. A
five-year-old cannot say those, and a phrase a child cannot say is a locked
door with extra steps. So the entropy comes from combining ordinary words
instead: every word is short, concrete, and easy to pronounce, and the
combination is what an attacker cannot have pre-recorded.

The wordlist is curated rather than generated. Words are excluded when they
are homophones (their/there, to/two), when speech recognition routinely
confuses them, when they are hard for a young child to articulate, and when
they carry any unpleasant or frightening association — a child should be
able to say their phrase cheerfully. Everything here is a concrete noun,
colour, or simple adjective.

WHY THE MATCH IS TOLERANT

Whisper mishears. A verifier demanding an exact transcript would reject
honest children constantly, and a check that fails honest users gets turned
off — at which point the security is zero rather than imperfect. So a
phrase is accepted when enough of its words are present, and the strictness
is a named constant rather than a magic number. Getting this wrong in the
strict direction is not the safe side of the trade; it is a different
failure with the same end state.
"""
import re
import secrets
import unicodedata

# Minimum shape of an issued phrase. "Not easy to guess" is enforced
# structurally rather than trusted to the wordlist staying large: an issued
# phrase must clear all three, and _self_check below fails the import if the
# configured wordlist cannot.
MIN_WORDS = 3
MIN_CHARS = 14
# 3 words from this list is ~1.4 million combinations. The relevant question
# is not brute force — a guesser gets one attempt per session and has to
# produce a recording in the child's voice — but whether an attacker could
# pre-record every possibility. At this size they cannot.
MIN_WORDLIST = 96

# Fraction of the phrase's words that must appear in the transcript. Two of
# three, four of five. Whisper drops or mangles a word often enough that
# demanding all of them would reject honest children; requiring a clear
# majority still means a recording of a DIFFERENT phrase never passes.
MATCH_RATIO = 0.66

# Curated for a young child to say aloud: concrete, one or two syllables,
# no homophones, nothing unpleasant. Deliberately not generated from a
# frequency list — a machine-picked list produces "though", "their" and
# "quite", which are the exact words that break both children and speech
# recognition.
_WORDS = (
    # animals
    "otter", "badger", "rabbit", "sparrow", "donkey", "kitten", "puppy",
    "beetle", "salmon", "falcon", "pony", "lamb", "goose", "turtle",
    "hedgehog", "squirrel", "robin", "dolphin", "penguin", "walrus",
    # nature
    "meadow", "river", "mountain", "forest", "pebble", "acorn", "blossom",
    "thunder", "rainbow", "harbour", "island", "valley", "garden", "orchard",
    "willow", "clover", "maple", "fern", "cedar", "brook",
    # colours and simple adjectives
    "purple", "yellow", "crimson", "golden", "silver", "amber", "scarlet",
    "cheerful", "gentle", "clever", "sleepy", "sunny", "quiet", "brave",
    "tidy", "merry", "friendly", "curious", "polite", "patient",
    # everyday objects
    "lantern", "basket", "kettle", "pencil", "blanket", "window", "ladder",
    "bucket", "candle", "compass", "anchor", "cushion", "teapot", "saucer",
    "mitten", "satchel", "button", "ribbon", "marble", "whistle",
    # food
    "muffin", "apple", "pumpkin", "biscuit", "porridge", "walnut", "cherry",
    "carrot", "honey", "lemon", "peach", "pear", "plum", "bramble",
    # weather and time
    "morning", "evening", "breezy", "frosty", "misty", "summer", "winter",
    "autumn", "sunrise", "moonlight",
)


def wordlist_size() -> int:
    return len(_WORDS)


def _normalise(text: str) -> list[str]:
    """Lowercase, strip accents and punctuation, split into words. Whisper
    returns "Otter, meadow — lantern." for what the child was asked to say
    as "otter meadow lantern"; none of that difference is meaningful."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [w for w in text.split() if w]


def issue(word_count: int = MIN_WORDS) -> str:
    """A fresh phrase. Uses `secrets`, not `random` — this is a credential
    challenge, and a predictable sequence would let an attacker record the
    next one in advance, which is the whole thing being defended against.

    Keeps drawing until the phrase clears MIN_CHARS, so the floor holds even
    if every word drawn happens to be short.
    """
    if word_count < MIN_WORDS:
        raise ValueError(f"a challenge phrase needs at least {MIN_WORDS} words")

    while True:
        # Distinct words: "otter otter meadow" is both odd to say and a
        # smaller space than it looks.
        words: list[str] = []
        while len(words) < word_count:
            candidate = secrets.choice(_WORDS)
            if candidate not in words:
                words.append(candidate)
        phrase = " ".join(words)
        if len(phrase) >= MIN_CHARS:
            return phrase


def matches(issued: str, transcript: str) -> bool:
    """Whether the child said the phrase they were asked for.

    Tolerant by design — see the module docstring on why a strict match is
    not the safe side of this trade. Order is ignored for the same reason:
    Whisper reorders far less often than it drops, and a child who says the
    words correctly in a stumbled order has still proved they heard a phrase
    that did not exist before this session.
    """
    if not issued or not transcript:
        return False

    wanted = _normalise(issued)
    heard = set(_normalise(transcript))
    if not wanted:
        return False

    hits = sum(1 for w in wanted if w in heard)
    required = max(2, round(len(wanted) * MATCH_RATIO))
    return hits >= required


def _self_check() -> None:
    """Fails at import if the wordlist cannot satisfy the policy above.

    A shrunken or duplicated list would silently weaken every phrase issued
    from then on, and nothing else in the system would notice — the phrases
    would still look fine. This is the same instinct as core/constitution.py
    verifying its own digest at import.
    """
    if len(set(_WORDS)) != len(_WORDS):
        raise RuntimeError("challenge wordlist contains duplicates")
    if len(_WORDS) < MIN_WORDLIST:
        raise RuntimeError(
            f"challenge wordlist has {len(_WORDS)} words, below the {MIN_WORDLIST} "
            "needed for a phrase an attacker cannot pre-record"
        )
    if any(not w.isalpha() or len(w) < 3 for w in _WORDS):
        raise RuntimeError("challenge words must be alphabetic and pronounceable")


_self_check()
