"""Phonics and blending practice for K-2, built and checked by code
(docs/K2_PRACTICE.md §5.1).

The skills are the phonics record's own six domains, in their own order
(services/diagnostic/phonics.py's DOMAINS). A kindergartner starts at
rhyming, a first grader at blending simple words, a second grader at blends
and digraphs, and a lesson practises the first domain at or after that start
that the child's phonics record does not yet show as secure.

Three rules this module holds, the same ones map practice holds:

1. **Every word is authored here, never generated.** Each domain has a fixed
   list of decodable words, each with a picture from the practice icon set
   (models/practice.py's ICONS). No model writes an item or decides whether
   an answer is right.
2. **No free text from the child.** An answer is a tap on one of the offered
   choices, or a spoken word matched to exactly one of them. Bede never
   judges pronunciation: speech recognition cannot hear a young child's
   sounds reliably, so a spoken answer is only ever a stand-in for a tap.
3. **Narration never gives the answer away.** Where reading the word is the
   skill (blending, blends and digraphs, long vowels), "Your turn" neither
   speaks the word nor sends the letters' sounds. Where hearing is the skill
   (rhymes, first sounds) or the spoken word is the cue (sight words), the
   word is spoken because it is the question, not its answer.

Everything is a pure function of (level, domain, seed), so a lesson is never
stored: the routes rebuild it to check an answer.

The words are English, because the phonics domains are English phonics. In a
Spanish session the instructions and Bede's card are Spanish and the words
being read stay English; Spanish decoding practice is not built.
"""
from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from models.practice import ICONS
from services.diagnostic.mastery import classify_level
from services.diagnostic.phonics import DOMAIN_LABELS, DOMAINS

LEVELS = ("K", "1", "2")

#: Where each grade starts (spec §5.1).
START_DOMAIN = {"K": "phonological_awareness", "1": "cvc_blending", "2": "blends_digraphs"}

#: How many choices a question offers. The K-2 UX baseline starts
#: kindergarten at 2 to 3 and grades 1 and 2 at 3 to 4.
CHOICES_PER_LEVEL = {"K": 3, "1": 3, "2": 4}

TOGETHER_TASKS = 2
YOUR_TURN_TASKS = 3
PHASES = ("together", "your_turn")
_PHASE_COUNT = {"together": TOGETHER_TASKS, "your_turn": YOUR_TURN_TASKS}

LEDGER_SUBJECT_AREA = "phonics"

#: Domains where reading the written word IS the skill, so the answer is
#: never spoken in "Your turn".
DECODING_DOMAINS = frozenset({"cvc_blending", "blends_digraphs", "long_vowel_patterns"})

# ── The authored word lists ─────────────────────────────────────────────────

#: Rhyming pairs. Every pair has its own ending, so a word from another pair
#: never rhymes with the target.
RHYME_PAIRS: tuple[tuple[str, str], ...] = (
    ("cat", "hat"), ("dog", "frog"), ("bee", "tree"), ("cake", "snake"), ("goat", "boat"),
    ("bear", "chair"), ("mouse", "house"), ("moon", "spoon"), ("fox", "box"), ("bed", "bread"),
    ("star", "car"),
)

#: A picture and the letter its first sound is written with. No two share a sound.
FIRST_SOUNDS: tuple[tuple[str, str], ...] = (
    ("sun", "s"), ("moon", "m"), ("dog", "d"), ("bee", "b"), ("fish", "f"), ("pig", "p"),
    ("hat", "h"), ("leaf", "l"), ("rain", "r"), ("goat", "g"), ("water", "w"), ("tooth", "t"),
)

# A grapheme is (letters, sound). The sound is a short spoken cue for speech
# synthesis; "" marks a silent letter. These approximate a sound, they do not
# model it, and nothing is ever compared against them.
_G = tuple[str, str]

DECODABLE: dict[str, tuple[tuple[str, tuple[_G, ...]], ...]] = {
    "cvc_blending": (
        ("cat", (("c", "kuh"), ("a", "ah"), ("t", "tuh"))),
        ("dog", (("d", "duh"), ("o", "aw"), ("g", "guh"))),
        ("pig", (("p", "puh"), ("i", "ih"), ("g", "guh"))),
        ("sun", (("s", "sss"), ("u", "uh"), ("n", "nnn"))),
        ("hat", (("h", "huh"), ("a", "ah"), ("t", "tuh"))),
        ("bus", (("b", "buh"), ("u", "uh"), ("s", "sss"))),
        ("bed", (("b", "buh"), ("e", "eh"), ("d", "duh"))),
        ("cup", (("c", "kuh"), ("u", "uh"), ("p", "puh"))),
        ("fox", (("f", "fff"), ("o", "aw"), ("x", "ks"))),
        ("box", (("b", "buh"), ("o", "aw"), ("x", "ks"))),
        ("map", (("m", "mmm"), ("a", "ah"), ("p", "puh"))),
    ),
    "blends_digraphs": (
        ("fish", (("f", "fff"), ("i", "ih"), ("sh", "shh"))),
        ("ship", (("sh", "shh"), ("i", "ih"), ("p", "puh"))),
        ("frog", (("f", "fff"), ("r", "rrr"), ("o", "aw"), ("g", "guh"))),
        ("duck", (("d", "duh"), ("u", "uh"), ("ck", "kuh"))),
        ("truck", (("t", "tuh"), ("r", "rrr"), ("u", "uh"), ("ck", "kuh"))),
        ("plant", (("p", "puh"), ("l", "lll"), ("a", "ah"), ("n", "nnn"), ("t", "tuh"))),
    ),
    "long_vowel_patterns": (
        ("cake", (("c", "kuh"), ("a", "ay"), ("k", "kuh"), ("e", ""))),
        ("snake", (("s", "sss"), ("n", "nnn"), ("a", "ay"), ("k", "kuh"), ("e", ""))),
        ("bone", (("b", "buh"), ("o", "oh"), ("n", "nnn"), ("e", ""))),
        ("cube", (("c", "kuh"), ("u", "you"), ("b", "buh"), ("e", ""))),
        ("rain", (("r", "rrr"), ("ai", "ay"), ("n", "nnn"))),
        ("boat", (("b", "buh"), ("oa", "oh"), ("t", "tuh"))),
        ("goat", (("g", "guh"), ("oa", "oh"), ("t", "tuh"))),
        ("tree", (("t", "tuh"), ("r", "rrr"), ("ee", "ee"))),
        ("bee", (("b", "buh"), ("ee", "ee"))),
        ("leaf", (("l", "lll"), ("ea", "ee"), ("f", "fff"))),
    ),
}

#: Common words that cannot be sounded out, read by sight.
SIGHT_WORDS: tuple[str, ...] = ("the", "was", "said", "of", "you", "are", "to", "one", "they", "have")

#: The sound of each first-sound letter, spoken when a letter choice is
#: tapped in Watch and Together. Consonants only, so each has one sound here.
LETTER_SOUNDS = {
    "s": "sss", "m": "mmm", "d": "duh", "b": "buh", "f": "fff", "p": "puh",
    "h": "huh", "l": "lll", "r": "rrr", "g": "guh", "w": "wuh", "t": "tuh",
}

#: Words a child may say for a choice. Matching is whole-word and only ever
#: resolves to one of the question's own choices.
_PICTURE_SPOKEN = {
    "cat": ("gato",), "hat": ("sombrero",), "dog": ("perro",), "frog": ("rana",), "bee": ("abeja",),
    "tree": ("arbol",), "cake": ("pastel",), "snake": ("serpiente", "vibora"), "goat": ("cabra",),
    "boat": ("barco", "bote"), "bear": ("oso",), "chair": ("silla",), "mouse": ("raton",),
    "house": ("casa",), "moon": ("luna",), "spoon": ("cuchara",), "fox": ("zorro",), "box": ("caja",),
    "bed": ("cama",), "bread": ("pan",), "star": ("estrella",), "car": ("carro", "coche"),
    "pig": ("cerdo", "puerco", "cochino"), "sun": ("sol",), "bus": ("autobus",), "cup": ("taza",),
    "map": ("mapa",), "fish": ("pez", "pescado"), "ship": ("barco",), "duck": ("pato",),
    "truck": ("camion",), "plant": ("planta",), "rain": ("lluvia",), "bone": ("hueso",),
    "cube": ("cubo",), "leaf": ("hoja",),
}
_LETTER_SPOKEN = {
    "s": ("ess", "ese"), "m": ("em", "eme"), "d": ("dee",), "b": ("bee", "be"), "f": ("ef", "efe"),
    "p": ("pee", "pe"), "h": ("aitch", "hache"), "l": ("ele",), "r": ("ar", "erre", "ere"),
    "g": ("gee", "ge"), "w": (), "t": ("tee",),
}


def level_for_grade(grade: str) -> Optional[str]:
    """The practice level for a SAVED grade, or None outside K-2."""
    g = (grade or "").strip().upper()
    return g if g in LEVELS else None


def domain_for(level: str, vector: Optional[dict] = None) -> str:
    """The domain a lesson practises: the first at or after the grade's start
    that the child's phonics record does not show as secure, walked in the
    record's own developmental order. With no record, the grade's start."""
    start = DOMAINS.index(START_DOMAIN[level])
    for domain in DOMAINS[start:]:
        if vector is None or classify_level(vector.get(domain, 0.5)) != "secure":
            return domain
    return DOMAINS[-1]


# ── A question ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Task:
    domain: str
    prompt_key: str
    prompt_args: dict
    #: What the question is about: a picture to hear, a word to read, or a
    #: word to listen for. Graphemes carry sounds only outside "Your turn".
    display: dict
    #: "picture", "letter" or "word".
    choice_kind: str
    choices: tuple[str, ...]
    accept_choice: str
    choice_sounds: dict = field(default_factory=dict)

    def is_right(self, choice: Optional[str]) -> bool:
        return choice is not None and choice == self.accept_choice

    def reveal(self) -> dict:
        return {"choice": self.accept_choice}

    def public(self, phase: str, index: int) -> dict:
        display = dict(self.display)
        if phase == "your_turn" and self.domain in DECODING_DOMAINS:
            # Reading the word is the skill: no sounds, and no word to speak.
            display.pop("word", None)
            display["graphemes"] = [{"text": g["text"], **({"silent": True} if g.get("silent") else {})}
                                    for g in display.get("graphemes", [])]
        out = {
            "phase": phase, "index": index,
            "prompt": {"key": self.prompt_key, "args": self.prompt_args},
            "display": display, "choice_kind": self.choice_kind, "choices": list(self.choices),
        }
        if phase != "your_turn" and self.choice_sounds:
            out["choice_sounds"] = dict(self.choice_sounds)
        return out


def _graphemes(gs: tuple[_G, ...]) -> list[dict]:
    return [{"text": text, "sound": sound} if sound else {"text": text, "silent": True} for text, sound in gs]


def _choices(rng: random.Random, answer: str, pool: list[str], n: int) -> tuple[str, ...]:
    others = sorted(set(pool) - {answer})
    rng.shuffle(others)
    picked = [answer] + others[: n - 1]
    rng.shuffle(picked)
    return tuple(picked)


def _order(level: str, domain: str, seed: int, size: int) -> list[int]:
    """One lesson's items in a fixed order, so Watch, Together and Your turn
    each get a different word."""
    order = list(range(size))
    random.Random(f"phonics:{level}:{domain}:{seed}:order").shuffle(order)
    return order


def _position(phase: str, index: int) -> int:
    return {"watch": 0, "together": 1, "your_turn": 1 + TOGETHER_TASKS}[phase] + index


def _build(level: str, domain: str, seed: int, phase: str, index: int) -> Task:
    rng = random.Random(f"phonics:{level}:{domain}:{seed}:{phase}:{index}")
    n = CHOICES_PER_LEVEL[level]
    pos = _position(phase, index)

    if domain == "phonological_awareness":
        pair = RHYME_PAIRS[_order(level, domain, seed, len(RHYME_PAIRS))[pos % len(RHYME_PAIRS)]]
        target, rhyme = (pair if rng.random() < 0.5 else (pair[1], pair[0]))
        pool = [w for p in RHYME_PAIRS if p != pair for w in p] + [rhyme]
        return Task(domain, "rhyme_choice", {"word": target},
                    {"kind": "picture", "icon": target, "word": target},
                    "picture", _choices(rng, rhyme, pool, n), rhyme)

    if domain == "letter_sound":
        picture, letter = FIRST_SOUNDS[_order(level, domain, seed, len(FIRST_SOUNDS))[pos % len(FIRST_SOUNDS)]]
        choices = _choices(rng, letter, [lt for _, lt in FIRST_SOUNDS], n)
        return Task(domain, "first_sound_choice", {"word": picture},
                    {"kind": "picture", "icon": picture, "word": picture},
                    "letter", choices, letter, {c: LETTER_SOUNDS[c] for c in choices})

    if domain in DECODABLE:
        words = DECODABLE[domain]
        word, gs = words[_order(level, domain, seed, len(words))[pos % len(words)]]
        return Task(domain, "read_word_choice", {},
                    {"kind": "word", "graphemes": _graphemes(gs), "word": word},
                    "picture", _choices(rng, word, [w for w, _ in words], n), word)

    if domain == "sight_words":
        word = SIGHT_WORDS[_order(level, domain, seed, len(SIGHT_WORDS))[pos % len(SIGHT_WORDS)]]
        return Task(domain, "sight_word_choice", {"word": word},
                    {"kind": "listen", "word": word},
                    "word", _choices(rng, word, list(SIGHT_WORDS), n), word)

    raise ValueError("unknown domain")


def build_task(level: str, domain: str, seed: int, phase: str, index: int) -> Task:
    """One question, the same every time for the same arguments."""
    if level not in LEVELS or domain not in DOMAINS:
        raise ValueError("unknown level or domain")
    if phase not in PHASES or not 0 <= index < _PHASE_COUNT[phase]:
        raise ValueError("unknown task")
    return _build(level, domain, seed, phase, index)


def build_watch(level: str, domain: str, seed: int) -> dict:
    """The Watch step: one question with its answer, shown and spoken, so
    what Bede demonstrates is exactly what the child is about to do."""
    task = _build(level, domain, seed, "watch", 0)
    out = task.public("watch", 0)
    out.pop("phase"); out.pop("index")
    out["answer"] = task.reveal()
    return out


def build_lesson(level: str, seed: int, domain: str) -> dict:
    """The whole lesson as sent to the child's screen. The answer is sent for
    Watch only; Together and Your turn are checked on the server."""
    if level not in LEVELS or domain not in DOMAINS:
        raise ValueError("unknown level or domain")
    return {
        "area": "phonics", "level": level, "domain": domain, "label": DOMAIN_LABELS[domain],
        "watch": build_watch(level, domain, seed),
        "together": [build_task(level, domain, seed, "together", i).public("together", i)
                     for i in range(TOGETHER_TASKS)],
        "your_turn": [build_task(level, domain, seed, "your_turn", i).public("your_turn", i)
                      for i in range(YOUR_TURN_TASKS)],
    }


def _plain(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def spoken_forms(task: Task, choice: str) -> tuple[str, ...]:
    if task.choice_kind == "picture":
        return (choice,) + _PICTURE_SPOKEN.get(choice, ())
    if task.choice_kind == "letter":
        return (choice,) + _LETTER_SPOKEN.get(choice, ())
    return (choice,)


def match_spoken(task: Task, text: str) -> Optional[str]:
    """The question's own choice a spoken answer names, or None when it names
    none or more than one. The same rule as map_practice.match_spoken, with
    this area's own words. Never returns anything outside `task.choices`."""
    words = set("".join(ch.lower() if ch.isalnum() else " " for ch in _plain((text or "")[:200])).split())
    hits = [c for c in task.choices if any(w in words for w in spoken_forms(task, c))]
    return hits[0] if len(hits) == 1 else None


def _check_vocabulary() -> None:
    for word in [w for p in RHYME_PAIRS for w in p] + [p for p, _ in FIRST_SOUNDS] + \
            [w for ws in DECODABLE.values() for w, _ in ws]:
        if word not in ICONS:  # pragma: no cover - guarded by tests
            raise RuntimeError(f"phonics word without a picture: {word}")


_check_vocabulary()
