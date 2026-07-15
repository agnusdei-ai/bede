"""
Catholic poetry co-study catalog — public-domain poems and hymn-texts with
their EXACT wording, so Bede quotes and teaches recitation verbatim from a
verified source instead of reciting from model memory (models can misquote
long passages, and recitation/copywork requires exact lines). Each entry's
wording was cross-checked against a named published source before being
hardcoded here (see PR history for the specific sources checked); short
excerpts were chosen over full long-form works wherever a complete text
could not be verified with confidence.

Rotation is WEEKLY and computed automatically from the calendar (ISO week
number) rather than from a parent-set field. The prior design (one poet
per school TERM, keyed to SessionConfig.current_term) depended on a parent
manually advancing a dropdown in ParentSetup.tsx that nothing ever
prompted them to update — in practice current_term silently stayed at its
default of 1 for most sessions, which is exactly what made the public
demo's poetry permanently stuck on a single poet (see routers/tutor.py's
_demo_current_term for that fix). A calendar-derived week sidesteps the
whole failure mode: it advances on its own, for every family and every
demo visitor, with nothing to configure or forget.

Each entry is tagged with the specific grade(s) it fits ("K" through "8"),
not just a broad GradeStage band — a kindergartner and a 2nd grader are
both "foundations," but a poem's vocabulary/length that lands for one can
miss for the other. GradeStage is derived automatically from that grade
set (never hand-maintained separately, so the two can't drift apart) and
kept only as a fallback for the rare case a caller has a stage but no
specific grade (e.g. an unset/guest session). Poems for a given grade (or
stage, in the fallback path) are filtered first, then indexed by week, so
each grade/stage cycles through its own (independently sized) list at its
own pace — a poem may repeat more than once across a school year, which
is fine, even desirable, for a memory-work habit (see poetry_note's
teaching guidance below).
"""
from datetime import date

from models.schemas import GradeStage, VALID_GRADES, grade_to_stage


def _entry(title: str, poet: str, source: str, grades: set, text: str) -> dict:
    return {
        "title": title,
        "poet": poet,
        "source": source,
        "grades": grades,
        "stages": {grade_to_stage(g) for g in grades},
        "text": text,
    }


_COLLECTION = [
    _entry(
        "Angel of God", "Traditional (trad. attrib. St. Anselm of Canterbury)",
        "USCCB, \"Prayer to Your Guardian Angel\"", {"K", "1", "2", "3"}, (
            "Angel of God, my guardian dear,\n"
            "To whom God's love commits me here,\n"
            "Ever this day be at my side,\n"
            "To light and guard, to rule and guide. Amen."
        ),
    ),
    _entry(
        "Canticle of the Sun (Brother Sun)", "St. Francis of Assisi (tr. Matthew Arnold)",
        "Matthew Arnold's translation, as printed in Albert E. Bailey's The Gospel in Hymns", {"K", "1", "2", "3", "4"}, (
            "Praised be my Lord God with all his creatures;\n"
            "and specially our brother the sun,\n"
            "who brings us the day, and who brings us the light;\n"
            "fair is he, and shining with a very great splendour:\n"
            "O Lord, to us he signifies Thee!"
        ),
    ),
    _entry(
        "Loving Shepherd of Thy Sheep", "Jane E. Leeson",
        "Infant Hymnings (1842)", {"K", "1", "2", "3"}, (
            "Loving Shepherd of Thy sheep,\n"
            "Keep Thy lamb, in safety keep;\n"
            "Nothing can Thy power withstand,\n"
            "None can pluck me from Thy hand.\n"
            "\n"
            "Loving Shepherd, ever near,\n"
            "Teach Thy lamb Thy voice to hear,\n"
            "Suffer not my steps to stray\n"
            "From the straight and narrow way."
        ),
    ),
    _entry(
        "Christ Be With Me", "St. Patrick's Breastplate (tr. Cecil Frances Alexander, 1889)",
        "\"I Bind Unto Myself Today\", verse translation of the Lorica", {"2", "3", "4", "5", "6"}, (
            "Christ be with me, Christ within me,\n"
            "Christ behind me, Christ before me,\n"
            "Christ beside me, Christ to win me,\n"
            "Christ to comfort and restore me,\n"
            "Christ beneath me, Christ above me,\n"
            "Christ in quiet, Christ in danger,\n"
            "Christ in hearts of all that love me,\n"
            "Christ in mouth of friend and stranger."
        ),
    ),
    _entry(
        "Lead, Kindly Light", "St. John Henry Newman",
        "Lyra Apostolica (1836), first stanza", {"4", "5", "6", "7", "8"}, (
            "Lead, Kindly Light, amid the encircling gloom,\n"
            "Lead Thou me on;\n"
            "The night is dark, and I am far from home,\n"
            "Lead Thou me on.\n"
            "Keep Thou my feet; I do not ask to see\n"
            "The distant scene; one step enough for me."
        ),
    ),
    _entry(
        "The Donkey", "G.K. Chesterton",
        "The Wild Knight and Other Poems (1900)", {"5", "6", "7", "8"}, (
            "When fishes flew and forests walked\n"
            "And figs grew upon thorn,\n"
            "Some moment when the moon was blood,\n"
            "Then surely I was born;\n"
            "With monstrous head and sickening cry\n"
            "And ears like errant wings,\n"
            "The devil's walking parody\n"
            "On all four-footed things.\n"
            "\n"
            "The tattered outlaw of the earth,\n"
            "Of ancient crooked will;\n"
            "Starve, scourge, deride me: I am dumb,\n"
            "I keep my secret still.\n"
            "\n"
            "Fools! For I also had my hour;\n"
            "One far fierce hour and sweet:\n"
            "There was a shout about my ears,\n"
            "And palms before my feet."
        ),
    ),
    _entry(
        "Pied Beauty", "Gerard Manley Hopkins, S.J.",
        "Poems (1918, posthumous)", {"7", "8"}, (
            "Glory be to God for dappled things—\n"
            "   For skies of couple-colour as a brinded cow;\n"
            "      For rose-moles all in stipple upon trout that swim;\n"
            "Fresh-firecoal chestnut-falls; finches' wings;\n"
            "   Landscape plotted and pieced—fold, fallow, and plough;\n"
            "      And áll trádes, their gear and tackle and trim.\n"
            "\n"
            "All things counter, original, spare, strange;\n"
            "   Whatever is fickle, freckled (who knows how?)\n"
            "      With swift, slow; sweet, sour; adazzle, dim;\n"
            "He fathers-forth whose beauty is past change:\n"
            "                                Praise him."
        ),
    ),
]


def _entries_for_grade(grade: str) -> list[dict]:
    return [e for e in _COLLECTION if grade in e["grades"]]


def _entries_for_stage(stage: GradeStage) -> list[dict]:
    return [e for e in _COLLECTION if stage in e["stages"]]


def _entries_for(grade: "str | None", stage: GradeStage) -> list[dict]:
    """Grade-specific entries when the exact grade is known and recognized
    (VALID_GRADES), otherwise the broader stage band — covers sessions
    that only have a stage (e.g. an unset/guest config)."""
    if grade and grade.strip().upper() in VALID_GRADES:
        entries = _entries_for_grade(grade.strip().upper())
        if entries:
            return entries
    return _entries_for_stage(stage)


def current_week(today: "date | None" = None) -> int:
    """1-based ISO week number. Computed fresh from the calendar every
    call — no stored state to drift, no field for a parent to forget."""
    return (today or date.today()).isocalendar()[1]


def poem_for_week(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> "dict | None":
    """
    The grade-filtered (falling back to stage-filtered) entry for the
    current calendar week. week_salt offsets the index — ai_service.py
    passes the session's current_term (already unique-per-demo-code, see
    routers/tutor.py's _demo_current_term) so different families/demo
    visitors don't all land on the identical poem in the same calendar
    week, without this module needing to know anything about demo codes
    itself.

    Returns None only if both the grade and stage lists are empty (not
    true of the current collection, but keeps this honest if a future
    edit narrows one to nothing).
    """
    entries = _entries_for(grade, stage)
    if not entries:
        return None
    idx = (current_week(today) + week_salt - 1) % len(entries)
    return entries[idx]


def poetry_note(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> str:
    """Prompt block for poetry co-study in morning_time / living_books:
    this week's poem, given VERBATIM, and how to teach it the Mater
    Amabilis way (co-study and gentle recitation, never a quiz)."""
    entry = poem_for_week(grade, stage, week_salt, today)
    if not entry:
        return ""
    return f"""

<poetry_co_study>
This week's poem is "{entry['title']}" by {entry['poet']} ({entry['source']}) — part of a
weekly rotation of Catholic verse and hymn-texts, per Mater Amabilis practice of a steady
poetry habit. The text below is given VERBATIM. When you read, quote, or teach any line of
this poem, use EXACTLY the text below — never recite it from memory and never paraphrase a
line you present as the poem itself.

{entry['text']}

How to co-study a poem (a few minutes, woven in where it fits — not a lecture):
read a stanza aloud together, wonder about one image in it ("What do you see when he says...?"),
let the child echo a favorite line, and connect it to the child's own day where that happens
naturally. Over several sessions, gently build toward the child saying a whole poem from memory —
one or two lines at a time, always as delight, never as a quiz. A recited line is a fine thing to
celebrate.
</poetry_co_study>"""
