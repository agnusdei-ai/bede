"""
Catholic prayer library — traditional, universally standardized prayers
given in their EXACT wording, in English and Spanish, so Bede leads
recitation and memory-work verbatim from a fixed, reviewed text instead of
reciting from model memory each time (a model can subtly misquote a long
devotional text, and rote memorization — the whole point of this catalog —
requires exact, unchanging words). Mirrors services/poetry_catalog.py's
architecture (weekly calendar-driven rotation, grade-tagged entries,
week_salt for per-session offset) — see that module's own docstring for
the fuller reasoning behind each of those choices, not repeated here.

Every entry here is one of the handful of prayers said identically, in the
same wording, across virtually every English- and Spanish-language Catholic
missal, catechism, and parish in living memory (the Sign of the Cross, the
Our Father, the Hail Mary, and similarly universal texts) — chosen
specifically because their wording has effectively no live variation to get
wrong, unlike a poem's translation. That said: these were transcribed from
this app's own training-time knowledge, not cross-checked against a live
published source the way poetry_catalog.py's entries were (this sandbox's
network policy blocks fetching USCCB.org, Wikipedia, and similar reference
sites at build time — see the PR that added this file for the specific
attempt). Treat every entry, and especially the Spanish text, as a first
pass worth a native-speaker/parish review before a real family relies on
it — the same "translation quality bar" docs/LOCALIZATION.md already asks
of every other localized string in this app.

The Spanish text is the culturally standard prayer as prayed in the
Spanish-speaking Church, not a literal translation of the English —
e.g. the Hail Mary opens "Dios te salve, María" ("God save you, Mary"),
not a word-for-word rendering of "Hail Mary." Same "adapt, don't just
translate" principle as the rest of this app's localization work.

Deliberately excludes the Guardian Angel prayer ("Angel of God") — already
in poetry_catalog.py's own rotation for morning_time, and both catalogs
can land in the same week's Morning Time; showing the same prayer twice in
one session under two different framings (poetry co-study vs. prayer
recitation) would be confusing rather than reinforcing. Also excludes
longer, more edition-variable texts (the Apostles' Creed, the Angelus, the
Act of Contrition) for this first pass, pending the same source-review
this module's own docstring asks for.
"""
from datetime import date

from models.schemas import GradeStage, VALID_GRADES, grade_to_stage


def _entry(title: str, attribution: str, grades: set, text_en: str, text_es: str) -> dict:
    return {
        "title": title,
        "attribution": attribution,
        "grades": grades,
        "stages": {grade_to_stage(g) for g in grades},
        "text_en": text_en,
        "text_es": text_es,
    }


_COLLECTION = [
    _entry(
        "Sign of the Cross", "Traditional", {"K", "1", "2", "3", "4", "5", "6", "7", "8"},
        "In the name of the Father, and of the Son, and of the Holy Spirit. Amen.",
        "En el nombre del Padre, y del Hijo, y del Espíritu Santo. Amén.",
    ),
    _entry(
        "The Lord's Prayer (Our Father)", "Traditional", {"K", "1", "2", "3", "4", "5", "6", "7", "8"}, (
            "Our Father, who art in heaven, hallowed be thy name. Thy kingdom come, thy will be done, "
            "on earth as it is in heaven. Give us this day our daily bread, and forgive us our trespasses, "
            "as we forgive those who trespass against us. And lead us not into temptation, "
            "but deliver us from evil. Amen."
        ), (
            "Padre nuestro, que estás en el cielo, santificado sea tu Nombre; venga a nosotros tu reino; "
            "hágase tu voluntad en la tierra como en el cielo. Danos hoy nuestro pan de cada día; "
            "perdona nuestras ofensas, como también nosotros perdonamos a los que nos ofenden; "
            "no nos dejes caer en la tentación, y líbranos del mal. Amén."
        ),
    ),
    _entry(
        "Hail Mary", "Traditional", {"K", "1", "2", "3", "4", "5", "6", "7", "8"}, (
            "Hail Mary, full of grace, the Lord is with thee; blessed art thou among women, "
            "and blessed is the fruit of thy womb, Jesus. Holy Mary, Mother of God, "
            "pray for us sinners, now and at the hour of our death. Amen."
        ), (
            "Dios te salve, María, llena eres de gracia, el Señor es contigo; bendita tú eres "
            "entre todas las mujeres, y bendito es el fruto de tu vientre, Jesús. Santa María, "
            "Madre de Dios, ruega por nosotros, pecadores, ahora y en la hora de nuestra muerte. Amén."
        ),
    ),
    _entry(
        "Glory Be (Doxology)", "Traditional", {"K", "1", "2", "3", "4", "5", "6", "7", "8"}, (
            "Glory be to the Father, and to the Son, and to the Holy Spirit, as it was in the beginning, "
            "is now, and ever shall be, world without end. Amen."
        ), (
            "Gloria al Padre, y al Hijo, y al Espíritu Santo. Como era en el principio, ahora y siempre, "
            "por los siglos de los siglos. Amén."
        ),
    ),
    _entry(
        "Grace Before Meals", "Traditional", {"K", "1", "2", "3", "4", "5", "6", "7", "8"}, (
            "Bless us, O Lord, and these thy gifts, which we are about to receive from thy bounty, "
            "through Christ our Lord. Amen."
        ), (
            "Bendícenos, Señor, y bendice estos alimentos que por tu bondad vamos a tomar. "
            "Por Cristo, nuestro Señor. Amén."
        ),
    ),
    _entry(
        "Grace After Meals", "Traditional", {"K", "1", "2", "3", "4", "5", "6", "7", "8"}, (
            "We give Thee thanks for all Thy benefits, almighty God, who lives and reigns forever. Amen."
        ), (
            "Te damos gracias, Dios omnipotente, por todos tus beneficios, "
            "que vives y reinas por los siglos de los siglos. Amén."
        ),
    ),
    _entry(
        "Morning Offering", "Traditional (Apostleship of Prayer form)", {"2", "3", "4", "5", "6", "7", "8"}, (
            "O Jesus, through the Immaculate Heart of Mary, I offer You my prayers, works, joys, "
            "and sufferings of this day, in union with the Holy Sacrifice of the Mass throughout the world. Amen."
        ), (
            "Oh Jesús, por el Corazón Inmaculado de María, te ofrezco mis oraciones, trabajos, "
            "alegrías y sufrimientos de este día, en unión con el Santo Sacrificio de la Misa "
            "en todo el mundo. Amén."
        ),
    ),
    _entry(
        "Prayer to St. Michael the Archangel", "Pope Leo XIII, 1886", {"2", "3", "4", "5", "6", "7", "8"}, (
            "St. Michael the Archangel, defend us in battle. Be our defense against the wickedness "
            "and snares of the devil. May God rebuke him, we humbly pray, and do thou, O Prince of "
            "the heavenly hosts, by the power of God, thrust into hell Satan and all the evil spirits "
            "who prowl about the world seeking the ruin of souls. Amen."
        ), (
            "San Miguel Arcángel, defiéndenos en la batalla; sé nuestro amparo contra la perversidad "
            "y asechanzas del demonio. Reprímale Dios, pedimos suplicantes, y tú, Príncipe de la "
            "milicia celestial, arroja al infierno con el divino poder a Satanás y a los demás "
            "espíritus malignos que andan dispersos por el mundo para la perdición de las almas. Amén."
        ),
    ),
    _entry(
        "The Memorare", "Traditional (attrib. St. Bernard of Clairvaux)", {"4", "5", "6", "7", "8"}, (
            "Remember, O most gracious Virgin Mary, that never was it known that anyone who fled to "
            "thy protection, implored thy help, or sought thy intercession was left unaided. Inspired "
            "with this confidence, I fly unto thee, O Virgin of virgins, my Mother. To thee do I come, "
            "before thee I stand, sinful and sorrowful. O Mother of the Word Incarnate, despise not "
            "my petitions, but in thy mercy hear and answer me. Amen."
        ), (
            "Acordaos, oh piadosísima Virgen María, que jamás se ha oído decir que ninguno de los "
            "que han acudido a vuestra protección, implorando vuestra asistencia y reclamando vuestro "
            "socorro, haya sido abandonado de vos. Animado con esta confianza, a vos también acudo, "
            "oh Madre, Virgen de las vírgenes, y gimiendo bajo el peso de mis pecados me atrevo a "
            "comparecer ante vuestra presencia soberana. No desechéis mis súplicas, oh Madre del "
            "Verbo divino, antes bien escuchadlas y acogedlas benignamente. Amén."
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
    """1-based ISO week number. A one-line duplicate of poetry_catalog.py's
    identical helper rather than a shared import — these are two
    independent catalogs and this isn't worth coupling them over."""
    return (today or date.today()).isocalendar()[1]


def prayer_for_week(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> "dict | None":
    """
    The grade-filtered (falling back to stage-filtered) entry for the
    current calendar week. week_salt offsets the index — same convention
    as poetry_catalog.poem_for_week (ai_service.py passes the session's
    current_term so different families/demo visitors don't all land on the
    identical prayer in the same calendar week).
    """
    entries = _entries_for(grade, stage)
    if not entries:
        return None
    idx = (current_week(today) + week_salt - 1) % len(entries)
    return entries[idx]


def prayer_note(
    grade: "str | None", stage: GradeStage, locale: str = "en", week_salt: int = 0, today: "date | None" = None,
) -> str:
    """Prompt block for prayer recitation in Morning Time: this week's
    prayer, given VERBATIM in the deployment's locale, and how to lead it
    the Mater Amabilis way (reverent repetition toward memory, never a
    quiz, never scored — Bede's constitution treats a child's faith
    formation as something to nurture, not measure). Only "en" and "es"
    have translated text today; any other locale falls back to English
    until that language's text is drafted and reviewed, same incremental
    approach as the rest of this app's localization."""
    entry = prayer_for_week(grade, stage, week_salt, today)
    if not entry:
        return ""
    text = entry["text_es"] if locale == "es" else entry["text_en"]
    return f"""

<prayer_recitation>
This week's prayer for Morning Time is the "{entry['title']}" ({entry['attribution']}) — part of a
weekly rotation of the Church's own traditional prayers. The text below is given VERBATIM. When you
lead, quote, or teach this prayer, use EXACTLY the text below — never recite it from memory and
never paraphrase a line you present as the prayer itself.

{text}

How to lead prayer with a child (a minute or two, woven in naturally): pray a line, let the child
echo it back, and let repetition over many sessions build toward saying the whole prayer together
from memory. This is worship, not a memorization drill — keep the tone reverent and unhurried,
never a quiz, and never something you score or measure. A child who joins in for even one line is
a good and complete thing in itself.
</prayer_recitation>"""
