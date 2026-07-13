"""
Poetry co-study catalog — public-domain poems with their EXACT text, so
Bede quotes and teaches recitation verbatim from a canonical source
instead of reciting from model memory (models can misquote long
passages, and recitation/copywork requires exact lines).

Starting rotation: Robert Louis Stevenson, "A Child's Garden of Verses"
(1885) — the canonical Charlotte Mason / Mater Amabilis starting poet.
Everything here is public domain; nothing is licensed. Additions should
follow the same shape (see docs and the poet list discussed in review:
Rossetti, Lear, Longfellow, Hopkins, ...) — one poet per term, a few
short poems per stage.

Injected into the morning_time and living_books subject prompts by
services/ai_service.py's _poetry_note(). Kept deliberately small (a few
short poems per stage) so the subject prompt stays lean.
"""
from models.schemas import GradeStage

_POET = "Robert Louis Stevenson"
_COLLECTION = "A Child's Garden of Verses (1885)"

# Short, complete poems — chosen for recitation length by stage.
_POEMS = {
    "rls_rain": {
        "title": "Rain",
        "stages": {GradeStage.foundations},
        "text": (
            "The rain is raining all around,\n"
            "It falls on field and tree,\n"
            "It rains on the umbrellas here,\n"
            "And on the ships at sea."
        ),
    },
    "rls_time_to_rise": {
        "title": "Time to Rise",
        "stages": {GradeStage.foundations},
        "text": (
            "A birdie with a yellow bill\n"
            "Hopped upon the window sill,\n"
            "Cocked his shining eye and said:\n"
            "\"Ain't you 'shamed, you sleepy-head!\""
        ),
    },
    "rls_the_swing": {
        "title": "The Swing",
        "stages": {GradeStage.foundations, GradeStage.core_mastery},
        "text": (
            "How do you like to go up in a swing,\n"
            "Up in the air so blue?\n"
            "Oh, I do think it the pleasantest thing\n"
            "Ever a child can do!\n"
            "\n"
            "Up in the air and over the wall,\n"
            "Till I can see so wide,\n"
            "Rivers and trees and cattle and all\n"
            "Over the countryside—\n"
            "\n"
            "Till I look down on the garden green,\n"
            "Down on the roof so brown—\n"
            "Up in the air I go flying again,\n"
            "Up in the air and down!"
        ),
    },
    "rls_bed_in_summer": {
        "title": "Bed in Summer",
        "stages": {GradeStage.foundations, GradeStage.core_mastery},
        "text": (
            "In winter I get up at night\n"
            "And dress by yellow candle-light.\n"
            "In summer, quite the other way,\n"
            "I have to go to bed by day.\n"
            "\n"
            "I have to go to bed and see\n"
            "The birds still hopping on the tree,\n"
            "Or hear the grown-up people's feet\n"
            "Still going past me in the street.\n"
            "\n"
            "And does it not seem hard to you,\n"
            "When all the sky is clear and blue,\n"
            "And I should like so much to play,\n"
            "To have to go to bed by day?"
        ),
    },
    "rls_my_shadow": {
        "title": "My Shadow",
        "stages": {GradeStage.core_mastery, GradeStage.independent},
        "text": (
            "I have a little shadow that goes in and out with me,\n"
            "And what can be the use of him is more than I can see.\n"
            "He is very, very like me from the heels up to the head;\n"
            "And I see him jump before me, when I jump into my bed.\n"
            "\n"
            "The funniest thing about him is the way he likes to grow—\n"
            "Not at all like proper children, which is always very slow;\n"
            "For he sometimes shoots up taller like an india-rubber ball,\n"
            "And he sometimes gets so little that there's none of him at all.\n"
            "\n"
            "He hasn't got a notion of how children ought to play,\n"
            "And can only make a fool of me in every sort of way.\n"
            "He stays so close beside me, he's a coward you can see;\n"
            "I'd think shame to stick to nursie as that shadow sticks to me!\n"
            "\n"
            "One morning, very early, before the sun was up,\n"
            "I rose and found the shining dew on every buttercup;\n"
            "But my lazy little shadow, like an arrant sleepy-head,\n"
            "Had stayed at home behind me and was fast asleep in bed."
        ),
    },
    "rls_where_go_the_boats": {
        "title": "Where Go the Boats?",
        "stages": {GradeStage.core_mastery, GradeStage.independent},
        "text": (
            "Dark brown is the river,\n"
            "Golden is the sand.\n"
            "It flows along for ever,\n"
            "With trees on either hand.\n"
            "\n"
            "Green leaves a-floating,\n"
            "Castles of the foam,\n"
            "Boats of mine a-boating—\n"
            "Where will all come home?\n"
            "\n"
            "On goes the river\n"
            "And out past the mill,\n"
            "Away down the valley,\n"
            "Away down the hill.\n"
            "\n"
            "Away down the river,\n"
            "A hundred miles or more,\n"
            "Other little children\n"
            "Shall bring my boats ashore."
        ),
    },
}


def poems_for_stage(stage: GradeStage) -> list[dict]:
    return [
        {"id": pid, "title": p["title"], "text": p["text"]}
        for pid, p in _POEMS.items()
        if stage in p["stages"]
    ]


def poetry_note(stage: GradeStage) -> str:
    """Prompt block for poetry co-study in morning_time / living_books.
    Returns the term poet, this stage's poems verbatim, and how to teach
    them the Mater Amabilis way (co-study and gentle recitation, never a
    quiz)."""
    poems = poems_for_stage(stage)
    if not poems:
        return ""
    poem_blocks = "\n\n".join(f'"{p["title"]}"\n{p["text"]}' for p in poems)
    return f"""

<poetry_co_study>
This term's poet is {_POET} — {_COLLECTION}, chosen per Mater Amabilis practice of living with one
poet at a time. The poems below are this child's stage selection, given VERBATIM. When you read,
quote, or teach any line of these poems, use EXACTLY the text below — never recite them from memory
and never paraphrase a line you present as the poem itself.

{poem_blocks}

How to co-study a poem (a few minutes, woven in where it fits — not a lecture):
read a stanza aloud together, wonder about one image in it ("What do you see when he says...?"),
let the child echo a favorite line, and connect it to the child's own day where that happens
naturally. Over several sessions, gently build toward the child saying a whole poem from memory —
one or two lines at a time, always as delight, never as a quiz. A recited line is a fine thing to
celebrate.
</poetry_co_study>"""
