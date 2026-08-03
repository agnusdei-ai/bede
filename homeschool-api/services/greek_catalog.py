"""
Greek & New Testament Foundations — the verbatim content behind
Subject.greek. Sibling to services/latin_catalog.py; read that module's
docstring first, since the architecture, the VERBATIM rule, and the
"shared inheritance only" scope test are identical and are not repeated
here. What follows is only what is different about Greek.

WHY GREEK, GIVEN LATIN ALREADY EXISTS. Not "a second classical language."
The Vulgate is a translation; Koine Greek is the original. For a family in
a tradition that emphasizes reading Scripture in its own words, that
distinction is the whole point, and it makes Greek — if anything — a
stronger fit than Latin. It is also the one classical language that serves
Orthodox families, who are served by neither Subject.saints (Catholic in
scope, via the Ignatius Press Faith and Life catechism) nor Latin (the
Western Church's language).

THE SAME SIX VIRTUES, IN THE ORIGINAL. The terms below deliberately mirror
latin_catalog.py's six, and four of them carry the SAME anchor verse:

    πίστις  / Fides         1 Corinthians 13:13   (same verse)
    ἐλπίς   / Spes          Romans 12:12          (same verse)
    ἀγάπη   / Caritas       1 Corinthians 13:13   (same verse)
    σοφία   / Sapientia     James 1:5             (Latin uses Proverbs 9:10)
    ἀλήθεια / Veritas       John 14:6             (same verse)
    λόγος   / Ora et Labora John 1:1              (no Latin counterpart)

That is a feature, not a coincidence: a child taking both subjects meets
one verse in two languages and can see for themselves that `caritas` is
translating ἀγάπη. `λόγος` replaces Latin's Ora et Labora rather than
matching it — the Benedictine motto has no Greek counterpart, and λόγος is
the single most consequential Greek word in Christian thought.

TEXTUAL TRADITION IS DELIBERATELY SIDESTEPPED. Greek has a live, and
sometimes heated, divide the Vulgate does not: the Textus Receptus (behind
the KJV/NKJV) against the modern critical text (Nestle-Aland/UBS, behind
the ESV/NIV/NASB/CSB). A K-8 tutoring subject has no business adjudicating
it. So every anchor below was chosen from passages where the two
traditions read identically at the phrase being quoted — verified at
authoring time against both. This is the same reasoning that made
latin_catalog.py cite Proverbs 9:10 rather than the psalm whose number
differs between the Vulgate and Hebrew numbering: pick the text that says
the same thing everywhere, and the question never has to be raised in
front of a child.

PRONUNCIATION IS ERASMIAN, AND HONESTLY LABELLED. Erasmian is the
convention of classical academia and of Christian-classical programs
(Memoria Press argues for it explicitly, on the grounds that every written
symbol gets one distinct sound, which is what a child learning to spell an
inflected language needs). It is what this catalog teaches. It is also
NOT how Greek ever actually sounded — it is a teaching convention, not a
reconstruction, and Modern and Byzantine pronunciation are both closer to
the living tradition. This matters more here than the Ecclesiastical/
Classical split does in Latin, because a Greek-heritage or Orthodox child
may well pronounce these words the way their own family and parish
actually say them. Bede is told, in as many words, never to correct that.

THE ALPHABET IS THE K-2 CURRICULUM. Greek's unfamiliar script is an asset
at Grammar stage, not an obstacle: learning the letters is concrete,
physical, and delightful in a way abstract vocabulary is not, and the
payoff lands immediately — the word "alphabet" is alpha plus beta, and
Christ calls himself the first letter and the last (Revelation 22:13).
That verse is the K-2 anchor for exactly that reason.
"""
from datetime import date

from models.schemas import GradeStage, grade_to_stage

_ALL_STAGES = {GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent}
_FROM_3 = {GradeStage.core_mastery, GradeStage.independent}


def _term(
    term_id: str,
    greek: str,
    transliteration: str,
    english: str,
    pronunciation: str,
    stages: set,
    meaning: str,
    anchor_ref: str,
    anchor_greek: str,
    anchor_english: str,
    derivatives: str,
    caution: str = "",
) -> dict:
    return {
        "term_id": term_id,
        "greek": greek,
        "transliteration": transliteration,
        "english": english,
        "pronunciation": pronunciation,
        "stages": stages,
        "meaning": meaning,
        "anchor_ref": anchor_ref,
        "anchor_greek": anchor_greek,
        "anchor_english": anchor_english,
        "derivatives": derivatives,
        "caution": caution,
    }


_TERMS = [
    _term(
        "pistis", "πίστις", "pistis", "faith", "PIS-tis", _ALL_STAGES,
        "Trust — believing someone because of who they are, and holding to it.",
        "1 Corinthians 13:13",
        "νυνὶ δὲ μένει πίστις, ἐλπίς, ἀγάπη, τὰ τρία ταῦτα· μείζων δὲ τούτων ἡ ἀγάπη.",
        "And now abide faith, hope, love, these three; but the greatest of these is love.",
        "few in everyday English — see the note below, which is the lesson here",
        caution=(
            "Worth pointing out rather than glossing over: πίστις left almost no descendants in "
            "English, while λόγος left dozens. That is not an accident. English took its words for "
            "believing and loving from Latin (faith from `fides`, charity from `caritas`) and its "
            "words for thinking and studying from Greek (logic, biology, theology). A child taking "
            "both subjects can see the two languages divided the work between them."
        ),
    ),
    _term(
        "elpis", "ἐλπίς", "elpis", "hope", "el-PIS", _ALL_STAGES,
        "Looking forward to a good that is real but not here yet — and not giving up.",
        "Romans 12:12",
        "τῇ ἐλπίδι χαίροντες, τῇ θλίψει ὑπομένοντες, τῇ προσευχῇ προσκαρτεροῦντες.",
        "Rejoicing in hope, patient in tribulation, continuing steadfastly in prayer.",
        "rare in English, like πίστις — the name Elpis itself, and little else",
        caution=(
            "The word changes shape in this verse: the dictionary form is ἐλπίς, but Paul writes "
            "ἐλπίδι because of the job it is doing in the sentence. At 6-8 that is worth naming as "
            "the dative case; below that, just say the ending changed and move on."
        ),
    ),
    _term(
        "agape", "ἀγάπη", "agapē", "love", "ah-GAH-pay", _ALL_STAGES,
        "The love that gives itself away for someone else's real good — the greatest of the three.",
        "1 Corinthians 13:13",
        "νυνὶ δὲ μένει πίστις, ἐλπίς, ἀγάπη, τὰ τρία ταῦτα· μείζων δὲ τούτων ἡ ἀγάπη.",
        "And now abide faith, hope, love, these three; but the greatest of these is love.",
        "agape (borrowed into English whole, used in theology and in \"agape feast\")",
        caution=(
            "Greek has several words English flattens into \"love,\" and this is the one place the "
            "distinction really pays: ἀγάπη is self-giving love willed for another's good; ἔρως is "
            "desire; φιλία is friendship; στοργή is family affection. That is why older English "
            "Bibles render ἀγάπη as \"charity\" — they are reaching for the same distinction Latin "
            "makes with `caritas`, and neither wording is a mistake."
        ),
    ),
    _term(
        "sophia", "σοφία", "sophia", "wisdom", "so-FEE-ah", _FROM_3,
        "Knowing not just what is true, but what it is FOR — and living accordingly.",
        "James 1:5",
        "Εἰ δέ τις ὑμῶν λείπεται σοφίας, αἰτείτω παρὰ τοῦ διδόντος θεοῦ πᾶσιν ἁπλῶς.",
        "If any of you lacks wisdom, let him ask of God, who gives to all liberally.",
        "philosophy (love of wisdom), sophisticated, sophomore (\"wise fool\"), Sophia as a name",
    ),
    _term(
        "aletheia", "ἀλήθεια", "alētheia", "truth", "ah-LAY-thay-ah", _FROM_3,
        "What is actually so — whether or not anyone likes it, and whether or not anyone knows it.",
        "John 14:6",
        "λέγει αὐτῷ ὁ Ἰησοῦς· Ἐγώ εἰμι ἡ ὁδὸς καὶ ἡ ἀλήθεια καὶ ἡ ζωή.",
        "Jesus said to him: I am the way, and the truth, and the life.",
        "lethargy and the river Lethe — both from λήθη, forgetting; see the note",
        caution=(
            "A lovely one for 6-8. ἀλήθεια is built from ἀ- (not) plus λήθη (forgetting), so it "
            "literally means un-forgetting, or un-hiddenness — truth as what stops being concealed. "
            "λήθη is where English gets lethargy. Ask what it would mean for truth to be something "
            "uncovered rather than something invented; that question is the lesson."
        ),
    ),
    _term(
        "logos", "λόγος", "logos", "word, reason", "LOG-os", _FROM_3,
        "Word — but also reason, account, the sense a thing makes. John calls Christ this.",
        "John 1:1",
        "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν, καὶ θεὸς ἦν ὁ λόγος.",
        "In the beginning was the Word, and the Word was with God, and the Word was God.",
        "logic, logo, dialogue, catalogue, apology, and every single -ology "
        "(biology, theology, geology, zoology)",
        caution=(
            "λόγος does not mean only \"word\" — it also carries reason, argument, and the account "
            "a thing gives of itself, which is why it produced both `logic` and every `-ology`. "
            "Say that plainly; do not go further and explain what John MEANT by calling Christ the "
            "λόγος. That is theology, and it belongs to the family's own pastor, priest, or "
            "minister, not to you."
        ),
    ),
]

_TERMS_BY_ID = {t["term_id"]: t for t in _TERMS}

# Same spine as latin_catalog.py's, in the language Matthew wrote it in.
# Text is identical in the Textus Receptus and the critical text at both
# verses — see this module's docstring on why that mattered for selection.
GREAT_COMMANDMENT = {
    "ref": "Matthew 22:37, 39 (Greek)",
    "first_greek": (
        "Ἀγαπήσεις κύριον τὸν θεόν σου ἐν ὅλῃ τῇ καρδίᾳ σου "
        "καὶ ἐν ὅλῃ τῇ ψυχῇ σου καὶ ἐν ὅλῃ τῇ διανοίᾳ σου."
    ),
    "first_english": (
        "You shall love the Lord your God with all your heart, and with all your soul, "
        "and with all your mind."
    ),
    "second_greek": "Ἀγαπήσεις τὸν πλησίον σου ὡς σεαυτόν.",
    "second_english": "You shall love your neighbor as yourself.",
    "english_note": (
        "The English above is a plain rendering of this Greek, not a quotation from any published "
        "translation. If the family has set a Bible translation, use THEIR English wording when you "
        "quote it in English, and keep the Greek exactly as given here."
    ),
    "link_to_latin": (
        "Note for a child who also takes Latin: the verb here is ἀγαπήσεις, from ἀγάπη — the same "
        "word as the Latin `caritas` in `Diliges proximum tuum sicut teipsum`. Same sentence, two "
        "languages. If they take both subjects, showing them that once is worth more than saying "
        "it every week."
    ),
}

# The Greek alphabet — the whole K-2 curriculum, and the reference a 3-5
# student reads and writes from. Erasmian sounds (see the module docstring).
ALPHABET = [
    ("Α", "α", "alpha", "a as in father"),
    ("Β", "β", "beta", "b"),
    ("Γ", "γ", "gamma", "g as in go"),
    ("Δ", "δ", "delta", "d"),
    ("Ε", "ε", "epsilon", "e as in met"),
    ("Ζ", "ζ", "zeta", "dz as in adze"),
    ("Η", "η", "eta", "ay as in they"),
    ("Θ", "θ", "theta", "th as in thin"),
    ("Ι", "ι", "iota", "i as in machine"),
    ("Κ", "κ", "kappa", "k"),
    ("Λ", "λ", "lambda", "l"),
    ("Μ", "μ", "mu", "m"),
    ("Ν", "ν", "nu", "n"),
    ("Ξ", "ξ", "xi", "x as in box"),
    ("Ο", "ο", "omicron", "o as in not"),
    ("Π", "π", "pi", "p"),
    ("Ρ", "ρ", "rho", "r"),
    ("Σ", "σ / ς", "sigma", "s (ς only at the end of a word)"),
    ("Τ", "τ", "tau", "t"),
    ("Υ", "υ", "upsilon", "u as in the French tu"),
    ("Φ", "φ", "phi", "ph as in phone"),
    ("Χ", "χ", "chi", "ch as in Bach"),
    ("Ψ", "ψ", "psi", "ps as in lips"),
    ("Ω", "ω", "omega", "o as in tone"),
]

# The K-2 anchor: the first letter and the last, and what Christ calls
# himself with them. Identical in both textual traditions.
ALPHA_OMEGA = {
    "ref": "Revelation 22:13",
    "greek": "ἐγὼ τὸ Ἄλφα καὶ τὸ Ὦ, ὁ πρῶτος καὶ ὁ ἔσχατος, ἡ ἀρχὴ καὶ τὸ τέλος.",
    "english": "I am the Alpha and the Omega, the first and the last, the beginning and the end.",
}

_VOCABULARY = {
    GradeStage.foundations: [
        ("Ἀμήν", "amēn", "truly, so be it", "ah-MANE"),
        ("Θεός", "theos", "God", "theh-OSS"),
        ("Χριστός", "christos", "anointed one, Christ", "chris-TOSS"),
        ("φῶς", "phōs", "light", "foce"),
        ("εἰρήνη", "eirēnē", "peace", "ay-RAY-nay"),
    ],
    GradeStage.core_mastery: [
        ("χάρις", "charis", "grace", "KAH-ris"),
        ("ζωή", "zōē", "life", "zo-AY"),
        ("ὁδός", "hodos", "way, road", "ho-DOSS"),
        ("δόξα", "doxa", "glory", "DOX-ah"),
        ("εὐαγγέλιον", "euangelion", "good news, gospel", "yoo-ang-GEL-ee-on"),
    ],
    GradeStage.independent: [
        ("ἐκκλησία", "ekklēsia", "assembly, church", "ek-klay-SEE-ah"),
        ("κοινωνία", "koinōnia", "fellowship, sharing in common", "koy-no-NEE-ah"),
        ("μετάνοια", "metanoia", "a change of mind, repentance", "meh-TAH-noy-ah"),
        ("μαρτυρία", "martyria", "witness, testimony", "mar-too-REE-ah"),
        ("βασιλεία", "basileia", "kingdom, reign", "bah-si-LAY-ah"),
    ],
}

# Words whose plain meaning is shared but whose application divides
# traditions. Bede teaches what the word MEANT to its first readers and
# stops there — the alternative is quietly taking a side on church
# government or the sacraments inside a vocabulary lesson.
_VOCABULARY_CAUTIONS = {
    "ἐκκλησία": (
        "ἐκκλησία simply meant an assembly of people called out and gathered — that is what the "
        "word does. Teach that. Do NOT go on to say what a church should therefore look like, who "
        "leads it, or how it should be governed; Christian traditions differ on exactly that, and "
        "it belongs to the family's own pastor, priest, or minister."
    ),
    "μετάνοια": (
        "μετάνοια is literally a change of mind — μετα (change) plus νοῦς (mind). Teach the word. "
        "Do not teach what a person must therefore do about it; that is the family's own church's "
        "to say."
    ),
}

_STAGE_METHOD = {
    GradeStage.foundations: (
        "K-2 — THE ALPHABET, BY EAR AND EYE. This whole stage is the letters, and that is a full "
        "year's delight: their names, their sounds, their shapes. Two or three letters in a "
        "session, said aloud and traced in the air or on paper. The payoff lands immediately — the "
        "word ALPHABET is alpha plus beta, and Christ calls himself the first letter and the last "
        "(see the alpha-and-omega verse below). Say πίστις, ἐλπίς, and ἀγάπη as sounds the child "
        "can repeat, always with the English right beside them. NO grammar, NO cases, NO parsing, "
        "and never ask a child this age to read a Greek sentence or translate anything."
    ),
    GradeStage.core_mastery: (
        "3-5 — READING AND TRANSLITERATING. The child reads the letters fluently now and can turn "
        "a short Greek word into English letters (λόγος → logos) and back. That skill is the whole "
        "stage; everything else hangs on it. Add what each term means and the English words that "
        "grew out of it — this is where Greek pays for itself, since a child who knows λόγος owns "
        "every -ology word they will ever meet. Writing Greek letters by hand suits this stage well "
        "(`invite_handwriting`). Mention breathing marks lightly when a word has one (ὁδός is "
        "\"hodos,\" not \"odos\"), as a noticing, not a rule to memorize."
    ),
    GradeStage.independent: (
        "6-8 — READING PHRASES. The student meets short New Testament phrases and takes them apart. "
        "The definite article (ὁ, ἡ, τό) is the highest-value thing to teach here — Greek uses it "
        "constantly where English does not, and noticing it unlocks whole verses. Nominative and "
        "accusative carry the Great Commandment. Ask the student to render a line into their own "
        "English and then compare it with a printed translation; where the two differ is the real "
        "conversation. If they also take Latin, comparing the same verse in both is the single most "
        "valuable thing you can do in this subject."
    ),
}


def current_week(today: "date | None" = None) -> int:
    """1-based ISO week number — same calendar-driven rotation
    services/latin_catalog.py and the poetry/prayer catalogs use."""
    return (today or date.today()).isocalendar()[1]


def _terms_for(stage: GradeStage) -> list:
    return [t for t in _TERMS if stage in t["stages"]]


def term_for_week(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> "dict | None":
    """This week's focus term, stage-filtered. Same contract as
    latin_catalog.term_for_week — see there."""
    stage = grade_to_stage(grade) if grade else stage
    entries = _terms_for(stage)
    if not entries:
        return None
    return entries[(current_week(today) + week_salt - 1) % len(entries)]


def vocabulary_for(stage: GradeStage) -> list:
    return _VOCABULARY.get(stage, [])


def letters_for_week(stage: GradeStage, week_salt: int = 0, today: "date | None" = None) -> list:
    """
    K-2 works through the alphabet a few letters at a time across the year,
    so the block names WHICH letters this week rather than dumping all 24
    into every session. Later stages get the whole alphabet as a standing
    reference — by then it is something to read from, not to learn.
    """
    if stage != GradeStage.foundations:
        return ALPHABET
    per_week = 2
    groups = (len(ALPHABET) + per_week - 1) // per_week
    start = ((current_week(today) + week_salt - 1) % groups) * per_week
    return ALPHABET[start:start + per_week]


def greek_note(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> str:
    """
    The Subject.greek prompt block. Same shape and same guarantees as
    latin_catalog.latin_note, plus the alphabet work Greek needs and Latin
    does not.
    """
    stage = grade_to_stage(grade) if grade else stage
    term = term_for_week(grade, stage, week_salt, today)
    if not term:
        return ""

    letters = letters_for_week(stage, week_salt, today)
    letter_lines = "\n".join(
        f"  {upper} {lower} — {name} (sounds like: {sound})" for upper, lower, name, sound in letters
    )
    letter_heading = (
        "THIS WEEK'S LETTERS (the whole lesson at this stage — take them slowly):"
        if stage == GradeStage.foundations
        else "THE ALPHABET (reference — the student should be reading these, not learning them fresh):"
    )

    words = "\n".join(
        f"  - {greek} ({translit}) — {english} (say it: {pron})"
        + (f"\n      NOTE: {_VOCABULARY_CAUTIONS[greek]}" if greek in _VOCABULARY_CAUTIONS else "")
        for greek, translit, english, pron in vocabulary_for(stage)
    )
    # Cautions are suppressed entirely at K-2. Every one of them is
    # analytical 3+ material — case endings, English derivation history,
    # the four Greek words for love — and none belongs in an ear-only
    # stage. One of them makes that concrete rather than theoretical: the
    # ἀγάπη note distinguishes it from ἔρως, which has no business
    # rendering into a five-year-old's prompt block just because ἀγάπη is
    # taught at every stage. latin_catalog.py needs no equivalent rule; its
    # only K-2-reachable caution contrasts `caritas` with `amor` and
    # `amicitia`, which is harmless at any age.
    caution = (
        f"\n\nIMPORTANT for this term: {term['caution']}"
        if term["caution"] and stage != GradeStage.foundations
        else ""
    )

    alpha_omega = (
        f"\n\nTHE FIRST LETTER AND THE LAST ({ALPHA_OMEGA['ref']}) — quote this Greek EXACTLY:\n"
        f"  {ALPHA_OMEGA['greek']}\n"
        f"  \"{ALPHA_OMEGA['english']}\"\n"
        "Alpha is the first letter of the alphabet and Omega is the last, and Christ calls himself "
        "both. For a young child this is the best possible reason to learn the letters at all — the "
        "alphabet is not a chore in front of the lesson, it IS the lesson."
        if stage == GradeStage.foundations
        else ""
    )

    return f"""

<greek_foundations>
THIS WEEK'S TERM: {term['greek']} ({term['transliteration']}) — "{term['english']}" (say it: {term['pronunciation']})
What it means: {term['meaning']}
English words that grew from it: {term['derivatives']}

Where it comes from ({term['anchor_ref']}) — quote this Greek EXACTLY as written:
  {term['anchor_greek']}
  "{term['anchor_english']}"{caution}

{letter_heading}
{letter_lines}{alpha_omega}

THE SENTENCE THIS WHOLE SUBJECT IS BUILT ON ({GREAT_COMMANDMENT['ref']}):
  {GREAT_COMMANDMENT['first_greek']}
  "{GREAT_COMMANDMENT['first_english']}"
  {GREAT_COMMANDMENT['second_greek']}
  "{GREAT_COMMANDMENT['second_english']}"
{GREAT_COMMANDMENT['english_note']}
{GREAT_COMMANDMENT['link_to_latin']}
Come back to this sentence often — it is the thread every other word in this subject hangs on.

WORDS FOR THIS STAGE:
{words}

HOW TO TEACH IT AT THIS STAGE:
{_STAGE_METHOD[stage]}

RULES FOR GREEK SPECIFICALLY:
- Quote ONLY the Greek given in this block. Never recite a Greek verse or phrase from memory, and
  never compose Greek of your own to show a child — Greek is inflected, a single wrong ending
  changes the grammar, and a child cannot catch the error. If a child asks for Greek you have not
  been given here, say honestly that you would want to check it rather than guess, and offer one of
  the words above instead.
- ALWAYS give the transliteration and the English beside any Greek you show. A child who cannot yet
  read the alphabet must never be handed a wall of letters they have no way into.
- Pronunciation above is Erasmian — the convention used in classical schools and by most Greek
  programs a homeschooling family would use. Be honest if it comes up that it is a teaching
  convention rather than how Greek actually sounded; Modern and Byzantine pronunciation are closer
  to the living tradition. If a child says a word the way their own family, parish, or program says
  it — especially a Greek-heritage or Orthodox child saying words their church actually uses — do
  NOT correct them. Their own tradition is the authority, not this block.
- Keep this a real Socratic session, not a drill. Wonder about the word, hunt the English words
  hiding inside it, connect it to something in the child's own week. One word met properly beats
  six quizzed.
- Later in the SAME conversation — not immediately, and never as a test — it is natural to come
  back to a letter or word you taught earlier and see whether it stayed. If the child genuinely
  shows you either way, call `record_language_evidence` with language `greek` and an honest
  outcome. If they have lost it, say it again warmly and move on; never correct, re-drill, or let a
  forgotten word end the session badly. Never mention this recording to the child.

FAITH SCOPE — this subject is for EVERY Christian family:
- Everything here is the shared inheritance of all Christians: the Greek New Testament, the
  theological virtues, and the ordinary vocabulary of the faith. Teach it as such. This subject
  serves Protestant, Catholic, and Orthodox families alike, and nothing in it should read as
  belonging to one of them.
- Do NOT introduce material specific to one tradition — devotion to the saints or to Mary, the
  sacraments, prayers for the dead, icons, or a particular church's structure and authority. A
  family that wants that has Saints & Catechism available as its own subject; a family that does
  not must be able to do this subject start to finish without ever meeting it.
- Do NOT take a position on which Greek manuscript tradition is correct. Every text in this block
  reads the same in both, which is why it was chosen; if a student raises the question, say
  honestly that Christians differ on it and send them to their own pastor, priest, or minister.
- If a child asks a doctrinal question that divides Christian traditions, answer the LANGUAGE
  question if there is one, and send the doctrinal question warmly and directly to their own
  parents and their own pastor, priest, or minister. That is their family's to answer, never yours.
</greek_foundations>"""
