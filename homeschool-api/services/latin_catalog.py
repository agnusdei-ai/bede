"""
Latin & Christian Foundations — the verbatim content behind Subject.latin.

WHAT THIS IS. A K-8 Latin strand whose spine is the shared Christian
vocabulary every Christian tradition holds in common — Fides, Spes,
Caritas, Sapientia, Veritas, Ora et Labora — anchored in the Vulgate, and
centered on Christ's own summary of the whole moral law:

    Diliges Dominum Deum tuum ex toto corde tuo...
    et diliges proximum tuum sicut teipsum.

WHY IT'S BUILT THIS WAY. This app already has two independent faith
modules — Subject.saints (explicitly Catholic, backed by the Ignatius
Press Faith and Life scope in data/catechism/faith_and_life.json) and
Subject.scripture (deliberately denomination-neutral, so a Baptist or
non-denominational family gets a real module of their own rather than a
Catholic one with the labels filed off). Latin sits with `scripture`, not
with `saints`: a family that does not hold the intercession of the saints,
the seven sacraments, transubstantiation, purgatory, or the Marian
dogmas must be able to run this subject start to finish and never be
taught, or asked to assume, any of them. The vocabulary below is chosen on
exactly that test. Ave Maria, Salve Regina, the Sanctus of the Mass, and
the Confiteor are all wonderful Latin and all deliberately absent: each is
either tradition-specific or liturgically situated in a way that would
make this subject quietly Catholic. What IS here — God, Word, light,
peace, grace, faith, hope, love, truth, wisdom, prayer, work, "I believe",
"Amen" — is the common inheritance, and the Vulgate anchors are passages
read as Scripture in every Christian communion.

VERBATIM, NOT RECALLED. Every Latin text below is quoted, never generated.
Same rule and same reason as services/poetry_catalog.py and
services/prayer_catalog.py: a model reciting an inflected language from
memory will sooner or later hand a child a wrong ending, a wrong case, or
a plausible-looking verse that is not what the Vulgate says — and Latin is
worse than English prose here, because a single wrong vowel changes the
grammar rather than just the wording. The prompt block built at the bottom
of this file tells Bede in as many words to use the text below exactly and
never to improvise Latin of its own.

SOURCING. Unlike services/prayer_catalog.py — whose own docstring records
that its texts were transcribed from model knowledge because this sandbox
could not reach a reference site — every Latin text in this module was
checked against published Vulgate editions at authoring time (Bible Study
Tools, StudyLight, Blue Letter Bible, and Bible.com's Clementine text).
Readings are given in the Clementine Vulgate's punctuated form, the
edition a classical homeschool family is most likely to have on the shelf.
Two known edition variants, recorded here so a future editor does not
"fix" one into the other by accident:

  * Mt 22:39 — the Clementine prints `teipsum` as one word; the Stuttgart
    critical text prints `te ipsum`. Both are the same words.
  * 1 Cor 13:13 — the Clementine reads `manent ... major autem horum`;
    the Nova Vulgata reads `manet ... maior autem ex his`. The Clementine
    is used here.

PSALM NUMBERING IS AVOIDED ON PURPOSE. "Initium sapientiae timor Domini"
(Vulgate Ps 110:10) is the more famous phrasing for Sapientia, and it is
NOT used, because the Vulgate/Septuagint psalm numbering differs from the
Hebrew/Masoretic numbering nearly every Protestant Bible follows — the
same verse is Psalm 111:10 there. Citing it would force this subject to
pick a numbering tradition in front of a child on its very first wisdom
lesson. Proverbs 9:10 says the same thing, carries the same chapter and
verse number in every tradition, and is used instead.

ORA ET LABORA IS HONESTLY LABELLED. The motto is genuinely Benedictine in
spirit — St. Benedict's own Rule, chapter 48, orders the monastic day into
alternating prayer, reading, and manual work — but the phrase itself
appears nowhere in the Rule, and nowhere in Benedictine literature before
the 19th century; it was popularized by Maurus Wolter, first Abbot of
Beuron, in 1880. That is stated in the entry rather than smoothed over.
The constitution's first non-negotiable rule forbids fabricated certainty,
and "a phrase St. Benedict wrote" is exactly the kind of pleasant, widely
repeated, false thing a tutor should not hand a child. It also happens to
be the entry's best lesson: the words are true to the Rule even though
they are not from it.

PRONUNCIATION. Ecclesiastical (Church) Latin, the pronunciation used with
sung and prayed Latin and the one most Christian-classical programs teach.
Families using a program that teaches Classical (restored) pronunciation
will hear differences — most audibly `c` before e/i as hard [k] rather
than [ch], and `v` as [w] — and the prompt block says so, so Bede defers
to the family's own program rather than correcting a child who has been
taught the other way. See SessionConfig.curriculum_resources.
"""
from datetime import date

from models.schemas import GradeStage, grade_to_stage

_ALL_STAGES = {GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent}
_FROM_3 = {GradeStage.core_mastery, GradeStage.independent}


def _term(
    term_id: str,
    latin: str,
    english: str,
    pronunciation: str,
    stages: set,
    meaning: str,
    anchor_ref: str,
    anchor_latin: str,
    anchor_english: str,
    derivatives: str,
    caution: str = "",
) -> dict:
    return {
        "term_id": term_id,
        "latin": latin,
        "english": english,
        "pronunciation": pronunciation,
        "stages": stages,
        "meaning": meaning,
        "anchor_ref": anchor_ref,
        "anchor_latin": anchor_latin,
        "anchor_english": anchor_english,
        "derivatives": derivatives,
        "caution": caution,
    }


# The six foundational terms. Order is the order a family would meet them:
# the three theological virtues first (they are also the three the
# constitution itself is built on — see constitution/bede.constitution.json's
# theological_virtues), then wisdom and truth, then the rhythm of the day.
_TERMS = [
    _term(
        "fides", "Fides", "faith", "FEE-dess", _ALL_STAGES,
        "Trust — believing someone because of who they are, and holding to it.",
        "1 Corinthians 13:13",
        "Nunc autem manent fides, spes, caritas, tria hæc: major autem horum est caritas.",
        "And now there remain faith, hope, and charity, these three: but the greatest of these is charity.",
        "fidelity, confide, fiancé, bona fide, Fido (a dog's name meaning \"I trust\")",
    ),
    _term(
        "spes", "Spes", "hope", "spess", _ALL_STAGES,
        "Looking forward to a good that is real but not here yet — and not giving up.",
        "Romans 12:12",
        "Spe gaudentes, in tribulatione patientes, orationi instantes.",
        "Rejoicing in hope; patient in tribulation; instant in prayer.",
        "despair (literally \"down from hope\"), desperate, prosper",
    ),
    _term(
        "caritas", "Caritas", "love, charity", "KAH-ree-tahs", _ALL_STAGES,
        "The love that gives itself away for someone else's real good — the greatest of the three.",
        "1 Corinthians 13:13",
        "Nunc autem manent fides, spes, caritas, tria hæc: major autem horum est caritas.",
        "And now there remain faith, hope, and charity, these three: but the greatest of these is charity.",
        "charity, charitable, cherish",
        caution=(
            "Latin has several words English flattens into \"love.\" `Caritas` is self-giving love "
            "willed for another's good; `amor` is love as desire or affection; `amicitia` is "
            "friendship. That is why older English Bibles say \"charity\" here and newer ones say "
            "\"love\" — the translators are reaching for the same word and neither is a mistake."
        ),
    ),
    _term(
        "sapientia", "Sapientia", "wisdom", "sah-pee-EN-tsee-ah", _FROM_3,
        "Knowing not just what is true, but what it is FOR — and living accordingly.",
        "Proverbs 9:10",
        "Principium sapientiæ timor Domini, et scientia sanctorum prudentia.",
        "The fear of the Lord is the beginning of wisdom: and the knowledge of the holy is prudence.",
        "sapient, savant, savvy, homo sapiens (\"wise man\")",
        caution=(
            "`Timor Domini` here is reverent awe before God, not being frightened of Him — the "
            "same distinction the constitution's own seventh gift draws. Say so plainly if a "
            "child hears \"fear\" and looks worried."
        ),
    ),
    _term(
        "veritas", "Veritas", "truth", "VEH-ree-tahs", _FROM_3,
        "What is actually so — whether or not anyone likes it, and whether or not anyone knows it.",
        "John 14:6",
        "Dicit ei Jesus: Ego sum via, et veritas, et vita. Nemo venit ad Patrem, nisi per me.",
        "Jesus saith to him: I am the way, and the truth, and the life. No man cometh to the Father, but by me.",
        "verify, verdict, veracity, very (originally \"truly\"), aver",
    ),
    _term(
        "ora_et_labora", "Ora et Labora", "pray and work", "OH-rah et lah-BOH-rah", _FROM_3,
        "A whole day held together: prayer and work belong to each other, and neither one is a "
        "break from the other.",
        "Rule of St. Benedict, chapter 48 (the idea, not the phrase — see below)",
        "Otiositas inimica est animæ.",
        "Idleness is the enemy of the soul.",
        "oratory, oral, adore, laboratory, labor, elaborate, collaborate",
        caution=(
            "Be honest about this one if it comes up. `Ora et labora` is a real summary of St. "
            "Benedict's Rule, but it is NOT a quotation from it: the phrase appears nowhere in the "
            "Rule and nowhere in Benedictine writing before the 19th century, when Maurus Wolter, "
            "the first Abbot of Beuron, popularized it in 1880. The Latin sentence quoted above "
            "(`Otiositas inimica est animæ`) IS from the Rule, chapter 48, and it is the sentence "
            "the motto is summarizing. Never tell a child St. Benedict wrote \"ora et labora\"; do "
            "tell them it is a fair four-word summary of what he actually ordered."
        ),
    ),
]

_TERMS_BY_ID = {t["term_id"]: t for t in _TERMS}

# The spine of the whole subject: Christ's own summary of the law, in the
# Vulgate, given in two halves so a K-2 child can hold one at a time and a
# 6-8 student can put them back together as one sentence.
GREAT_COMMANDMENT = {
    "ref": "Matthew 22:37, 39 (Vulgate)",
    "first_latin": "Diliges Dominum Deum tuum ex toto corde tuo, et in tota anima tua, et in tota mente tua.",
    "first_english": (
        "Thou shalt love the Lord thy God with thy whole heart, and with thy whole soul, "
        "and with thy whole mind."
    ),
    "second_latin": "Diliges proximum tuum sicut teipsum.",
    "second_english": "Thou shalt love thy neighbour as thyself.",
    "short_form": "Diliges Dominum Deum tuum... et proximum tuum sicut teipsum.",
    "english_note": (
        "The English above is the Douay-Rheims, the English translation made from this very Latin "
        "— so the two line up word for word. If the family reads a different translation (see the "
        "Bible translation setting), use THEIR English wording when you quote it in English, and "
        "keep the Latin exactly as given here."
    ),
}

# Shared-Christian vocabulary, by stage. Nothing here is specific to one
# tradition; every word is either a plain noun of the faith or a word a
# child meets in Scripture and in hymns across every Christian communion.
_VOCABULARY = {
    GradeStage.foundations: [
        ("Deus", "God", "DEH-oos"),
        ("Amen", "truly, so be it", "AH-men"),
        ("Lux", "light", "looks"),
        ("Pax", "peace", "pahks"),
        ("Aqua", "water", "AH-kwah"),
        ("Terra", "earth, land", "TEH-rah"),
    ],
    GradeStage.core_mastery: [
        ("Verbum", "word", "VEHR-boom"),
        ("Gratia", "grace, thanks", "GRAH-tsee-ah"),
        ("Gloria", "glory", "GLOH-ree-ah"),
        ("Vita", "life", "VEE-tah"),
        ("Via", "way, road", "VEE-ah"),
        ("Caelum", "heaven, sky", "CHAY-loom"),
    ],
    GradeStage.independent: [
        ("Credo", "I believe", "KREH-doh"),
        ("Misericordia", "mercy", "mee-seh-ree-KOR-dee-ah"),
        ("Justitia", "justice", "yoo-STEE-tsee-ah"),
        ("Humilitas", "humility", "hoo-MEE-lee-tahs"),
        ("Testamentum", "covenant, testament", "tess-tah-MEN-toom"),
        ("Evangelium", "gospel, good news", "eh-vahn-GHEH-lee-oom"),
    ],
}

# How the subject is actually taught at each stage. The progression is the
# ordinary classical one — ear before eye, eye before grammar — and it is
# the reason this subject is honest at K-2 rather than premature: a
# Grammar-stage child is doing exactly what the classical tradition asks of
# them (hearing, saying, loving the sound), not conjugating anything.
_STAGE_METHOD = {
    GradeStage.foundations: (
        "K-2 — EAR ONLY. Latin at this stage is heard and said, never parsed and never written. "
        "Say the word; have the child say it back; tell them what it means in one short sentence; "
        "delight in it. Two or three words in a session is plenty, and repeating last session's "
        "word is better than adding a new one. NO grammar, NO cases, NO conjugation, NO spelling "
        "of Latin, and never ask a child this age to translate. If they want to shout AMEN or LUX "
        "for the joy of the sound, that IS the lesson working."
    ),
    GradeStage.core_mastery: (
        "3-5 — WORDS AND ROOTS. Keep saying the words aloud, and now add two things: what the word "
        "means, and which English words grew out of it. Root-hunting is the heart of this stage — "
        "\"we get 'verify' from veritas\" turns Latin into a key that opens English. Short copywork "
        "of a Latin phrase by hand suits this stage well (`invite_handwriting`). Introduce that "
        "Latin changes a word's ENDING to show its job in the sentence, but as a noticing, not a "
        "paradigm to memorize: `Deus` (God, doing something) vs. `Deum` (God, being loved). One "
        "noticing per session at most."
    ),
    GradeStage.independent: (
        "6-8 — SENTENCES. The student can now meet a whole Vulgate sentence and take it apart: who "
        "is doing what to whom, and how the endings tell them. Nominative and accusative are enough "
        "grammar to carry the Great Commandment; add the genitive when a phrase needs it. Ask them "
        "to render a line into their own English and then compare it with the printed translation "
        "— where the two differ is where the real conversation is. Translation, derivation, and "
        "why a translator chose one English word over another are all fair game."
    ),
}


def current_week(today: "date | None" = None) -> int:
    """1-based ISO week number — same calendar-driven rotation
    services/poetry_catalog.py uses, with no stored state to drift."""
    return (today or date.today()).isocalendar()[1]


def _terms_for(stage: GradeStage) -> list:
    return [t for t in _TERMS if stage in t["stages"]]


def term_for_week(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> "dict | None":
    """
    This week's focus term, filtered to the ones appropriate for the
    child's stage. Same weekly-rotation-with-salt convention as
    poetry_catalog.poem_for_week — week_salt is the session's current_term,
    so two families in the same calendar week don't necessarily land on the
    identical word. grade is accepted for signature symmetry with the
    sibling catalogs and to allow future per-grade curation; stage is what
    actually filters today.
    """
    stage = grade_to_stage(grade) if grade else stage
    entries = _terms_for(stage)
    if not entries:
        return None
    return entries[(current_week(today) + week_salt - 1) % len(entries)]


def vocabulary_for(stage: GradeStage) -> list:
    return _VOCABULARY.get(stage, [])


def latin_note(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> str:
    """
    The Subject.latin prompt block: this week's focus term with its
    verified Vulgate anchor, the stage-appropriate vocabulary, the Great
    Commandment spine, and the rules that keep Bede quoting rather than
    inventing Latin. Returns "" only if a future edit leaves a stage with
    no terms at all.
    """
    term = term_for_week(grade, stage, week_salt, today)
    if not term:
        return ""

    words = "\n".join(
        f"  - {latin} — {english} (say it: {pron})"
        for latin, english, pron in vocabulary_for(stage)
    )
    caution = f"\n\nIMPORTANT for this term: {term['caution']}" if term["caution"] else ""

    return f"""

<latin_foundations>
THIS WEEK'S TERM: {term['latin']} — "{term['english']}" (say it: {term['pronunciation']})
What it means: {term['meaning']}
English words that grew from it: {term['derivatives']}

Where it comes from ({term['anchor_ref']}) — quote this Latin EXACTLY as written:
  {term['anchor_latin']}
  "{term['anchor_english']}"{caution}

THE SENTENCE THIS WHOLE SUBJECT IS BUILT ON ({GREAT_COMMANDMENT['ref']}):
  {GREAT_COMMANDMENT['first_latin']}
  "{GREAT_COMMANDMENT['first_english']}"
  {GREAT_COMMANDMENT['second_latin']}
  "{GREAT_COMMANDMENT['second_english']}"
{GREAT_COMMANDMENT['english_note']}
Come back to this sentence often — it is the thread every other word in this subject hangs on.
Every term above is one facet of it: faith and hope and love are HOW this is obeyed, wisdom and
truth are what it takes to obey it well, and prayer and work are the two halves of the day in
which it is actually done.

WORDS FOR THIS STAGE:
{words}

HOW TO TEACH IT AT THIS STAGE:
{_STAGE_METHOD[stage]}

RULES FOR LATIN SPECIFICALLY:
- Quote ONLY the Latin given in this block. Never recite a Latin verse, prayer, or phrase from
  memory, and never compose Latin of your own to show a child — in an inflected language a single
  wrong ending changes the grammar, and a child cannot catch the error. If a child asks for Latin
  you have not been given here, say honestly that you would want to check it rather than guess,
  and offer one of the words above instead.
- Pronunciation above is Ecclesiastical (Church) Latin. If the family uses a program that teaches
  Classical pronunciation, or the child says a word the other way (hard `c` before e/i, `v` as
  `w`), do NOT correct them — both are real, and their own program is the authority here.
- Keep this a real Socratic session, not a vocabulary drill. Wonder about the word, ask what it
  reminds them of, hunt the English words hiding inside it, connect it to something that happened
  in their own week. A child who has met one word properly has had a better lesson than a child
  who has been quizzed on six.
- Later in the SAME conversation — not immediately, and never as a test — it is natural to come
  back to a word you taught earlier and see whether it stayed. If the child genuinely shows you
  either way, call `record_language_evidence` with language `latin` and an honest outcome. If they
  have lost it, say the word again warmly and move on; never correct, re-drill, or let a forgotten
  word end the session on a sour note. Never mention this recording to the child.

FAITH SCOPE — this subject is for EVERY Christian family:
- Everything here is the shared inheritance of all Christians: the Vulgate, the theological
  virtues, wisdom, truth, and the rhythm of prayer and work. Teach it as such.
- Do NOT introduce material specific to one tradition in this subject — devotion to the saints or
  to Mary, the sacraments, prayers for the dead, or a particular church's structure and authority.
  A family that wants that has Saints & Catechism available as its own subject; a family that does
  not must be able to do this subject start to finish without ever being taught it.
- If a child asks a doctrinal question that divides Christian traditions ("do we pray to Mary?",
  "what happens at communion?"), answer the LANGUAGE question if there is one, and send the
  doctrinal question warmly and directly to their own parents and their own pastor, priest, or
  minister. That is their family's to answer, never yours.
</latin_foundations>"""
