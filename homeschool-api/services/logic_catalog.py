"""
Logic — the content behind Subject.logic. The label is "Logic", not "Logic
& Clear Thinking": clear thinking is what the subject produces in a
student who studies it well, not part of the subject's own name.

WHY THIS EXISTS. `GradeStage.core_mastery` and `GradeStage.independent` are
labelled in models/schemas.py as the Logic stage and the Rhetoric stage,
and _STAGE_GUIDANCE calls the latter "the crown of the trivium" — but
until this module nothing in the app actually taught reasoning. A student
got Socratic questioning without ever being told what makes an argument
work. This closes the gap the trivium's own vocabulary had been promising.

NOT K-2, AND THAT IS ENFORCED IN THREE PLACES, NOT ASSUMED. Formal logic
before the Logic stage is exactly the premature abstraction classical
education warns against; a Grammar-stage child is gathering the world, not
auditing it. So `SessionConfig._validate_logic_stage` drops the subject for
a foundations-stage student, `ParentSetup.tsx` never offers the card, and
data/catalog/year{1,2}.json deliberately carry no logic plan. Prompt text
alone would not have been enough — this is the first stage-gated SUBJECT
in the app (phonics is a stage-gated NOTE inside language_arts, which is
not the same thing).

FIXED EXAMPLES, NOT IMPROVISED ONES — the same rule as
services/latin_catalog.py, for a reason that is, if anything, sharper here.
A language model asked to invent a syllogism will sometimes produce an
invalid one and label it valid, or an invalid form that happens to have a
true conclusion and call that a proof. A child cannot catch either error;
that is the whole reason they are in the subject. Every syllogism and every
fallacy example below is fixed, worked out, and labelled with WHY it holds
or fails, and the prompt block tells Bede to reason from these rather than
generate new ones.

THE TWO GUARDRAILS THAT MATTER MOST. Neither is decoration:

  1. **Logic serves truth and charity, never winning.** A child newly armed
     with "that's an ad hominem" has been handed a weapon, and the obvious
     first target is their own parents. The classical tradition is explicit
     that dialectic serves truth, and the constitution
     (constitution/bede.constitution.json) makes Love "the final measure of
     every response, recommendation, and judgment" — which governs this
     subject more directly than any other. The block says so, repeatedly,
     and tells Bede to redirect rather than coach when a child starts
     hunting for fallacies in what their parents told them.
  2. **Bede does not adjudicate contested claims.** A logic subject invites
     "is THIS argument good?" about live political and religious disputes,
     and a tutor that starts ruling on those has quietly become something
     the constitution forbids it to be. Bede teaches the FORM using the
     neutral examples below, and sends the substance of a contested
     question back to the family — the same boundary the faith modules
     already keep.

Examples throughout are deliberately dull: weather, animals, chores,
homework. That is a feature. An example with real stakes teaches the stakes
rather than the form.

One deliberate exception (owner ruling 2026-11-24, docs/DECISIONS.md entry
47): `_SUMMA_ARTICLES`, an early exposure to St. Thomas Aquinas's Summa at
6-8, worked on his article "Whether God exists?". It keeps rule 2 above by
construction: it teaches the SHAPE of a disputed question (objections stated
fairly first, then the answer, then a reply to each objection), Bede gives
no verdict on whether the argument succeeds, and the substance goes home.
"""
from datetime import date

from models.schemas import GradeStage, grade_to_stage

# Deliberately excludes GradeStage.foundations everywhere in this module.
# See the docstring — the exclusion is the design, not an oversight.
_FROM_3 = {GradeStage.core_mastery, GradeStage.independent}
_FROM_6 = {GradeStage.independent}


def _move(move_id: str, name: str, question: str, why: str, example: str) -> dict:
    """A 3-5 informal reasoning move — a habit of mind, phrased as the
    question a child actually asks, not a technical term to memorize."""
    return {
        "move_id": move_id, "name": name, "question": question,
        "why": why, "example": example, "stages": _FROM_3,
    }


_MOVES = [
    _move(
        "always_or_sometimes", "Always, or just sometimes?",
        "\"Is that true every single time, or only some of the time?\"",
        "The difference between a rule and a coincidence. Most arguments that go wrong go wrong "
        "right here — someone noticed something twice and started treating it as always.",
        "\"Dogs bark.\" Do ALL dogs bark? Do they bark ALL the time? What would we have to check?",
    ),
    _move(
        "how_do_you_know", "How do you know?",
        "\"What makes you think so?\"",
        "The difference between believing something and having a reason for it. Asked kindly, this "
        "is the single most useful question in the subject.",
        "\"It's going to rain.\" How do you know? Did you see clouds, hear a forecast, or feel it?",
    ),
    _move(
        "reason_or_restatement", "Is that a reason, or just saying it again?",
        "\"You told me WHAT you think — did you tell me WHY?\"",
        "Children (and adults) often repeat a claim more loudly instead of supporting it. Naming "
        "the difference is most of the work.",
        "\"Broccoli is gross because it's disgusting.\" That is the same sentence twice. What "
        "about it — the taste, the smell, the way it looks?",
    ),
    _move(
        "after_is_not_because", "Happening after isn't the same as being caused by",
        "\"Did it happen BECAUSE of that, or just AFTER it?\"",
        "The first real distinction between correlation and cause, in language a nine-year-old "
        "owns immediately.",
        "\"I wore my red socks and we won the game.\" Did the socks help? How could we find out?",
    ),
    _move(
        "both_cant_be_true", "Both of those can't be true",
        "\"Wait — you said two things that can't both be right. Which one do you mean?\"",
        "Noticing a contradiction is the seed of all formal logic, and a child can do it long "
        "before they can name it.",
        "\"Nobody in my class likes math, and my friend Sam loves math.\" Both can't be so.",
    ),
    _move(
        "what_would_change", "What would change your mind?",
        "\"If you're right, what would we expect to see? What if we saw the opposite?\"",
        "Teaches that a belief worth holding is one that could, in principle, be checked — and "
        "gently exposes a claim built so it can never be wrong.",
        "\"My plant grows faster with music.\" What would we see if that were false?",
    ),
    # Owner ruling 2026-11-24 (docs/DECISIONS.md entry 47): early exposure to
    # the Summa. At 3-5 that is the HABIT the Summa is built on, not its
    # content, so the example stays as dull as every other one here.
    _move(
        "best_reason_against", "What's the best reason against?",
        "\"Before you give your answer, what's the best reason someone might disagree?\"",
        "St. Thomas Aquinas wrote his greatest book this way: before he gave his own answer to "
        "any question, he wrote down the strongest reasons against it, fairly, and then answered "
        "each one. Saying the other side well first is how you find out whether your own answer "
        "really holds, and it is kind to the person who disagrees.",
        "\"We should walk to the park instead of riding bikes.\" What's the best reason someone "
        "might say bikes are better? Can you say it so well they'd agree you got it right?",
    ),
]


def _fallacy(fallacy_id: str, name: str, definition: str, example: str, why_it_fails: str) -> dict:
    return {
        "fallacy_id": fallacy_id, "name": name, "definition": definition,
        "example": example, "why_it_fails": why_it_fails, "stages": _FROM_6,
    }


# Neutral examples on purpose — see the module docstring. None of these is
# drawn from family life, politics, or religion.
_FALLACIES = [
    _fallacy(
        "ad_hominem", "Ad hominem (\"to the person\")",
        "Attacking the person making an argument instead of the argument itself.",
        "\"You can't trust his report on the water cycle — he's terrible at spelling.\"",
        "Whether the report is right about the water cycle has nothing to do with his spelling. "
        "The argument was never answered, only the arguer.",
    ),
    _fallacy(
        "straw_man", "Straw man",
        "Replacing someone's actual argument with a weaker one that is easier to knock down, then "
        "knocking that down instead.",
        "\"She said we should read more before bed. So she thinks we should never sleep!\"",
        "She never said that. Beating an argument nobody made proves nothing about the one that "
        "was made.",
    ),
    _fallacy(
        "false_dilemma", "False dilemma",
        "Presenting only two choices when more exist.",
        "\"Either we finish the whole book tonight or we've wasted the whole week.\"",
        "There are obviously other possibilities — finishing half, finishing tomorrow. A real "
        "either/or has to actually exhaust the options.",
    ),
    _fallacy(
        "post_hoc", "Post hoc ergo propter hoc (\"after this, therefore because of this\")",
        "Assuming that because one thing followed another, the first caused the second.",
        "\"I sharpened my pencil and then got the answer right, so sharpening it helped.\"",
        "Order in time is not causation. The same reasoning would make every rooster responsible "
        "for the sunrise.",
    ),
    _fallacy(
        "circular", "Circular reasoning (begging the question)",
        "Using the conclusion as one of the reasons for the conclusion.",
        "\"This is the best map because no other map is as good as this one.\"",
        "The reason and the claim are the same sentence wearing different clothes. Nothing has "
        "been offered that someone who disagreed could examine.",
    ),
    _fallacy(
        "hasty_generalization", "Hasty generalization",
        "Drawing a broad conclusion from too few cases.",
        "\"Both robins I saw today were on the ground, so robins don't perch in trees.\"",
        "Two birds is not enough to establish what all robins do. This is the grown-up version of "
        "\"always, or just sometimes?\"",
    ),
    _fallacy(
        "ad_populum", "Appeal to popularity (ad populum)",
        "Treating something as true because many people believe it.",
        "\"Everyone in the co-op says this is the hardest math book, so it must be.\"",
        "How many people hold a view is evidence about the people, not about the thing. Popular "
        "beliefs have been wrong, and unpopular ones right.",
    ),
    _fallacy(
        "equivocation", "Equivocation",
        "Using one word in two different senses inside the same argument, as if it meant the same "
        "thing both times.",
        "\"A feather is light. Light things are not dark. So a feather is not dark.\"",
        "\"Light\" means not-heavy the first time and not-dark the second. The argument only looks "
        "like it works because the word held still while its meaning moved.",
    ),
]


def _syllogism(
    syllogism_id: str, premises: list, conclusion: str, verdict: str, why: str,
) -> dict:
    return {
        "syllogism_id": syllogism_id, "premises": premises, "conclusion": conclusion,
        "verdict": verdict, "why": why, "stages": _FROM_6,
    }


# Fixed and worked out — never generated at runtime. See the docstring on
# why an improvised syllogism is a real hazard rather than a theoretical
# one. Each verdict is either "valid", "invalid", or the third case that
# matters most pedagogically: valid form, false premise.
_SYLLOGISMS = [
    _syllogism(
        "barbara",
        ["All men are mortal.", "Socrates is a man."],
        "Therefore Socrates is mortal.",
        "valid",
        "The classic. If both premises are true, the conclusion cannot be false — that is exactly "
        "what validity means.",
    ),
    _syllogism(
        "modus_ponens",
        ["If it is raining, the ground is wet.", "It is raining."],
        "Therefore the ground is wet.",
        "valid",
        "Affirming the 'if' part lets you affirm the 'then' part. One of the two safe moves.",
    ),
    _syllogism(
        "modus_tollens",
        ["If it is raining, the ground is wet.", "The ground is not wet."],
        "Therefore it is not raining.",
        "valid",
        "Denying the 'then' part lets you deny the 'if' part. The other safe move — and the "
        "harder one to see, which is why it is worth practising.",
    ),
    _syllogism(
        "affirming_consequent",
        ["If it is raining, the ground is wet.", "The ground is wet."],
        "Therefore it is raining.",
        "invalid",
        "INVALID, and the most common mistake there is. The ground could be wet from a sprinkler, "
        "a hose, or a spilled bucket. The first premise never said rain was the ONLY thing that "
        "wets the ground.",
    ),
    _syllogism(
        "denying_antecedent",
        ["If it is raining, the ground is wet.", "It is not raining."],
        "Therefore the ground is not wet.",
        "invalid",
        "INVALID, and the mirror image of the mistake above. Again: rain is not the only way for "
        "the ground to get wet.",
    ),
    _syllogism(
        "valid_but_false",
        ["All birds can fly.", "A penguin is a bird."],
        "Therefore a penguin can fly.",
        "valid form, false premise",
        "The most important example in the whole subject. The FORM is perfect — if both premises "
        "were true the conclusion would follow. But the first premise is false, so the conclusion "
        "is false too. Valid does not mean true. An argument can be built correctly out of bad "
        "materials, and a student who cannot see that will be fooled by every well-dressed "
        "falsehood they ever meet.",
    ),
]

# Owner ruling 2026-11-24 (docs/DECISIONS.md entry 47): early exposure to the
# Summa Theologiae at 6-8. The one item in this module drawn from religion, on
# purpose, and handled differently from every other: it teaches the SHAPE of a
# disputed question, worked on Aquinas's own article "Whether God exists?", and
# Bede delivers no verdict on it. Every part is a SIMPLIFIED RETELLING, not a
# quotation (see services/aquinas_catalog.py for why), and says so.
_SUMMA_ARTICLES = [
    {
        "summa_id": "whether_god_exists",
        "reference": "Summa Theologiae, First Part, Question 2, Article 3",
        "question": "Whether God exists?",
        "parts": [
            ("The question", "Every article opens with a yes-or-no question, here: does God exist?"),
            ("Objections",
             "Next come the strongest reasons AGAINST the answer Aquinas will give, stated fairly, "
             "as a serious opponent would put them. Here there are two. First: if God were "
             "infinitely good, there would be no evil, yet there is evil in the world. Second: "
             "nature and human choices seem to explain everything that happens without needing "
             "God."),
            ("On the contrary",
             "Then a short reply from an authority on the other side. Here it is God's own word "
             "in Scripture, where God names himself to Moses as \"I am\" (Exodus 3)."),
            ("I answer that",
             "Then Aquinas's own reasoning. Here he gives five ways. The first, from motion: "
             "things are moved by something else; that chain cannot go back forever, or nothing "
             "would be moving now; so there is a first mover that nothing else moves, and that "
             "is what everyone means by God."),
            ("Replies to the objections",
             "Last, he answers EACH objection in turn. To the first, he follows St. Augustine: "
             "God, being supremely good, would not allow any evil unless he could bring good out "
             "of it. To the second: nature and human choices are themselves moved and caused, so "
             "they too lead back to a first cause."),
        ],
        "stages": _FROM_6,
    },
]


_STAGE_METHOD = {
    GradeStage.core_mastery: (
        "3-5 — INFORMAL AND ORAL. No technical vocabulary, no fallacy names, no syllogisms. At this "
        "stage logic is a handful of questions the child learns to ask, practised out loud on "
        "ordinary things — what they read this week, what they noticed outside, something they "
        "argued about with a sibling. Take ONE move per session and use it two or three times in "
        "real conversation; do not present the list. If the child starts asking \"how do you "
        "know?\" about things on their own, the stage has done its whole job."
    ),
    GradeStage.independent: (
        "6-8 — FORMAL, BUT STILL SPOKEN FIRST. Now the names and the forms. Work through ONE "
        "syllogism or ONE fallacy per session, slowly, out of the fixed set below — say it, let "
        "the student judge it, then tell them whether they were right and why. The single most "
        "important idea at this stage is that VALIDITY AND TRUTH ARE DIFFERENT THINGS: an argument "
        "can be built perfectly and still reach a false conclusion because a premise was false. "
        "Return to that until it is second nature. `invite_handwriting` suits laying out a "
        "syllogism's premises and conclusion on paper, where the structure becomes visible."
    ),
}


def current_week(today: "date | None" = None) -> int:
    """1-based ISO week number — the same calendar-driven rotation the
    poetry, prayer, Latin, and Greek catalogs use."""
    return (today or date.today()).isocalendar()[1]


def _items_for(stage: GradeStage) -> list:
    """What this stage actually studies: informal moves at 3-5, and the
    formal material at 6-8. A foundations-stage caller gets nothing, which
    is the point — see the module docstring."""
    if stage == GradeStage.core_mastery:
        return list(_MOVES)
    if stage == GradeStage.independent:
        return list(_FALLACIES) + list(_SYLLOGISMS) + list(_SUMMA_ARTICLES)
    return []


def item_for_week(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> "dict | None":
    """This week's single focus item. Returns None for K-2 — a foundations
    session should never have reached this subject at all (the config
    validator drops it), so this is the last of the three gates rather than
    the only one."""
    stage = grade_to_stage(grade) if grade else stage
    items = _items_for(stage)
    if not items:
        return None
    return items[(current_week(today) + week_salt - 1) % len(items)]


def _render_item(item: dict) -> str:
    if "move_id" in item:
        return (
            f"THIS WEEK'S MOVE: {item['name']}\n"
            f"The question to actually ask: {item['question']}\n"
            f"Why it matters: {item['why']}\n"
            f"A worked example to draw on: {item['example']}"
        )
    if "fallacy_id" in item:
        return (
            f"THIS WEEK'S FALLACY: {item['name']}\n"
            f"What it is: {item['definition']}\n"
            f"Example (use this one — do not invent your own): {item['example']}\n"
            f"Why it fails: {item['why_it_fails']}"
        )
    if "summa_id" in item:
        parts = "\n".join(f"  {name}: {text}" for name, text in item["parts"])
        return (
            "THIS WEEK'S SUMMA ARTICLE — the shape of a disputed question, worked on St. Thomas "
            f"Aquinas's own article \"{item['question']}\" ({item['reference']}). Everything below "
            "is a simplified retelling for this lesson, NOT Aquinas's own words; never quote the "
            "Summa from memory or present this as a quotation.\n"
            f"{parts}\n"
            "How to teach it: the lesson is the FORM. Walk the student through the five parts in "
            "order and ask them to say back what each part does. Point out what is remarkable about "
            "it: Aquinas puts the strongest case AGAINST his own conclusion first and answers every "
            "objection, which is this subject's own rule (state the other side fairly before you "
            "criticize it) practised by one of the greatest teachers who ever lived. Then take the "
            "first way and ask the student to restate it step by step in their own words, and to "
            "say which step each later step depends on. Correct one common mistake if it comes up: "
            "Aquinas does NOT argue \"everything has a cause\" (which would make God need a cause "
            "too); he argues that the things we see are moved and caused by something else, and "
            "that chain needs a beginning that is not itself moved or caused.\n"
            "What NOT to do: do not give a verdict of your own on whether the argument succeeds or "
            "whether God exists, and do not set the student to hunt for its flaws. Do not present "
            "the question as open either. Say plainly that this is St. Thomas's argument for what "
            "his Church teaches, and that what the student's own family believes about God belongs "
            "to their parents and their pastor, priest, or minister, who teach something definite "
            "about it. If the student pushes on an objection, that is the article working: show "
            "them where Aquinas answers it, and send anything further home."
        )
    premises = "\n".join(f"    {p}" for p in item["premises"])
    return (
        "THIS WEEK'S ARGUMENT — give it to the student exactly as written and let them judge it "
        "BEFORE you say anything:\n"
        f"{premises}\n"
        f"    {item['conclusion']}\n"
        f"Verdict: {item['verdict'].upper()}\n"
        f"Why: {item['why']}"
    )


def logic_note(
    grade: "str | None", stage: GradeStage, week_salt: int = 0, today: "date | None" = None,
) -> str:
    """
    The Subject.logic prompt block. Returns "" for K-2 — see the module
    docstring on why that is enforced here as well as at config validation
    and in the UI.
    """
    stage = grade_to_stage(grade) if grade else stage
    item = item_for_week(None, stage, week_salt, today)
    if not item:
        return ""

    return f"""

<logic>
{_render_item(item)}

HOW TO TEACH IT AT THIS STAGE:
{_STAGE_METHOD[stage]}

RULES FOR LOGIC SPECIFICALLY:
- Work from the arguments and examples given in this block. Do NOT invent new syllogisms, new
  fallacy examples, or new "is this valid?" puzzles of your own — a made-up argument can be
  invalid while looking fine, or valid while looking wrong, and the student cannot catch that
  error yet; catching it is what they are here to learn. If a student brings an argument of their
  own, you may reason about it carefully and out loud, but say plainly when you are not certain
  rather than delivering a confident verdict you cannot stand behind.
- Let the student judge FIRST, always. Give them the argument, ask what they think and why, and
  only then say whether it holds. A verdict handed down before they have reasoned is a fact to
  memorize, not a skill.
- Never let naming replace understanding. A student who can say "straw man" but cannot explain
  what was misrepresented has learned a label, not a lesson. Ask for the explanation every time.

WHAT LOGIC IS FOR — this matters more here than in any other subject:
- Logic is for finding what is true, together with someone — never for winning against them. Say
  this often and mean it. A student who leaves this subject better at arguing and no better at
  thinking has been harmed by it, not helped.
- If the student starts using this to catch out their parents, their siblings, or their church,
  redirect warmly and firmly. Point out that the first person to test an argument on is yourself:
  ask them what the strongest version of the OTHER side would be, and whether they can state it
  fairly before criticizing it. Never coach a child in how to argue against their own parents'
  instructions or authority — if they raise a disagreement at home, that belongs to their family,
  not to a logic lesson.
- Being right is not the same as being kind, and it does not outrank it. When a student is
  correct and unkind about it, the unkindness is the thing to address first.
- Do NOT rule on political, moral, or religious questions, however logically they are dressed up.
  Teach the FORM with the examples given in this block and send the substance home: that question belongs
  to the student's own parents and their own pastor, priest, or minister.
- Declining to rule is NOT the same as saying the matter is unsettled, and you must not blur them.
  Say "that one belongs to your parents and your church, and they teach something definite about
  it" — never "thoughtful people disagree, so it's open." On a political question, reasonable
  people genuinely do differ and you may say so. On a moral or religious one, do not characterize
  the landscape at all: this family's tradition holds what it holds, you are not its arbiter, and
  presenting a settled conviction of theirs as a live dispute would be taking a side while
  appearing not to.
- Naming a fallacy in someone's position is not the same as showing their conclusion is false, and
  a student should learn that here rather than the hard way. A bad argument for a true claim is
  still a bad argument — and the claim may still be true.
</logic>"""
