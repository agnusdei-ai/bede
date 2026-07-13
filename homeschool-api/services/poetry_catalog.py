"""
Poetry co-study catalog — public-domain poems with their EXACT text, so
Bede quotes and teaches recitation verbatim from a canonical source
instead of reciting from model memory (models can misquote long
passages, and recitation/copywork requires exact lines).

Rotation follows Mater Amabilis practice of living with ONE poet per
term. The parent's term schedule (SessionConfig.term_schedule) picks the
rotation length: trimester years rotate three poets, quarterly years
four. Everything here is public domain; nothing is licensed.

    Term/Quarter 1 — Robert Louis Stevenson, A Child's Garden of Verses (1885)
    Term/Quarter 2 — Christina Rossetti, Sing-Song and other poems (1872)
    Term/Quarter 3 — Henry Wadsworth Longfellow (1839-1845)
    Quarter 4      — William Blake, Songs of Innocence (1789)

Injected into the morning_time and living_books subject prompts by
services/ai_service.py. Each poet carries a few short poems keyed by
grade stage so the subject prompt stays lean.
"""
from models.schemas import GradeStage, TermSchedule

_F = GradeStage.foundations
_C = GradeStage.core_mastery
_I = GradeStage.independent


def _poem(title: str, stages: set, text: str) -> dict:
    return {"title": title, "stages": stages, "text": text}


_ROTATION = [
    {
        "poet": "Robert Louis Stevenson",
        "collection": "A Child's Garden of Verses (1885)",
        "poems": [
            _poem("Rain", {_F}, (
                "The rain is raining all around,\n"
                "It falls on field and tree,\n"
                "It rains on the umbrellas here,\n"
                "And on the ships at sea."
            )),
            _poem("Time to Rise", {_F}, (
                "A birdie with a yellow bill\n"
                "Hopped upon the window sill,\n"
                "Cocked his shining eye and said:\n"
                "\"Ain't you 'shamed, you sleepy-head!\""
            )),
            _poem("The Swing", {_F, _C}, (
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
            )),
            _poem("Bed in Summer", {_F, _C}, (
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
            )),
            _poem("My Shadow", {_C, _I}, (
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
            )),
            _poem("Where Go the Boats?", {_C, _I}, (
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
            )),
        ],
    },
    {
        "poet": "Christina Rossetti",
        "collection": "Sing-Song and other poems (1872)",
        "poems": [
            _poem("The Caterpillar", {_F}, (
                "Brown and furry\n"
                "Caterpillar in a hurry,\n"
                "Take your walk\n"
                "To the shady leaf, or stalk,\n"
                "Or what not,\n"
                "Which may be the chosen spot.\n"
                "No toad spy you,\n"
                "Hovering bird of prey pass by you;\n"
                "Spin and die,\n"
                "To live again a butterfly."
            )),
            _poem("Hurt No Living Thing", {_F}, (
                "Hurt no living thing:\n"
                "Ladybird, nor butterfly,\n"
                "Nor moth with dusty wing,\n"
                "Nor cricket chirping cheerily,\n"
                "Nor grasshopper so light of leap,\n"
                "Nor dancing gnat, nor beetle fat,\n"
                "Nor harmless worms that creep."
            )),
            _poem("Who Has Seen the Wind?", {_F, _C}, (
                "Who has seen the wind?\n"
                "Neither I nor you:\n"
                "But when the leaves hang trembling,\n"
                "The wind is passing through.\n"
                "\n"
                "Who has seen the wind?\n"
                "Neither you nor I:\n"
                "But when the trees bow down their heads,\n"
                "The wind is passing by."
            )),
            _poem("What Is Pink?", {_F, _C}, (
                "What is pink? a rose is pink\n"
                "By a fountain's brink.\n"
                "What is red? a poppy's red\n"
                "In its barley bed.\n"
                "What is blue? the sky is blue\n"
                "Where the clouds float thro'.\n"
                "What is white? a swan is white\n"
                "Sailing in the light.\n"
                "What is yellow? pears are yellow,\n"
                "Rich and ripe and mellow.\n"
                "What is green? the grass is green,\n"
                "With small flowers between.\n"
                "What is violet? clouds are violet\n"
                "In the summer twilight.\n"
                "What is orange? Why, an orange,\n"
                "Just an orange!"
            )),
            _poem("Up-Hill", {_C, _I}, (
                "Does the road wind up-hill all the way?\n"
                "   Yes, to the very end.\n"
                "Will the day's journey take the whole long day?\n"
                "   From morn to night, my friend.\n"
                "\n"
                "But is there for the night a resting-place?\n"
                "   A roof for when the slow dark hours begin.\n"
                "May not the darkness hide it from my face?\n"
                "   You cannot miss that inn.\n"
                "\n"
                "Shall I meet other wayfarers at night?\n"
                "   Those who have gone before.\n"
                "Then must I knock, or call when just in sight?\n"
                "   They will not keep you standing at that door.\n"
                "\n"
                "Shall I find comfort, travel-sore and weak?\n"
                "   Of labour you shall find the sum.\n"
                "Will there be beds for me and all who seek?\n"
                "   Yea, beds for all who come."
            )),
        ],
    },
    {
        "poet": "Henry Wadsworth Longfellow",
        "collection": "selected poems (1839-1845)",
        "poems": [
            _poem("The Arrow and the Song", {_F, _C, _I}, (
                "I shot an arrow into the air,\n"
                "It fell to earth, I knew not where;\n"
                "For, so swiftly it flew, the sight\n"
                "Could not follow it in its flight.\n"
                "\n"
                "I breathed a song into the air,\n"
                "It fell to earth, I knew not where;\n"
                "For who has sight so keen and strong,\n"
                "That it can follow the flight of song?\n"
                "\n"
                "Long, long afterward, in an oak\n"
                "I found the arrow, still unbroke;\n"
                "And the song, from beginning to end,\n"
                "I found again in the heart of a friend."
            )),
            _poem("A Psalm of Life (opening stanzas)", {_C, _I}, (
                "Tell me not, in mournful numbers,\n"
                "   Life is but an empty dream!—\n"
                "For the soul is dead that slumbers,\n"
                "   And things are not what they seem.\n"
                "\n"
                "Life is real! Life is earnest!\n"
                "   And the grave is not its goal;\n"
                "Dust thou art, to dust returnest,\n"
                "   Was not spoken of the soul.\n"
                "\n"
                "Lives of great men all remind us\n"
                "   We can make our lives sublime,\n"
                "And, departing, leave behind us\n"
                "   Footprints on the sands of time."
            )),
        ],
    },
    {
        "poet": "William Blake",
        "collection": "Songs of Innocence (1789)",
        "poems": [
            _poem("The Shepherd", {_F}, (
                "How sweet is the Shepherd's sweet lot!\n"
                "From the morn to the evening he strays;\n"
                "He shall follow his sheep all the day,\n"
                "And his tongue shall be filled with praise.\n"
                "\n"
                "For he hears the lamb's innocent call,\n"
                "And he hears the ewe's tender reply;\n"
                "He is watchful while they are in peace,\n"
                "For they know when their Shepherd is nigh."
            )),
            _poem("The Lamb", {_F, _C}, (
                "Little Lamb, who made thee?\n"
                "Dost thou know who made thee?\n"
                "Gave thee life, and bid thee feed,\n"
                "By the stream and o'er the mead;\n"
                "Gave thee clothing of delight,\n"
                "Softest clothing, woolly, bright;\n"
                "Gave thee such a tender voice,\n"
                "Making all the vales rejoice?\n"
                "Little Lamb, who made thee?\n"
                "Dost thou know who made thee?\n"
                "\n"
                "Little Lamb, I'll tell thee,\n"
                "Little Lamb, I'll tell thee:\n"
                "He is called by thy name,\n"
                "For He calls Himself a Lamb.\n"
                "He is meek, and He is mild;\n"
                "He became a little child.\n"
                "I a child, and thou a lamb,\n"
                "We are called by His name.\n"
                "Little Lamb, God bless thee!\n"
                "Little Lamb, God bless thee!"
            )),
            _poem("The Tyger (opening and closing stanzas)", {_C, _I}, (
                "Tyger! Tyger! burning bright\n"
                "In the forests of the night,\n"
                "What immortal hand or eye\n"
                "Could frame thy fearful symmetry?\n"
                "\n"
                "When the stars threw down their spears,\n"
                "And water'd heaven with their tears,\n"
                "Did he smile his work to see?\n"
                "Did he who made the Lamb make thee?\n"
                "\n"
                "Tyger! Tyger! burning bright\n"
                "In the forests of the night,\n"
                "What immortal hand or eye,\n"
                "Dare frame thy fearful symmetry?"
            )),
        ],
    },
]


def poet_for_term(schedule: TermSchedule, current_term: int) -> dict:
    """One poet per term. Trimester years rotate the first three poets;
    quarterly years all four. current_term is 1-based and already capped
    by SessionConfig validation."""
    rotation_len = 3 if schedule == TermSchedule.trimester else 4
    idx = (max(1, current_term) - 1) % rotation_len
    return _ROTATION[idx]


def poems_for_stage(poet: dict, stage: GradeStage) -> list[dict]:
    return [
        {"title": p["title"], "text": p["text"]}
        for p in poet["poems"]
        if stage in p["stages"]
    ]


def poetry_note(stage: GradeStage, schedule: TermSchedule, current_term: int) -> str:
    """Prompt block for poetry co-study in morning_time / living_books:
    the current term's poet, this stage's poems verbatim, and how to
    teach them the Mater Amabilis way (co-study and gentle recitation,
    never a quiz)."""
    poet = poet_for_term(schedule, current_term)
    poems = poems_for_stage(poet, stage)
    if not poems:
        return ""
    term_word = "term" if schedule == TermSchedule.trimester else "quarter"
    poem_blocks = "\n\n".join(f'"{p["title"]}"\n{p["text"]}' for p in poems)
    return f"""

<poetry_co_study>
This {term_word}'s poet is {poet["poet"]} — {poet["collection"]}, chosen per Mater Amabilis practice
of living with one poet at a time. The poems below are this child's stage selection, given VERBATIM.
When you read, quote, or teach any line of these poems, use EXACTLY the text below — never recite
them from memory and never paraphrase a line you present as the poem itself.

{poem_blocks}

How to co-study a poem (a few minutes, woven in where it fits — not a lecture):
read a stanza aloud together, wonder about one image in it ("What do you see when he says...?"),
let the child echo a favorite line, and connect it to the child's own day where that happens
naturally. Over several sessions, gently build toward the child saying a whole poem from memory —
one or two lines at a time, always as delight, never as a quiz. A recited line is a fine thing to
celebrate.
</poetry_co_study>"""
