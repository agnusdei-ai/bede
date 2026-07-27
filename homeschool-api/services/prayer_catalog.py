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

_DAILY_COLLECTION (below) is a second, separate catalog backing the day's
opening/closing prayer moment (services/ai_service.py's Sacred Rule 10) —
added specifically so Bede never composes that prayer itself. Before this,
Bede was instructed to "freshly adapt" an opening/closing prayer each
session; a growing homeschool family raised, correctly, that a model
improvising devotional wording every day — with no human ever reviewing
what it actually said — is not something a family building toward
diocesan/parish endorsement can stand behind, however well-intentioned the
result usually is. This catalog closes that gap the same way _COLLECTION
already closed it for memory-work recitation: a fixed, reviewed set of
real, traditionally-attested prayers Bede selects and quotes VERBATIM,
never invents. Per the parent's own direction, it deliberately spans both
Catholic devotional prayers and prayers in wider ecumenical Christian use
(the Doxology, the Serenity Prayer, the Numbers 6:24-26 blessing, "Now I
Lay Me Down to Sleep") — all doctrinally uncontroversial, Trinitarian
where applicable, and none requiring Bede to adjudicate a denominational
question to use. Same transcription caveat as _COLLECTION above: treat
every entry (English and especially the Spanish renderings, several of
which are this session's own translation rather than a cross-checked
published source) as a first pass worth a parish/native-speaker review
before a family relies on it.
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


def _daily_entry(
    title: str, attribution: str, tradition: str, moments: set, text_en: str, text_es: str,
) -> dict:
    return {
        "title": title,
        "attribution": attribution,
        "tradition": tradition,  # "catholic" | "christian" (wider ecumenical Christian use)
        "moments": moments,  # subset of {"opening", "closing"}
        "text_en": text_en,
        "text_es": text_es,
    }


# Backs the day's opening/closing prayer moment only (Sacred Rule 10 in
# services/ai_service.py) — see this module's own docstring for why this is
# a separate catalog from _COLLECTION above, not just an entry in it: these
# are short enough for daily reuse across every grade, and several are
# non-Catholic Christian prayers in wider ecumenical use, which _COLLECTION's
# own scope (universally standardized CATHOLIC prayers) deliberately excludes.
_DAILY_COLLECTION = [
    _daily_entry(
        "Come, Holy Spirit", "Traditional", "catholic", {"opening"},
        (
            "Come, Holy Spirit, fill the hearts of your faithful and kindle in them the fire of "
            "your love. Send forth your Spirit and they shall be created. And You shall renew the "
            "face of the earth. Amen."
        ),
        (
            "Ven, Espíritu Santo, llena los corazones de tus fieles y enciende en ellos el fuego de "
            "tu amor. Envía tu Espíritu y todo será creado. Y renovarás la faz de la tierra. Amén."
        ),
    ),
    _daily_entry(
        "Prayer Before Study", "Traditional (attrib. St. Thomas Aquinas)", "catholic", {"opening"},
        (
            "Creator of all things, true source of light and wisdom, origin of all being, "
            "graciously let a ray of your light penetrate the darkness of my understanding. Give me "
            "a sharp sense of understanding, a retentive memory, and the ability to grasp things "
            "correctly and fundamentally. Point out the beginning, direct the progress, and help in "
            "the completion. I ask this through Christ our Lord. Amen."
        ),
        (
            "Creador de todas las cosas, verdadera fuente de luz y sabiduría, origen de todo ser: "
            "te suplico que hagas penetrar un rayo de tu luz en la oscuridad de mi entendimiento. "
            "Dame agudeza para entender, capacidad para retener, y método y facilidad para "
            "aprender. Señala el comienzo, dirige el progreso y ayuda a la conclusión. Te lo pido "
            "por Cristo, nuestro Señor. Amén."
        ),
    ),
    _daily_entry(
        "Prayer of St. Francis", "Traditional (long attributed to St. Francis of Assisi)", "catholic", {"closing"},
        (
            "Lord, make me an instrument of your peace. Where there is hatred, let me sow love; "
            "where there is injury, pardon; where there is doubt, faith; where there is despair, "
            "hope; where there is darkness, light; where there is sadness, joy. Amen."
        ),
        (
            "Señor, hazme un instrumento de tu paz. Donde haya odio, que yo ponga amor; donde haya "
            "ofensa, perdón; donde haya duda, fe; donde haya desesperación, esperanza; donde haya "
            "oscuridad, luz; donde haya tristeza, alegría. Amén."
        ),
    ),
    _daily_entry(
        "Glory Be (Doxology)", "Traditional", "catholic", {"closing"},
        (
            "Glory be to the Father, and to the Son, and to the Holy Spirit, as it was in the "
            "beginning, is now, and ever shall be, world without end. Amen."
        ),
        (
            "Gloria al Padre, y al Hijo, y al Espíritu Santo. Como era en el principio, ahora y "
            "siempre, por los siglos de los siglos. Amén."
        ),
    ),
    _daily_entry(
        "The Doxology", "Thomas Ken, 1674 (traditional Protestant hymn verse)", "christian", {"closing"},
        (
            "Praise God, from whom all blessings flow; praise Him, all creatures here below; "
            "praise Him above, ye heavenly host; praise Father, Son, and Holy Ghost. Amen."
        ),
        (
            "Alaben a Dios, de quien fluyen todas las bendiciones; alábenlo, todas las criaturas de "
            "la tierra; alábenlo en las alturas, huestes celestiales; alaben al Padre, al Hijo y al "
            "Espíritu Santo. Amén."
        ),
    ),
    _daily_entry(
        "The Serenity Prayer", "Reinhold Niebuhr, c. 1930s (traditional, wide ecumenical Christian use)",
        "christian", {"opening"},
        (
            "God, grant me the serenity to accept the things I cannot change, courage to change the "
            "things I can, and wisdom to know the difference."
        ),
        (
            "Señor, concédeme serenidad para aceptar las cosas que no puedo cambiar, valor para "
            "cambiar las cosas que puedo, y sabiduría para reconocer la diferencia."
        ),
    ),
    _daily_entry(
        "The Blessing (Numbers 6:24-26)", "Scripture, traditional English liturgical rendering",
        "christian", {"closing"},
        (
            "The Lord bless you and keep you; the Lord make his face shine upon you and be "
            "gracious to you; the Lord turn his face toward you and give you peace. Amen."
        ),
        (
            "El Señor te bendiga y te guarde; el Señor haga resplandecer su rostro sobre ti y "
            "tenga de ti misericordia; el Señor alce sobre ti su rostro y te dé paz. Amén."
        ),
    ),
    _daily_entry(
        "Now I Lay Me Down to Sleep", "Traditional (The New England Primer, 18th c.; wide ecumenical Christian use)",
        "christian", {"closing"},
        (
            "Now I lay me down to sleep, I pray the Lord my soul to keep. If I die before I wake, "
            "I pray the Lord my soul to take. Amen."
        ),
        (
            "Ahora que me acuesto a dormir, pido al Señor que cuide mi alma. Si muero antes de "
            "despertar, pido al Señor que lleve mi alma. Amén."
        ),
    ),
]


def daily_prayer_for(moment: str, week_salt: int = 0, today: "date | None" = None) -> "dict | None":
    """
    The entry for today's opening or closing prayer moment. Rotates by
    calendar DAY, not week — unlike _COLLECTION's memory-work rotation,
    this catalog backs a moment that recurs every single session day, so a
    week-long rotation would repeat the identical prayer seven days
    running. week_salt offsets the index — same per-session-offset
    convention as prayer_for_week/poem_for_week, so different families/
    demo visitors don't all land on the same pick the same day.
    """
    entries = [e for e in _DAILY_COLLECTION if moment in e["moments"]]
    if not entries:
        return None
    idx = ((today or date.today()).toordinal() + week_salt) % len(entries)
    return entries[idx]


def daily_prayer_note(
    moment: str, locale: str = "en", week_salt: int = 0, today: "date | None" = None,
) -> str:
    """
    Prompt block for Sacred Rule 10's opening/closing prayer: today's pick,
    given VERBATIM in the deployment's locale, with an explicit instruction
    that Bede is selecting and quoting it, never composing it. Only "en"
    and "es" have translated text today; any other locale falls back to
    English, same incremental-localization convention as prayer_note above.
    """
    entry = daily_prayer_for(moment, week_salt, today)
    if not entry:
        return ""
    text = entry["text_es"] if locale == "es" else entry["text_en"]
    moment_label = "opening" if moment == "opening" else "closing"
    return f"""

<daily_prayer moment="{moment_label}">
Today's {moment_label} prayer is the "{entry['title']}" ({entry['attribution']}) — drawn from a rotating \
database of traditional Catholic and Christian prayers, not composed by you. The text below is given \
VERBATIM. Introduce it in one short, warm sentence naming what it's for, then give EXACTLY the text below \
as the prayer itself — never compose, paraphrase, or improvise a prayer of your own, and never blend it \
with invented lines of your own.

{text}
</daily_prayer>"""


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
