"""Practical math practice for K-2, built and checked by code
(docs/K2_PRACTICE.md §5.3).

Three pieces, the first the spec names: loose counters, a ten-frame, and a
number bond. Each lesson practises one topic, and each topic is one of the
existing K-2 skills in services/diagnostic/skill_map.py (no new skill id):

    count      cc.count_objects_20     counters, and building a number on a ten-frame
    compare    cc.compare_quantities   two rows of counters: more red, more yellow, or the same
    add        oa.add_within_20        a ten-frame (two past ten) with red and yellow counters
    subtract   oa.subtract_within_20   a ten-frame with some counters taken away
    bond       cc.number_bonds         a number bond with one part missing

A building question (putting counters on a ten-frame, whatever the topic
framing it) records counting, cc.count_objects_20, and nothing else (owner
ruling 2026-11-16, `recorded_skill`): the frame does the arithmetic for anyone
who counts, so it shows the child can make a number, not that they can add,
take away or split one. A question where the child picks the answer records
the topic's own skill.

The level comes from the SAVED grade, never the request, and the topic is
the first of that level's topics whose skill the child's saved math record
does not show as secure, in a fixed order.

Four rules this module holds, the same ones phonics and map practice hold:

1. **Every number is chosen here, never by a model**, and **every answer is
   worked out twice**: by the math pack's exact evaluator
   (services/practice/packs/math's `evaluate`, `fractions.Fraction`) on the
   question's own arithmetic, and by counting the picture
   (services/practice/diagrams.py's `answer`). A question where the two
   disagree is never built (`_checked`).
2. **No free text from the child.** An answer is a tap on one of the offered
   choices, the number of counters left on a ten-frame after dragging or
   tapping them (itself one of the offered choices), or spoken words matched
   to exactly one offered choice.
3. **The spoken instruction never says the answer and then counts hearing it
   back.** A question whose instruction contains its own answer ("Put 7
   counters in the frame") takes no spoken answer at all (the phonics echo
   rule).
4. **Nothing here is timed, scored or ranked.** A lesson is a pure function of
   (level, topic, seed), so nothing about it is stored: the routes rebuild it
   to check an answer.

Not built here yet (the spec's "then"): clock hands, coins, the number line
and the ruler. The spoken-forms table already covers clock times, so the
clock can use `match_spoken` as it stands.
"""
from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from services.diagnostic.mastery import classify_level
from services.diagnostic.skill_map import get_skill
from services.practice import diagrams
from services.practice.packs.math import evaluate

LEVELS = ("K", "1", "2")

#: Each topic's one skill id, from the existing K-2 skill map.
TOPIC_SKILL = {
    "count": "cc.count_objects_20",
    "compare": "cc.compare_quantities",
    "add": "oa.add_within_20",
    "subtract": "oa.subtract_within_20",
    "bond": "cc.number_bonds",
}
TOPICS = tuple(TOPIC_SKILL)

#: Each level's topics, in the order a lesson walks them.
LEVEL_TOPICS = {
    "K": ("count", "compare", "bond", "add", "subtract"),
    "1": ("add", "subtract", "bond", "compare"),
    "2": ("add", "subtract", "bond"),
}

#: How many choices a number question offers (the K-2 UX baseline, as phonics).
CHOICES_PER_LEVEL = {"K": 3, "1": 3, "2": 4}

TOGETHER_TASKS = 2
YOUR_TURN_TASKS = 3
PHASES = ("together", "your_turn")
_PHASE_COUNT = {"together": TOGETHER_TASKS, "your_turn": YOUR_TURN_TASKS}

#: Where each step sits in a lesson's list of problems.
_POSITIONS = (("watch", 0), ("together", 0), ("together", 1), ("your_turn", 0), ("your_turn", 1), ("your_turn", 2))

#: Which steps build on a ten-frame (drag or tap counters) rather than pick an
#: answer. Comparing two rows has no building step.
_BUILD_POSITIONS = {("watch", 0), ("together", 0), ("your_turn", 1)}

LEDGER_SUBJECT_AREA = "mathematics"

#: Every question in this area can be answered from the picture on screen, so
#: none works only by ear (unlike phonics' sight words). Kept as a named,
#: empty set so the no-sound flag means the same in every area.
AUDIO_ONLY_TOPICS: frozenset[str] = frozenset()

COMPARE_CHOICES = ("red", "yellow", "same")

#: The English question each prompt key asks, given to diagrams.answer so the
#: picture's own count is worked out with the same words every time. The
#: child sees and hears the translated line (the app's k2Math.prompt.*).
_QUESTION = {
    "count_how_many": "How many counters are there?",
    "compare_more": "Which has more?",
    "add_how_many": "How many are there in all?",
    "subtract_how_many": "How many are left?",
    "bond_missing": "What number is missing?",
    "count_build": "How many counters are there?",
    "add_build": "How many are there in all?",
    "subtract_build": "How many are left?",
    "bond_build": "How many are there in all?",
}


def level_for_grade(grade: str) -> Optional[str]:
    """The practice level for a SAVED grade, or None outside K-2."""
    g = (grade or "").strip().upper()
    return g if g in LEVELS else None


def topic_for(level: str, vector: Optional[dict] = None) -> str:
    """The first of the level's topics whose skill the saved math record does
    not show as secure; with no record, the level's first topic."""
    topics = LEVEL_TOPICS[level]
    for topic in topics:
        if vector is None or classify_level(vector.get(TOPIC_SKILL[topic], 0.5)) != "secure":
            return topic
    return topics[-1]


def skill_label(topic: str) -> str:
    return get_skill(TOPIC_SKILL[topic]).label


#: The one skill a building question records (owner ruling 2026-11-16, a
#: product default). Putting a number of counters on a ten-frame shows the
#: child can make that many; it does not show the addition, subtraction or
#: number bond the question was framed in, since the frame itself does the
#: arithmetic for anyone who counts. So every building question, whatever its
#: topic, records counting and nothing else.
BUILD_SKILL = "cc.count_objects_20"


def recorded_skill(task: "Task") -> str:
    """The skill a right Your turn answer to `task` is evidence for: counting
    for any building question, the topic's own skill for a question where the
    child picks the answer."""
    return BUILD_SKILL if task.choice_kind == "build" else TOPIC_SKILL[task.topic]


# ── A question ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Task:
    topic: str
    prompt_key: str
    prompt_args: dict
    #: The picture: a piece diagram (counters, a ten-frame, a number bond).
    diagram: dict
    #: "number", "color" or "build".
    choice_kind: str
    choices: tuple[str, ...]
    accept_choice: str
    #: The question's arithmetic, worked out by the math pack's evaluator.
    expression: str = ""
    #: For a building question: counters already on the frame, how many the
    #: frames hold, and whether the move is taking counters away.
    build: dict = field(default_factory=dict)

    def is_right(self, choice: Optional[str]) -> bool:
        return choice is not None and choice == self.accept_choice

    def reveal(self) -> dict:
        return {"choice": self.accept_choice}

    def public(self, phase: str, index: int) -> dict:
        """What the child's screen is sent. Together carries the guide (a
        number on each counter, and the target faintly shown on a frame);
        Your turn carries neither."""
        guided = phase != "your_turn"
        display: dict = {"diagram": dict(self.diagram), "guide": guided}
        if guided and self.choice_kind == "build":
            display["ghost"] = int(self.accept_choice)
        out = {
            "phase": phase, "index": index,
            "prompt": {"key": self.prompt_key, "args": dict(self.prompt_args)},
            "display": display, "choice_kind": self.choice_kind, "choices": list(self.choices),
        }
        if self.build:
            out["build"] = dict(self.build)
        return out


def _value(expression: str) -> int:
    """An answer worked out by the math pack's exact evaluator."""
    result = evaluate(expression)
    if result is None or result.denominator != 1:
        raise ValueError(f"not a whole-number problem: {expression}")
    return int(result)


def _checked(task: Task) -> Task:
    """Refuse a question whose two workings disagree: the evaluator's answer
    (already the accepted choice) and the picture's own count."""
    end = task.diagram
    if task.choice_kind == "build":
        end = _end_state(task)
    seen = diagrams.answer(diagrams.parse_piece(end), _QUESTION[task.prompt_key])
    if seen != task.accept_choice:
        raise ValueError(f"the picture and the arithmetic disagree: {task}")
    if task.accept_choice not in task.choices or len(set(task.choices)) != len(task.choices):
        raise ValueError(f"malformed choices: {task}")
    return task


def _end_state(task: Task) -> dict:
    """The frame as it looks once the building question is answered."""
    start, target = task.build["start"], int(task.accept_choice)
    frames = task.diagram["frames"]
    if task.build["take_away"]:
        return {"kind": "ten_frame", "frames": frames, "red": start, "crossed": start - target}
    return {"kind": "ten_frame", "frames": frames, "red": start, "yellow": target - start}


def _number_choices(rng: random.Random, answer: int, n: int, top: int) -> tuple[str, ...]:
    """The answer and n-1 nearby numbers, smallest first, all between 0 and
    `top`. Close numbers, so a choice is a real decision, never a giveaway."""
    pool = [answer + d for d in (1, -1, 2, -2, 3, -3, 4, -4) if 0 <= answer + d <= top]
    nearest = [v for v in pool if abs(v - answer) <= 2]
    farther = [v for v in pool if abs(v - answer) > 2]
    rng.shuffle(nearest)
    rng.shuffle(farther)
    return tuple(str(v) for v in sorted((nearest + farther)[: n - 1] + [answer]))


def _frames_for(top: int) -> int:
    return 2 if top > 10 else 1


# ── Problems ─────────────────────────────────────────────────────────────────

def _problem(level: str, topic: str, rng: random.Random) -> tuple:
    """One problem's numbers, by level. Every range stays within 20."""
    if topic == "count":
        lo, hi = {"K": (3, 10), "1": (6, 15), "2": (11, 20)}[level]
        return (rng.randint(lo, hi),)
    if topic == "compare":
        lo, hi = {"K": (1, 8), "1": (3, 12), "2": (8, 20)}[level]
        a = rng.randint(lo, hi)
        b = a if rng.random() < 0.25 else rng.choice([v for v in range(lo, hi + 1) if v != a])
        return (a, b)
    if topic == "add":
        if level == "2":
            a = rng.randint(6, 9)
            return (a, rng.randint(11 - a, 9))
        top = 10 if level == "K" else 12
        total = rng.randint(3 if level == "K" else 6, top)
        a = rng.randint(1, total - 1)
        return (a, total - a)
    if topic == "subtract":
        if level == "2":
            a = rng.randint(11, 18)
            return (a, rng.randint(2, min(9, a - 2)))
        a = rng.randint(3 if level == "K" else 5, 10)
        return (a, rng.randint(1, a - 1))
    if topic == "bond":
        whole = rng.randint(3, 7) if level == "K" else rng.randint(5, 10) if level == "1" else rng.randint(11, 18)
        return (whole, rng.randint(1, whole - 1))
    raise ValueError("unknown topic")


@lru_cache(maxsize=512)
def _problems(level: str, topic: str, seed: int) -> tuple[tuple, ...]:
    """The lesson's six problems (Watch, two Together, three Your turn), all
    different, the same every time for the same arguments."""
    rng = random.Random(f"k2math:{level}:{topic}:{seed}")
    out: list[tuple] = []
    tries = 0
    while len(out) < len(_POSITIONS):
        p = _problem(level, topic, rng)
        tries += 1
        if p not in out or tries > 200:
            out.append(p)
    return tuple(out)


def _build_task(level: str, topic: str, seed: int, phase: str, index: int) -> Task:
    pos = _POSITIONS.index((phase, index))
    numbers = _problems(level, topic, seed)[pos]
    rng = random.Random(f"k2math:{level}:{topic}:{seed}:{phase}:{index}")
    n = CHOICES_PER_LEVEL[level]
    building = (phase, index) in _BUILD_POSITIONS and topic != "compare"

    if topic == "count":
        (count,) = numbers
        if building:
            return _checked(_build(topic, "count_build", {"n": str(count)}, start=0, target=count,
                                   capacity=10 * _frames_for(count), take_away=False, expression=f"0 + {count}"))
        diagram = {"kind": "counters", "groups": [{"color": "red", "count": count}]}
        return _checked(Task(topic, "count_how_many", {}, diagram, "number",
                             _number_choices(rng, count, n, 20), str(count)))

    if topic == "compare":
        a, b = numbers
        diff = _value(f"{a} - {b}")
        answer = "same" if diff == 0 else "red" if diff > 0 else "yellow"
        diagram = {"kind": "counters", "groups": [{"color": "red", "count": a}, {"color": "yellow", "count": b}]}
        return _checked(Task(topic, "compare_more", {}, diagram, "color", COMPARE_CHOICES, answer,
                             expression=f"{a} - {b}"))

    if topic == "add":
        a, b = numbers
        total = _value(f"{a} + {b}")
        capacity = 10 * _frames_for(total)
        if building:
            return _checked(_build(topic, "add_build", {"a": str(a), "b": str(b)}, start=a, target=total,
                                   capacity=capacity, take_away=False, expression=f"{a} + {b}"))
        diagram = {"kind": "ten_frame", "frames": capacity // 10, "red": a, "yellow": b}
        return _checked(Task(topic, "add_how_many", {"a": str(a), "b": str(b)}, diagram, "number",
                             _number_choices(rng, total, n, capacity), str(total),
                             expression=f"{a} + {b}"))

    if topic == "subtract":
        a, b = numbers
        left = _value(f"{a} - {b}")
        capacity = 10 * _frames_for(a)
        if building:
            return _checked(_build(topic, "subtract_build", {"a": str(a), "b": str(b)}, start=a, target=left,
                                   capacity=capacity, take_away=True, expression=f"{a} - {b}"))
        diagram = {"kind": "ten_frame", "frames": capacity // 10, "red": a, "crossed": b}
        return _checked(Task(topic, "subtract_how_many", {"a": str(a), "b": str(b)}, diagram, "number",
                             _number_choices(rng, left, n, capacity), str(left),
                             expression=f"{a} - {b}"))

    if topic == "bond":
        whole, part = numbers
        missing = _value(f"{whole} - {part}")
        capacity = 10 * _frames_for(whole)
        if building:
            return _checked(_build(topic, "bond_build", {"whole": str(whole), "part": str(part)}, start=part,
                                   target=whole, capacity=capacity, take_away=False,
                                   expression=f"{part} + {missing}"))
        parts = [part, None] if rng.random() < 0.5 else [None, part]
        diagram = {"kind": "number_bond", "whole": whole, "parts": parts}
        return _checked(Task(topic, "bond_missing", {"whole": str(whole), "part": str(part)}, diagram, "number",
                             _number_choices(rng, missing, n, whole), str(missing),
                             expression=f"{whole} - {part}"))

    raise ValueError("unknown topic")


def _build(topic: str, key: str, args: dict, *, start: int, target: int, capacity: int,
           take_away: bool, expression: str) -> Task:
    """A building question: the frame starts with `start` counters and the
    answer is how many are on it when the child is done. Every count the
    frames can hold is an offered choice, so the final count is checked like
    any tapped choice."""
    if _value(expression) != target:
        raise ValueError("a building target that its arithmetic does not give")
    diagram = {"kind": "ten_frame", "frames": capacity // 10, "red": start}
    return Task(topic, key, args, diagram, "build", tuple(str(i) for i in range(capacity + 1)), str(target),
                expression=expression, build={"start": start, "capacity": capacity, "take_away": take_away})


def build_task(level: str, topic: str, seed: int, phase: str, index: int) -> Task:
    """One question, the same every time for the same arguments."""
    if level not in LEVELS or topic not in TOPICS:
        raise ValueError("unknown level or topic")
    if phase not in PHASES or not 0 <= index < _PHASE_COUNT[phase]:
        raise ValueError("unknown task")
    return _build_task(level, topic, seed, phase, index)


def build_watch(level: str, topic: str, seed: int) -> dict:
    """The Watch step: one question with its answer, shown and said, so what
    Bede demonstrates is exactly what the child is about to do."""
    task = _build_task(level, topic, seed, "watch", 0)
    out = task.public("watch", 0)
    out.pop("phase"); out.pop("index")
    out["answer"] = task.reveal()
    return out


def build_lesson(level: str, seed: int, topic: str, audio: bool = True) -> dict:
    """The whole lesson as sent to the child's screen. The answer is sent for
    Watch only; Together and Your turn are checked on the server. `audio`
    may only remove questions that work only by ear, and none here does."""
    if level not in LEVELS or topic not in TOPICS:
        raise ValueError("unknown level or topic")
    base = {"area": "math", "level": level, "topic": topic, "skill": TOPIC_SKILL[topic],
            "label": skill_label(topic), "audio": audio}
    if not audio and topic in AUDIO_ONLY_TOPICS:  # pragma: no cover - no such topic yet
        return {**base, "needs_audio": True, "watch": None, "together": [], "your_turn": []}
    return {
        **base, "needs_audio": False,
        "watch": build_watch(level, topic, seed),
        "together": [build_task(level, topic, seed, "together", i).public("together", i)
                     for i in range(TOGETHER_TASKS)],
        "your_turn": [build_task(level, topic, seed, "your_turn", i).public("your_turn", i)
                      for i in range(YOUR_TURN_TASKS)],
    }


# ── Spoken answers ───────────────────────────────────────────────────────────
# Numbers, quantities and clock times a child may say, in English and in
# Spanish. Matching is whole-word, resolves only to one of the question's own
# choices, and never judges how a word was said.

_EN_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
            "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
            "nineteen", "twenty")
_EN_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty"}
_ES_ONES = ("cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
            "once", "doce", "trece", "catorce", "quince", "dieciseis", "diecisiete", "dieciocho",
            "diecinueve", "veinte")
_ES_TWENTIES = ("veinte", "veintiuno", "veintidos", "veintitres", "veinticuatro", "veinticinco",
                "veintiseis", "veintisiete", "veintiocho", "veintinueve")
_ES_TENS = {30: "treinta", 40: "cuarenta", 50: "cincuenta"}

#: The same quantity words in both languages, for comparing two rows.
_QUANTITY_FORMS = {
    "red": ("red", "the red", "red ones", "rojo", "rojos", "roja", "rojas", "los rojos"),
    "yellow": ("yellow", "the yellow", "yellow ones", "amarillo", "amarillos", "amarilla", "amarillas",
               "los amarillos"),
    "same": ("same", "the same", "equal", "they are the same", "igual", "iguales", "lo mismo",
             "son iguales", "la misma", "el mismo"),
}


def _en_number(n: int) -> list[str]:
    if 0 <= n <= 20:
        return [_EN_ONES[n]]
    tens, ones = (n // 10) * 10, n % 10
    if tens in _EN_TENS:
        return [_EN_TENS[tens]] if ones == 0 else [f"{_EN_TENS[tens]} {_EN_ONES[ones]}"]
    return []


def _es_number(n: int) -> list[str]:
    if 0 <= n <= 20:
        forms = [_ES_ONES[n]]
        if 16 <= n <= 19:  # also written "diez y seis"
            forms.append(f"diez y {_ES_ONES[n - 10]}")
        return forms
    if 21 <= n <= 29:
        return [_ES_TWENTIES[n - 20], f"veinte y {_ES_ONES[n - 20]}"]
    tens, ones = (n // 10) * 10, n % 10
    if tens in _ES_TENS:
        return [_ES_TENS[tens]] if ones == 0 else [f"{_ES_TENS[tens]} y {_ES_ONES[ones]}"]
    return []


def number_forms(n: int) -> tuple[str, ...]:
    """Every way a number up to 59 may be said, as digits or words."""
    return (str(n), *_en_number(n), *_es_number(n))


def time_forms(hour: int, minute: int) -> tuple[str, ...]:
    """Every way a clock time may be said: "ten thirty", "half past ten",
    "diez y media", "las diez y media"."""
    nxt = hour % 12 + 1
    # An hour is feminine in Spanish ("la una", never "la uno").
    en_h, es_h = _en_number(hour)[0], "una" if hour == 1 else _es_number(hour)[0]
    es_next = "una" if nxt == 1 else _es_number(nxt)[0]
    article = "la" if hour == 1 else "las"
    forms = [f"{hour}:{minute:02d}", f"{hour} {minute:02d}"]
    if minute == 0:
        forms += [f"{en_h} o clock", f"{en_h} oclock", f"{es_h} en punto", f"{article} {es_h}",
                  f"{article} {es_h} en punto"]
    else:
        forms += [f"{en_h} {m}" for m in _en_number(minute)]
        forms += [f"{en_h} oh {_EN_ONES[minute]}"] if minute < 10 else []
        forms += [f"{es_h} {m}" for m in _es_number(minute)] + [f"{es_h} y {m}" for m in _es_number(minute)]
    if minute == 30:
        forms += [f"half past {en_h}", f"{es_h} y media", f"{article} {es_h} y media"]
    if minute == 15:
        forms += [f"quarter past {en_h}", f"a quarter past {en_h}", f"{es_h} y cuarto",
                  f"{article} {es_h} y cuarto"]
    if minute == 45:
        forms += [f"quarter to {_en_number(nxt)[0]}", f"a quarter to {_en_number(nxt)[0]}",
                  f"cuarto para {'la' if nxt == 1 else 'las'} {es_next}"]
    return tuple(forms)


_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def spoken_forms(choice: str) -> tuple[str, ...]:
    """The words a child may say for one choice: a number, a quantity, or a
    clock time."""
    if choice.isdigit():
        return number_forms(int(choice))
    if choice in _QUANTITY_FORMS:
        return (choice, *_QUANTITY_FORMS[choice])
    clock = _TIME.match(choice)
    if clock and 1 <= int(clock.group(1)) <= 12 and int(clock.group(2)) < 60:
        return time_forms(int(clock.group(1)), int(clock.group(2)))
    return (choice,)


def _words(text: str) -> list[str]:
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return "".join(ch.lower() if ch.isalnum() else " " for ch in plain).split()


def speech_echoes_answer(task: Task) -> bool:
    """Whether the spoken instruction says the answer ("Put 7 counters in
    the frame"), so saying it back shows only that the child heard it."""
    return task.accept_choice in {str(v) for v in task.prompt_args.values()}


def match_spoken(task: Task, text: str) -> Optional[str]:
    """The question's own choice a spoken answer names, or None when it names
    none or more than one. Never returns anything outside `task.choices`.

    Words are matched whole and in order, and a shorter match that sits
    inside a longer one belongs to the longer: "ten thirty" names 10:30 and
    not 10:00, "diez y seis" names 16 and not 10 or 6. A question whose
    spoken instruction says its own answer takes no spoken answer at all:
    an echo is neither a miss nor an answer, like speech that matched
    nothing."""
    if speech_echoes_answer(task):
        return None
    heard = _words((text or "")[:200])
    spans: dict[str, list[tuple[int, int]]] = {}
    for choice in task.choices:
        for form in spoken_forms(choice):
            want = _words(form)
            if not want:
                continue
            for i in range(len(heard) - len(want) + 1):
                if heard[i:i + len(want)] == want:
                    spans.setdefault(choice, []).append((i, i + len(want)))
    named = {
        choice for choice, mine in spans.items()
        if any(not any(o != choice and t[0] <= s[0] and s[1] <= t[1] and t[1] - t[0] > s[1] - s[0]
                       for o, theirs in spans.items() for t in theirs)
               for s in mine)
    }
    return next(iter(named)) if len(named) == 1 else None


__all__ = [
    "AUDIO_ONLY_TOPICS", "CHOICES_PER_LEVEL", "COMPARE_CHOICES", "LEVELS", "LEVEL_TOPICS", "PHASES",
    "TOGETHER_TASKS", "TOPICS", "TOPIC_SKILL", "YOUR_TURN_TASKS", "BUILD_SKILL", "Task", "build_lesson",
    "build_task", "recorded_skill",
    "build_watch", "level_for_grade", "match_spoken", "number_forms", "speech_echoes_answer",
    "spoken_forms", "time_forms", "topic_for",
]
