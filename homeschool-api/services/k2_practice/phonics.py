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

#: Domains whose questions work only by ear: a sight word is asked by saying
#: it, and nothing on screen says which word to find. When the child's device
#: cannot speak, these are neither served nor recorded, since a right answer
#: would be a lucky guess. A first-sound question keeps its picture, so it
#: stays.
AUDIO_ONLY_DOMAINS = frozenset({"sight_words"})

# ── The authored word lists ─────────────────────────────────────────────────

#: Rhyming pairs. Every pair has its own ending sound, so a word from another
#: pair never rhymes with the target.
RHYME_PAIRS: tuple[tuple[str, str], ...] = (
    ("cat", "hat"), ("dog", "frog"), ("bee", "tree"), ("cake", "snake"), ("goat", "boat"),
    ("bear", "chair"), ("mouse", "house"), ("moon", "spoon"), ("fox", "box"), ("bed", "bread"),
    ("star", "car"), ("bone", "phone"), ("sock", "lock"), ("king", "ring"), ("fan", "van"),
    ("drum", "thumb"), ("nest", "vest"), ("bell", "shell"), ("whale", "snail"), ("rain", "train"),
    ("fish", "dish"), ("nut", "hut"),
)

#: A picture and the letter its first sound is written with. Each letter has
#: one sound here, and every picture starts with that plain sound (no
#: digraphs such as sh, ch, th or ph, and no silent first letters).
FIRST_SOUNDS: tuple[tuple[str, str], ...] = (
    ("sun", "s"), ("sock", "s"), ("seal", "s"), ("soap", "s"),
    ("moon", "m"), ("mouse", "m"), ("map", "m"),
    ("dog", "d"), ("duck", "d"), ("dish", "d"),
    ("bee", "b"), ("ball", "b"), ("bus", "b"), ("bell", "b"), ("bat", "b"),
    ("fish", "f"), ("fox", "f"), ("fan", "f"),
    ("pig", "p"), ("pen", "p"),
    ("hat", "h"), ("house", "h"), ("horse", "h"), ("hut", "h"),
    ("leaf", "l"), ("lion", "l"), ("lock", "l"), ("log", "l"),
    ("rain", "r"), ("rabbit", "r"), ("ring", "r"), ("rock", "r"), ("rope", "r"),
    ("goat", "g"), ("girl", "g"),
    ("water", "w"), ("wolf", "w"), ("web", "w"),
    ("tooth", "t"), ("tent", "t"), ("turtle", "t"), ("tiger", "t"),
    ("nest", "n"), ("nut", "n"), ("nose", "n"),
    ("van", "v"), ("vest", "v"),
    ("king", "k"), ("kite", "k"), ("key", "k"),
    ("jar", "j"), ("yarn", "y"), ("zebra", "z"),
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
        ("bat", (("b", "buh"), ("a", "ah"), ("t", "tuh"))),
        ("rat", (("r", "rrr"), ("a", "ah"), ("t", "tuh"))),
        ("van", (("v", "vvv"), ("a", "ah"), ("n", "nnn"))),
        ("fan", (("f", "fff"), ("a", "ah"), ("n", "nnn"))),
        ("pen", (("p", "puh"), ("e", "eh"), ("n", "nnn"))),
        ("net", (("n", "nnn"), ("e", "eh"), ("t", "tuh"))),
        ("web", (("w", "wuh"), ("e", "eh"), ("b", "buh"))),
        ("log", (("l", "lll"), ("o", "aw"), ("g", "guh"))),
        ("nut", (("n", "nnn"), ("u", "uh"), ("t", "tuh"))),
        ("bug", (("b", "buh"), ("u", "uh"), ("g", "guh"))),
        ("cap", (("c", "kuh"), ("a", "ah"), ("p", "puh"))),
        ("bag", (("b", "buh"), ("a", "ah"), ("g", "guh"))),
        ("hut", (("h", "huh"), ("u", "uh"), ("t", "tuh"))),
    ),
    "blends_digraphs": (
        ("fish", (("f", "fff"), ("i", "ih"), ("sh", "shh"))),
        ("ship", (("sh", "shh"), ("i", "ih"), ("p", "puh"))),
        ("frog", (("f", "fff"), ("r", "rrr"), ("o", "aw"), ("g", "guh"))),
        ("duck", (("d", "duh"), ("u", "uh"), ("ck", "kuh"))),
        ("truck", (("t", "tuh"), ("r", "rrr"), ("u", "uh"), ("ck", "kuh"))),
        ("plant", (("p", "puh"), ("l", "lll"), ("a", "ah"), ("n", "nnn"), ("t", "tuh"))),
        ("crab", (("c", "kuh"), ("r", "rrr"), ("a", "ah"), ("b", "buh"))),
        ("drum", (("d", "duh"), ("r", "rrr"), ("u", "uh"), ("m", "mmm"))),
        ("sled", (("s", "sss"), ("l", "lll"), ("e", "eh"), ("d", "duh"))),
        ("shell", (("sh", "shh"), ("e", "eh"), ("ll", "lll"))),
        ("clock", (("c", "kuh"), ("l", "lll"), ("o", "aw"), ("ck", "kuh"))),
        ("flag", (("f", "fff"), ("l", "lll"), ("a", "ah"), ("g", "guh"))),
        ("nest", (("n", "nnn"), ("e", "eh"), ("s", "sss"), ("t", "tuh"))),
        ("tent", (("t", "tuh"), ("e", "eh"), ("n", "nnn"), ("t", "tuh"))),
        ("skunk", (("s", "sss"), ("k", "kuh"), ("u", "uh"), ("n", "nnn"), ("k", "kuh"))),
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
        ("kite", (("k", "kuh"), ("i", "eye"), ("t", "tuh"), ("e", ""))),
        ("rope", (("r", "rrr"), ("o", "oh"), ("p", "puh"), ("e", ""))),
        ("nose", (("n", "nnn"), ("o", "oh"), ("s", "zzz"), ("e", ""))),
        ("train", (("t", "tuh"), ("r", "rrr"), ("ai", "ay"), ("n", "nnn"))),
        ("snail", (("s", "sss"), ("n", "nnn"), ("ai", "ay"), ("l", "lll"))),
        ("queen", (("qu", "kwuh"), ("ee", "ee"), ("n", "nnn"))),
        ("seal", (("s", "sss"), ("ea", "ee"), ("l", "lll"))),
        ("soap", (("s", "sss"), ("oa", "oh"), ("p", "puh"))),
        ("plane", (("p", "puh"), ("l", "lll"), ("a", "ay"), ("n", "nnn"), ("e", ""))),
    ),
}

#: Common words that cannot be sounded out, read by sight.
SIGHT_WORDS: tuple[str, ...] = (
    "the", "was", "said", "of", "you", "are", "to", "one", "they", "have",
    "were", "what", "where", "do", "come", "some", "there", "two", "who", "your",
    "give", "put", "want", "could", "would",
)

#: The sound of each first-sound letter, spoken when a letter choice is
#: tapped in Watch and Together. Consonants only, so each has one sound here.
LETTER_SOUNDS = {
    "s": "sss", "m": "mmm", "d": "duh", "b": "buh", "f": "fff", "p": "puh",
    "h": "huh", "l": "lll", "r": "rrr", "g": "guh", "w": "wuh", "t": "tuh",
    "n": "nnn", "v": "vvv", "k": "kuh", "j": "juh", "y": "yuh", "z": "zzz",
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
    "phone": ("telefono",), "sock": ("calcetin",), "lock": ("candado",), "king": ("rey",),
    "ring": ("anillo",), "fan": ("abanico",), "van": ("camioneta",), "drum": ("tambor",),
    "thumb": ("pulgar",), "nest": ("nido",), "vest": ("chaleco",), "bell": ("campana",),
    "shell": ("concha",), "whale": ("ballena",), "snail": ("caracol",), "train": ("tren",),
    "dish": ("plato",), "nut": ("cacahuate", "nuez"), "hut": ("choza",), "seal": ("foca",),
    "soap": ("jabon",), "ball": ("pelota",), "bat": ("murcielago",), "pen": ("pluma",),
    "horse": ("caballo",), "lion": ("leon",), "log": ("tronco",), "rabbit": ("conejo",),
    "rock": ("piedra", "roca"), "rope": ("cuerda",), "girl": ("nina",), "water": ("agua",),
    "wolf": ("lobo",), "web": ("telarana",), "tooth": ("diente",), "tent": ("tienda",),
    "turtle": ("tortuga",), "tiger": ("tigre",), "nose": ("nariz",), "kite": ("papalote",),
    "key": ("llave",), "jar": ("frasco",), "yarn": ("estambre",), "zebra": ("cebra",),
    "rat": ("rata",), "bug": ("bicho",), "cap": ("gorra",), "bag": ("bolsa",),
    "crab": ("cangrejo",), "sled": ("trineo",), "clock": ("reloj",), "flag": ("bandera",),
    "skunk": ("zorrillo",), "queen": ("reina",), "plane": ("avion",),
}
_LETTER_SPOKEN = {
    "s": ("ess", "ese"), "m": ("em", "eme"), "d": ("dee",), "b": ("bee", "be"), "f": ("ef", "efe"),
    "p": ("pee", "pe"), "h": ("aitch", "hache"), "l": ("ele",), "r": ("ar", "erre", "ere"),
    "g": ("gee", "ge"), "w": (), "t": ("tee",),
    "n": ("en", "ene"), "v": ("vee", "uve"), "k": ("kay", "ka"), "j": ("jay", "jota"),
    "y": ("why", "ye"), "z": ("zee", "zed", "zeta"),
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


#: The letters first-sound questions use, each once per lesson.
FIRST_LETTERS: tuple[str, ...] = tuple(dict.fromkeys(letter for _, letter in FIRST_SOUNDS))

#: Each lesson asks one kind of question, chosen from its seed, so the Watch
#: step shows exactly what the child is about to do while lessons vary.
KINDS: dict[str, tuple[str, ...]] = {
    "phonological_awareness": ("rhyme_choice", "rhyme_odd_choice"),
    "letter_sound": ("first_sound_choice", "starts_with_choice"),
}
_POSITIONS_ALL = range(1 + TOGETHER_TASKS + YOUR_TURN_TASKS)


def _kind(level: str, domain: str, seed: int) -> str:
    kinds = KINDS.get(domain, ("",))
    return kinds[random.Random(f"phonics:{level}:{domain}:{seed}:kind").randrange(len(kinds))]


def _position(phase: str, index: int) -> int:
    return {"watch": 0, "together": 1, "your_turn": 1 + TOGETHER_TASKS}[phase] + index


def _build(level: str, domain: str, seed: int, phase: str, index: int) -> Task:
    rng = random.Random(f"phonics:{level}:{domain}:{seed}:{phase}:{index}")
    n = CHOICES_PER_LEVEL[level]
    pos = _position(phase, index)

    if domain == "phonological_awareness":
        if _kind(level, domain, seed) == "rhyme_odd_choice":
            # Two words that rhyme and one that does not: tap the odd one. Always
            # three choices, at every level: a fourth would be a second odd one.
            pairs = _order(level, domain, seed, len(RHYME_PAIRS))
            pair = RHYME_PAIRS[pairs[pos % len(pairs)]]
            other = RHYME_PAIRS[pairs[(pos + len(_POSITIONS_ALL)) % len(pairs)]]
            odd = other[rng.randrange(2)]
            choices = [pair[0], pair[1], odd]
            rng.shuffle(choices)
            return Task(domain, "rhyme_odd_choice", {"words": ", ".join(choices)},
                        {"kind": "none"}, "picture", tuple(choices), odd)
        pair = RHYME_PAIRS[_order(level, domain, seed, len(RHYME_PAIRS))[pos % len(RHYME_PAIRS)]]
        target, rhyme = (pair if rng.random() < 0.5 else (pair[1], pair[0]))
        pool = [w for p in RHYME_PAIRS if p != pair for w in p] + [rhyme]
        return Task(domain, "rhyme_choice", {"word": target},
                    {"kind": "picture", "icon": target, "word": target},
                    "picture", _choices(rng, rhyme, pool, n), rhyme)

    if domain == "letter_sound":
        # A lesson never repeats a letter; which picture stands for the
        # letter changes from lesson to lesson.
        letter = FIRST_LETTERS[_order(level, domain, seed, len(FIRST_LETTERS))[pos % len(FIRST_LETTERS)]]
        pictures = [p_ for p_, l_ in FIRST_SOUNDS if l_ == letter]
        picture = pictures[random.Random(f"phonics:{level}:{domain}:{seed}:{pos}:picture").randrange(len(pictures))]
        if _kind(level, domain, seed) == "starts_with_choice":
            # The letter is shown; tap the one picture that starts with it.
            others: dict[str, str] = {}
            for p_, l_ in sorted(FIRST_SOUNDS, key=lambda e: rng.random()):
                if l_ != letter and l_ not in others:
                    others[l_] = p_
            picked = [picture] + list(others.values())[: n - 1]
            rng.shuffle(picked)
            return Task(domain, "starts_with_choice", {"letter": letter, "sound": LETTER_SOUNDS[letter]},
                        {"kind": "word", "graphemes": [{"text": letter, "sound": LETTER_SOUNDS[letter]}], "word": letter},
                        "picture", tuple(picked), picture)
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


def build_lesson(level: str, seed: int, domain: str, audio: bool = True) -> dict:
    """The whole lesson as sent to the child's screen. The answer is sent for
    Watch only; Together and Your turn are checked on the server.

    `audio=False` (the child's device cannot speak) may only REMOVE questions:
    it never changes the level or the domain. A domain that works only by ear
    then has no questions, and the lesson says it needs sound."""
    if level not in LEVELS or domain not in DOMAINS:
        raise ValueError("unknown level or domain")
    if not audio and domain in AUDIO_ONLY_DOMAINS:
        return {
            "area": "phonics", "level": level, "domain": domain, "label": DOMAIN_LABELS[domain],
            "audio": False, "needs_audio": True, "watch": None, "together": [], "your_turn": [],
        }
    return {
        "area": "phonics", "level": level, "domain": domain, "label": DOMAIN_LABELS[domain],
        "audio": audio, "needs_audio": False,
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


def speech_echoes_answer(task: Task) -> bool:
    """Whether the spoken instruction contains the answer, so saying it back
    shows only that the child heard it."""
    answer = task.accept_choice.lower()
    return any(isinstance(v, str) and v.lower() == answer for v in task.prompt_args.values())


def match_spoken(task: Task, text: str) -> Optional[str]:
    """The question's own choice a spoken answer names, or None when it names
    none or more than one. The same rule as map_practice.match_spoken, with
    this area's own words. Never returns anything outside `task.choices`.

    A question whose spoken instruction says its own answer (a sight word:
    "Tap the word said") takes no spoken answer at all: repeating what was
    just heard is an echo, not a reading. Such an answer counts as neither a
    miss nor an answer, like speech that matched nothing."""
    if speech_echoes_answer(task):
        return None
    words = set("".join(ch.lower() if ch.isalnum() else " " for ch in _plain((text or "")[:200])).split())
    hits = [c for c in task.choices if any(w in words for w in spoken_forms(task, c))]
    return hits[0] if len(hits) == 1 else None


def _check_vocabulary() -> None:
    for word in [w for p in RHYME_PAIRS for w in p] + [p for p, _ in FIRST_SOUNDS] + \
            [w for ws in DECODABLE.values() for w, _ in ws]:
        if word not in ICONS:  # pragma: no cover - guarded by tests
            raise RuntimeError(f"phonics word without a picture: {word}")


_check_vocabulary()
