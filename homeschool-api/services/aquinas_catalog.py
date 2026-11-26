"""
St. Thomas Aquinas — fixed, pre-reviewed content for two subjects.

Owner ruling 2026-11-24: add Aquinas to Saints & Catechism, and give Logic an
early exposure to the Summa Theologiae. See docs/DECISIONS.md entry 47.

Two kinds of content live here, and they are deliberately different:

1. **His life** (`LIFE`), for Subject.saints. Facts only, each one checked
   against the sources in `SOURCES`. Where those sources disagree, the text
   says less rather than picking one: his birth year is given as "about
   1225" (sources say 1224 or 1225), and his family's keeping him at home is
   "a long time" (sources say one to two years).

2. **His argument**, for both subjects: the idea that the world points back
   to a first cause. This is a SIMPLIFIED RETELLING written for this project,
   NOT a quotation of the Summa, and every block says so. The source is
   Summa Theologiae, First Part, Question 2, Article 3, which a parent can
   look up in any translation. Quoting the Summa word for word needs the
   text checked against a published translation, which could not be fetched
   when this was written, so nothing here claims to be Aquinas's own words.

Why fixed text at all: the same reason as latin_catalog.py and
logic_catalog.py. A model retelling a famous argument from memory can drift
into a version Aquinas never made (the most common drift is "everything has a
cause, so God has a cause too", which is not his argument), and neither the
child nor most parents could catch it.
"""
from datetime import date

from models.schemas import GradeStage, grade_to_stage


# Every fact in LIFE was checked against these, and the text agrees with all
# of them (2026-11-24, via web search; see entry 47).
SOURCES = (
    "Encyclopaedia Britannica, 'Saint Thomas Aquinas'",
    "Vatican City State, Saint of the Day, 28 January: St. Thomas Aquinas, Doctor of the Church",
    "EWTN, 'Saint Thomas Aquinas, Confessor, Doctor of the Church'",
)

# The day his feast is kept (General Roman Calendar since 1969; formerly
# 7 March, the day he died).
FEAST_MONTH, FEAST_DAY = 1, 28

LIFE = (
    "Thomas was born about 1225 at Roccasecca, his family's castle in Italy, near the town of "
    "Aquino. His family was noble and hoped he would become abbot of the great monastery of "
    "Monte Cassino. Instead, as a "
    "young man he joined the Dominicans, a new order of friars who owned nothing, begged for "
    "their food, and spent their lives studying and preaching. His family was so against it that "
    "his brothers took him on the road and kept him shut away at the family castle for a long "
    "time. He would not give up, and in the end he was let go and returned to the friars. "
    "At school he was big and very quiet, so the other students called him \"the dumb ox.\" His "
    "teacher, St. Albert the Great, told them that one day this ox would bellow so loudly the "
    "whole world would hear him. Thomas became one of the greatest teachers the Church has ever "
    "had. His most famous book is the Summa Theologiae, a huge book of questions about God and "
    "everything God made, each one answered carefully. He died on 7 March 1274 at the abbey of "
    "Fossanova, before he finished it. The Church declared him a saint in 1323 and a Doctor of "
    "the Church in 1567. His feast day is 28 January, and he is the patron saint of Catholic schools."
)

# One concrete picture per stage. Each is a retelling, not a quotation; the
# rendered block says so and gives the reference.
_PICTURE = {
    GradeStage.foundations: (
        "K-2 — WONDER, NOT PROOF. Ask where things come from and follow the chain back with the "
        "child: the apple came from a tree, the tree came from a seed, the seed came from another "
        "tree... Ask: could it go back and back forever with nothing to start it? St. Thomas said "
        "there has to be a beginning that nothing else started, and that beginning is God, who "
        "made everything. Keep it to that one picture, and let the child's wonder do the work. "
        "Never call this a proof to a child this age, and never quiz them on it."
    ),
    GradeStage.core_mastery: (
        "3-5 — THE DOMINO CHAIN. Picture a long line of dominoes falling. Each one falls because "
        "the one before it pushed it. But a line of dominoes cannot start itself: something "
        "outside the line has to give the first push. St. Thomas looked at the world the same way. "
        "Things change and move because something else moves them, and that can't go back "
        "forever with no first push. So there must be a first mover that nothing else moves, "
        "which, he said, is what everyone means by God. Let the child explain the chain back in "
        "their own words before you add anything."
    ),
    GradeStage.independent: (
        "6-8 — THE FIVE WAYS, IN ONE LINE EACH. St. Thomas gave five ways of reasoning from the "
        "world to God: (1) from motion: things are moved by something else, and there must be a "
        "first mover; (2) from causes: things are caused by something else, and there must be a "
        "first cause; (3) from things that might not have existed: something must exist that "
        "cannot not exist; (4) from degrees: we see things more and less good and true, which "
        "points to something that is the best and truest; (5) from order: things without minds act "
        "for a purpose, which points to a mind that directs them. Take ONE way per lesson, the "
        "first or second to begin with. Make clear what St. Thomas did NOT say: not \"everything "
        "has a cause\" (which would make God need one too), but that the things we see are caused "
        "by something else, and the chain needs a beginning that is not caused. Explain why the "
        "first way holds: he means a chain where each thing moves only while it is being moved, "
        "like a hand moving a stick that moves a stone, and such a chain explains no motion at all "
        "without a first mover, however long it is (an endless train of carriages still needs an "
        "engine). It is about what keeps things moving now, not about how long ago the world began."
    ),
}

REFERENCE = "Summa Theologiae, First Part, Question 2, Article 3"


def _in_feast_week(today: "date | None") -> bool:
    """True in the calendar week (Monday to Sunday) that contains 28 January."""
    today = today or date.today()
    feast = date(today.year, FEAST_MONTH, FEAST_DAY)
    return today.isocalendar()[:2] == feast.isocalendar()[:2]


def saints_note(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> str:
    """The Subject.saints block for St. Thomas Aquinas.

    Always present, so Bede can tell his story whenever the family or the
    child asks about him, and promoted to the lesson's opening in the week of
    his feast. `week_salt` is accepted for the shared catalog-note signature
    and not used: a feast day does not rotate.
    """
    stage = grade_to_stage(grade) if grade else stage
    if _in_feast_week(today):
        when = (
            "THIS WEEK IS HIS FEAST (28 January). Open today's lesson with his story, unless the "
            "parent's own lesson note for today points somewhere else, which always wins."
        )
    else:
        when = (
            "Not his feast week. Tell his story when the family's lesson, a book they are "
            "reading, or the child's own question brings him up; do not steer a lesson to him "
            "on your own."
        )
    return f"""

<saint_thomas_aquinas>
{when}

HIS LIFE (checked facts; tell it as a story in your own words, and do not add details that are
not here):
{LIFE}

HIS BIG IDEA, AT THIS CHILD'S STAGE (a simplified retelling written for this lesson, NOT
Aquinas's own words; if a parent asks where it comes from, it is {REFERENCE}):
{_PICTURE[stage]}

RULES:
- Never present the retelling as a quotation of the Summa, and never quote the Summa from memory.
- This is the Church's teaching as St. Thomas gave it, told to a child with wonder. Teach it
  warmly and plainly, and explain why his reasoning holds rather than why it might fail; do not
  turn it into a debate, and do not quiz the child on it.
- What the child concludes and believes is their own, with their family. Help them, and their
  parent if they are there, think it through and reach their own conclusion freely: explain, never
  pressure, and never treat agreement as the goal.
- If the child has a hard question (for example, "then who made God?"), welcome it: St. Thomas
  welcomed every hard question. Give the simple answer the picture above already carries, and
  for anything deeper say it is a wonderful question to take to their parents or their priest.
- Invite narration of his story. `invite_handwriting` suits drawing the chain of dominoes or the
  seed-and-tree picture, or copying his name and feast day.
</saint_thomas_aquinas>"""
