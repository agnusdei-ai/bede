"""
The phrase a child says to prove they are themselves.

WHAT WAS THERE BEFORE

One sentence, hardcoded in VoiceVerification.tsx and published in this
repository: "I am ready to learn today!". The same words for every child in
every family forever. And routers/voice.py never checked what was said at
all — it compared the speaker embedding and returned a score — so a
recording of that one published sentence passed indefinitely.

WHAT REPLACES IT, AND WHY THIS SHAPE

The family chooses the phrase, and the child says it FROM MEMORY. Nothing
puts it on screen at verification time, and that omission is the design
rather than an oversight: a phrase displayed to whoever is holding the
tablet is only a script, and the sole secret left is the voice. A phrase
the child recalls is something they KNOW, said in a voice that is something
they ARE. Two factors in one step, and from the child's point of view a
single familiar thing they say every morning.

A machine-generated challenge ("otter meadow lantern", fresh each session)
resists a recording better, because nobody can pre-record a phrase that did
not exist yet. It was built first and then set aside deliberately: it can
only work by being shown on screen, which collapses the know-factor, and it
gives a five-year-old nothing to own. In a house where a sibling hears the
morning routine either way, the family phrase is the better bargain and the
one a child can actually do.

WHY A NURSERY RHYME

Because it is already in the child's head. The suggestions below are lines
old enough to be public domain and common enough that a parent recognises
them instantly — the point is recall, not obscurity. A family is free to
use anything: a line from the book they are reading, a family saying, a
verse.

THE SECRET IS NOT THE RHYME

"Hey diddle diddle" is not secret and is not meant to be. WHICH phrase this
family chose is what an attacker lacks, and they must also produce it in
this child's voice. That is the honest description of the strength here,
and it is why this remains a child-session factor and never a recovery
factor: services/voice_auth.py has no liveness detection, so a recording
made by someone who has heard the morning routine will still pass.
Device-native biometrics (Face ID, Touch ID, Windows Hello) carry real
presentation-attack detection and remain the parent's primary factor.

WRITE IT DOWN ONCE, SOMEWHERE ELSE

A phrase held only in a five-year-old's memory is one bad morning away from
a support call nobody can answer. The enrolment flow asks the parent to
record it outside Bede — an encrypted notes file or a paper notebook — and
to confirm they have. Shown once, confirmed once, never nagged about again,
the same shape as Apple's Recovery Key and as the recovery-PIN checkbox
ParentSecuritySettings.tsx already uses.
"""
import re
import unicodedata

# The floor. Short enough that a young child can hold it, long enough that
# a transcript has something unambiguous to match.
MIN_WORDS = 4
MIN_CHARS = 16
MAX_CHARS = 120

# Fraction of the phrase's words that must appear in the transcript. Whisper
# mishears, and a verifier demanding an exact transcript rejects honest
# children constantly — a check that fails honest users gets switched off,
# at which point the security is zero rather than imperfect. A clear
# majority still means a recording of a DIFFERENT phrase never passes.
MATCH_RATIO = 0.7

# Published in this repository, therefore known to anyone who looks. Same
# reasoning as core/pin_policy.py's PUBLISHED_EXAMPLE_PINS: a value printed
# here stops being a secret the moment it ships, and this one was the
# default for every family that ever installed Bede.
RETIRED_PHRASES = frozenset({
    "i am ready to learn today",
})

# Offered as starting points, never pre-filled. Public-domain lines a parent
# recognises instantly and a child very likely already knows — recall is the
# whole point, so obscurity would be the wrong instinct here. A family that
# picks one of these is fine: an attacker still has to know WHICH, and to
# produce it in this child's voice.
SUGGESTIONS = (
    "Hey diddle diddle the cat and the fiddle",
    "Twinkle twinkle little star how I wonder what you are",
    "Mary had a little lamb its fleece was white as snow",
    "The itsy bitsy spider climbed up the water spout",
    "Hickory dickory dock the mouse ran up the clock",
    "Jack and Jill went up the hill to fetch a pail of water",
    "Row row row your boat gently down the stream",
    "Baa baa black sheep have you any wool",
    "Round and round the garden like a teddy bear",
    "One two buckle my shoe three four knock at the door",
)


def _normalise(text: str) -> list[str]:
    """Lowercase, strip accents and punctuation, split into words. Whisper
    returns "Hey, diddle diddle — the cat and the fiddle." for what a child
    was asked to say plainly; none of that difference is meaningful."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [w for w in text.split() if w]


def check_phrase(phrase: str) -> str:
    """The one place a chosen phrase is judged. Returns an error message a
    parent can act on, or an empty string when the phrase is fine.

    One function, so the enrolment form, its live feedback, and the API all
    reach the same verdict — the lesson core/pin_policy.py exists to record,
    where two copies of one rule disagreed and the installer recommended a
    credential the app then refused to start with.
    """
    if not phrase or not phrase.strip():
        return "Choose a phrase your child already knows by heart."

    words = _normalise(phrase)
    if not words:
        return "Use words your child can say aloud."
    if len(words) < MIN_WORDS:
        return f"A little longer, please: at least {MIN_WORDS} words."
    if len(phrase.strip()) < MIN_CHARS:
        return f"A little longer, please: at least {MIN_CHARS} characters."
    if len(phrase.strip()) > MAX_CHARS:
        return "That is long enough to be hard to remember. One line of it is plenty."
    if " ".join(words) in RETIRED_PHRASES:
        return (
            "That was Bede's own printed example, so it is public. "
            "Choose something of your family's own."
        )
    if len(set(words)) < 3:
        return "Use a few different words rather than the same one repeated."
    return ""


def matches(chosen: str, transcript: str) -> bool:
    """Whether the child said their phrase.

    Tolerant on purpose — see MATCH_RATIO. Order is ignored because Whisper
    drops words far more often than it reorders them, and a child who
    stumbles the order has still recalled a phrase only their family knows.
    """
    if not chosen or not transcript:
        return False

    wanted = _normalise(chosen)
    heard = set(_normalise(transcript))
    if not wanted:
        return False

    hits = sum(1 for w in wanted if w in heard)
    required = max(3, round(len(wanted) * MATCH_RATIO))
    return hits >= required


def _self_check() -> None:
    """Fails at import if a suggestion would be refused by the very policy a
    parent is about to be judged against. Offering a family a phrase the
    form then rejects is precisely the defect core/pin_policy.py exists to
    record, one screen over."""
    for suggestion in SUGGESTIONS:
        problem = check_phrase(suggestion)
        if problem:
            raise RuntimeError(
                f"suggested phrase would be refused: {suggestion!r} — {problem}"
            )


_self_check()
