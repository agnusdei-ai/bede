"""Map-reading practice for K-2, drawn and checked by code.

Charlotte Mason's "home geography": maps of places a child knows, with
position and direction words. Three levels, kept distinct on purpose:

    K   position words, a map as a picture from above, following a path
    1   symbols and a key, the four directions, placing things on a map
    2   the compass rose, grid squares, land and water

What is left out is the abstract part (scale, latitude and longitude, real
road or atlas maps), which is too early for these grades.

Three rules this module holds:

1. **Maps are drawn by code, never by a model.** Every scene is built here
   from a closed set of symbols, and every answer is computed here. No model
   output reaches a map, and no real place is ever drawn. Real geography
   facts stay in lessons, from the sourced visual-aid catalog.
2. **Nothing about where a child lives.** No task asks for a street, a town
   or a neighbourhood, and no free text is accepted: an answer is a tapped
   square, one of the offered choices, or a spoken word matched to one of
   those choices.
3. **No mastery score.** Completed practice goes in the work ledger only
   (services/diagnostic/activity.py), as an event. There is no geography
   estimate and nothing here feeds one.

Everything is a pure function of (level, skill, seed), so a lesson is never
stored: the routes rebuild the same lesson to check an answer.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

# ── Closed vocabularies ──────────────────────────────────────────────────────

#: Everything a practice map can show. The frontend draws exactly these.
SYMBOLS = ("house", "tree", "pond", "gate", "well", "barn", "bridge", "rock", "flower", "bench")

LEVELS = ("K", "1", "2")

#: Three skills per level, in teaching order. A level never borrows another
#: level's skill: that is what keeps K, 1 and 2 distinct.
SKILLS: dict[str, tuple[str, ...]] = {
    "K": ("position_words", "birds_eye", "follow_path"),
    "1": ("symbols_and_key", "four_directions", "place_on_map"),
    "2": ("compass_rose", "grid_squares", "land_and_water"),
}

#: What a parent reads in the work ledger.
SKILL_LABELS: dict[str, str] = {
    "position_words": "Map skills: position words",
    "birds_eye": "Map skills: a map is a picture from above",
    "follow_path": "Map skills: following a path",
    "symbols_and_key": "Map skills: symbols and a key",
    "four_directions": "Map skills: north, south, east and west",
    "place_on_map": "Map skills: placing things on a map",
    "compass_rose": "Map skills: using a compass rose",
    "grid_squares": "Map skills: finding a grid square",
    "land_and_water": "Map skills: land and water",
}

LEDGER_SUBJECT_AREA = "map_skills"

DIRECTIONS = ("north", "south", "east", "west")
_STEP = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
POSITIONS = ("above", "below", "left_of", "right_of")
_POSITION_STEP = {"above": (0, -1), "below": (0, 1), "left_of": (-1, 0), "right_of": (1, 0)}
GROUND = ("land", "water")
COLUMN_LETTERS = "ABCDE"

TOGETHER_TASKS = 2
YOUR_TURN_TASKS = 3

#: Words a child may say for a choice, per locale. Matching is whole-word and
#: only ever resolves to one of the task's own choices.
_SPOKEN = {
    "north": ("north", "norte"), "south": ("south", "sur"),
    "east": ("east", "este"), "west": ("west", "oeste"),
    "above": ("above", "over", "arriba", "encima"),
    "below": ("below", "under", "abajo", "debajo"),
    "left_of": ("left", "izquierda"), "right_of": ("right", "derecha"),
    "land": ("land", "tierra"), "water": ("water", "agua"),
    "house": ("house", "casa"), "tree": ("tree", "arbol", "árbol"),
    "pond": ("pond", "estanque"), "gate": ("gate", "puerta", "reja"),
    "well": ("well", "pozo"), "barn": ("barn", "granero"),
    "bridge": ("bridge", "puente"), "rock": ("rock", "roca", "piedra"),
    "flower": ("flower", "flor"), "bench": ("bench", "banca", "banco"),
}

Cell = tuple[int, int]


def level_for_grade(grade: str) -> Optional[str]:
    """The practice level for a grade, or None when map practice is not
    offered (grade 3 and up, or anything unrecognised)."""
    g = (grade or "").strip().upper()
    return g if g in LEVELS else None


def cell_label(cell: Cell) -> str:
    """'B2' for column 1, row 1. Letters run west to east, numbers north to south."""
    return f"{COLUMN_LETTERS[cell[0]]}{cell[1] + 1}"


# ── Scene and task ───────────────────────────────────────────────────────────

@dataclass
class Scene:
    cols: int
    rows: int
    items: list[tuple[str, Cell]] = field(default_factory=list)
    water: list[Cell] = field(default_factory=list)
    path: list[Cell] = field(default_factory=list)
    #: "none", "north_only" (an arrow marked N) or "labeled" (N, S, E, W).
    compass: str = "none"
    grid_labels: bool = False
    key: bool = False
    #: "picture" for K (a picture seen from above), "map" for 1 and 2.
    style: str = "map"

    def at(self, cell: Cell) -> Optional[str]:
        return next((s for s, c in self.items if c == cell), None)

    def where(self, symbol: str) -> Cell:
        return next(c for s, c in self.items if s == symbol)

    def inside(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.cols and 0 <= cell[1] < self.rows

    def public(self) -> dict:
        return {
            "cols": self.cols, "rows": self.rows, "style": self.style,
            "items": [{"symbol": s, "col": c[0], "row": c[1]} for s, c in self.items],
            "water": [list(c) for c in self.water],
            "path": [list(c) for c in self.path],
            "compass": self.compass, "grid_labels": self.grid_labels, "key": self.key,
        }


@dataclass
class Task:
    scene: Scene
    prompt_key: str
    prompt_args: dict
    #: "tap" (a square), "choice" (one of `choices`) or "scene_choice" (one
    #: of `options`, each a small map).
    answer_kind: str
    choices: tuple[str, ...] = ()
    options: tuple[Scene, ...] = ()
    #: Squares that are right, for a tap. One square for most tasks.
    accept_cells: frozenset = frozenset()
    #: The right choice, or the right option's index as a string.
    accept_choice: Optional[str] = None
    #: A side view shown above the options (birds_eye only): symbols left to right.
    side_view: tuple[str, ...] = ()
    #: Squares softly marked in Together only. Never sent in Your turn.
    guide_cells: tuple[Cell, ...] = ()
    #: One square the question is about, ringed in every phase.
    marked: Optional[Cell] = None

    def is_right(self, *, cell: Optional[Cell] = None, choice: Optional[str] = None) -> bool:
        if self.answer_kind == "tap":
            return cell is not None and tuple(cell) in self.accept_cells
        return choice is not None and choice == self.accept_choice

    def reveal(self) -> dict:
        """The answer, for showing after a miss. Deterministic."""
        if self.answer_kind == "tap":
            return {"cell": list(min(self.accept_cells))}
        return {"choice": self.accept_choice}

    def public(self, phase: str, index: int) -> dict:
        out = {
            "phase": phase, "index": index, "scene": self.scene.public(),
            "prompt": {"key": self.prompt_key, "args": self.prompt_args},
            "answer_kind": self.answer_kind,
        }
        if self.choices:
            out["choices"] = list(self.choices)
        if self.options:
            out["options"] = [o.public() for o in self.options]
        if self.side_view:
            out["side_view"] = list(self.side_view)
        if self.marked is not None:
            out["marked"] = list(self.marked)
        if phase == "together" and self.guide_cells:
            out["guide_cells"] = [list(c) for c in self.guide_cells]
        return out


# ── Building blocks ──────────────────────────────────────────────────────────

def _all_cells(cols: int, rows: int) -> list[Cell]:
    return [(c, r) for r in range(rows) for c in range(cols)]


def _scatter(rng: random.Random, scene: Scene, symbols: list[str], avoid: set) -> None:
    free = [c for c in _all_cells(scene.cols, scene.rows)
            if c not in avoid and scene.at(c) is None and c not in scene.water]
    rng.shuffle(free)
    for symbol, cell in zip(symbols, free):
        scene.items.append((symbol, cell))


def _line(scene: Scene, start: Cell, direction: str) -> list[Cell]:
    """Squares from `start` (not included) to the edge, going `direction`."""
    dc, dr = _STEP[direction]
    out, cur = [], (start[0] + dc, start[1] + dr)
    while scene.inside(cur):
        out.append(cur)
        cur = (cur[0] + dc, cur[1] + dr)
    return out


def _pick(rng: random.Random, pool, n: int, exclude=()) -> list:
    choices = [p for p in pool if p not in exclude]
    rng.shuffle(choices)
    return choices[:n]


def _with_hints(scene: Scene, phase: str, *, labeled_compass: bool = False) -> None:
    """Together shows the supports; Your turn takes them away."""
    if labeled_compass:
        scene.compass = "labeled" if phase != "your_turn" else "north_only"


# ── Level K ──────────────────────────────────────────────────────────────────

def _k_position_words(rng: random.Random, phase: str) -> Task:
    scene = Scene(4, 3, style="picture")
    a, b, c = _pick(rng, SYMBOLS, 3)
    centre = (1, 1)
    position = rng.choice(POSITIONS)
    dc, dr = _POSITION_STEP[position]
    # A third thing in the far column: two squares from the centre, so it
    # does not touch it even at a corner and "next to" has one answer.
    scene.items = [(b, centre), (a, (1 + dc, 1 + dr)), (c, (3, rng.randrange(3)))]
    if rng.random() < 0.5:
        return Task(scene, "position_choice", {"thing": a, "reference": b}, "choice",
                    choices=POSITIONS, accept_choice=position,
                    guide_cells=(scene.where(a), centre))
    return Task(scene, "next_to_tap", {"reference": b}, "tap",
                accept_cells=frozenset({scene.where(a)}),
                guide_cells=(centre,))


def _k_birds_eye(rng: random.Random, phase: str) -> Task:
    symbols = _pick(rng, SYMBOLS, 3)
    rows = [0, 1, 2]
    rng.shuffle(rows)

    def overhead(order: list[str]) -> Scene:
        return Scene(3, 3, items=[(s, (col, rows[col])) for col, s in enumerate(order)], style="picture")

    orders = [symbols, [symbols[1], symbols[0], symbols[2]], [symbols[0], symbols[2], symbols[1]]]
    slots = [0, 1, 2]
    rng.shuffle(slots)
    options = [None, None, None]
    for order, slot in zip(orders, slots):
        options[slot] = overhead(order)
    return Task(overhead(symbols), "birds_eye_match", {}, "scene_choice",
                options=tuple(options), accept_choice=str(slots[0]), side_view=tuple(symbols))


def _k_follow_path(rng: random.Random, phase: str) -> Task:
    scene = Scene(4, 3, style="picture")
    start = (0, rng.randrange(3))
    end = (3, rng.choice([r for r in range(3) if r != start[1]]))
    turn_col = rng.choice([1, 2])
    path = [(c, start[1]) for c in range(1, turn_col + 1)]
    step = 1 if end[1] > start[1] else -1
    path += [(turn_col, r) for r in range(start[1] + step, end[1] + step, step)]
    path += [(c, end[1]) for c in range(turn_col + 1, 3)]
    target, other = _pick(rng, SYMBOLS, 2, exclude=("gate",))
    scene.items = [("gate", start), (target, end)]
    scene.path = path
    # Nothing else may touch the path's last square, or the path would seem
    # to end at two things.
    last = path[-1]
    beside_end = {(last[0] + dc, last[1] + dr) for dc, dr in _STEP.values()}
    _scatter(rng, scene, [other], avoid=set(path) | {start, end} | beside_end)
    return Task(scene, "path_end_tap", {"start": "gate"}, "tap",
                accept_cells=frozenset({end}), guide_cells=tuple(path))


# ── Level 1 ──────────────────────────────────────────────────────────────────

def _one_symbols_and_key(rng: random.Random, phase: str) -> Task:
    scene = Scene(4, 4, key=True)
    symbols = _pick(rng, SYMBOLS, 4)
    _scatter(rng, scene, symbols, avoid=set())
    target = symbols[0]
    cell = scene.where(target)
    if rng.random() < 0.5:
        return Task(scene, "find_symbol_tap", {"thing": target}, "tap",
                    accept_cells=frozenset({cell}), guide_cells=())
    choices = tuple(sorted(symbols))
    return Task(scene, "symbol_meaning_choice", {"square": list(cell)}, "choice",
                choices=choices, accept_choice=target, marked=cell)


def _aligned_scene(rng: random.Random, size: int, reference: str) -> tuple[Scene, dict[str, str]]:
    """A map with `reference` away from the edge and one thing in each of
    two or three directions from it, in a straight line."""
    scene = Scene(size, size)
    ref = (rng.randrange(1, size - 1), rng.randrange(1, size - 1))
    scene.items.append((reference, ref))
    placed: dict[str, str] = {}
    directions = _pick(rng, DIRECTIONS, rng.choice([2, 3]))
    things = _pick(rng, SYMBOLS, len(directions), exclude=(reference,))
    for direction, thing in zip(directions, things):
        scene.items.append((thing, rng.choice(_line(scene, ref, direction))))
        placed[direction] = thing
    return scene, placed


def _one_four_directions(rng: random.Random, phase: str) -> Task:
    scene, placed = _aligned_scene(rng, 4, "house")
    _with_hints(scene, phase, labeled_compass=True)
    direction = rng.choice(sorted(placed))
    thing = placed[direction]
    ref = scene.where("house")
    if rng.random() < 0.5:
        return Task(scene, "direction_tap", {"direction": direction, "reference": "house"}, "tap",
                    accept_cells=frozenset({scene.where(thing)}),
                    guide_cells=tuple(_line(scene, ref, direction)))
    return Task(scene, "direction_choice", {"thing": thing, "reference": "house"}, "choice",
                choices=DIRECTIONS, accept_choice=direction,
                guide_cells=(ref, scene.where(thing)))


def _one_place_on_map(rng: random.Random, phase: str) -> Task:
    scene = Scene(4, 4)
    ref = (rng.randrange(1, 3), rng.randrange(1, 3))
    reference, thing, other = _pick(rng, SYMBOLS, 3)
    scene.items.append((reference, ref))
    direction = rng.choice(DIRECTIONS)
    line = _line(scene, ref, direction)
    _scatter(rng, scene, [other], avoid=set(line) | {ref})
    _with_hints(scene, phase, labeled_compass=True)
    return Task(scene, "place_tap", {"thing": thing, "direction": direction, "reference": reference},
                "tap", accept_cells=frozenset(line), guide_cells=tuple(line))


# ── Level 2 ──────────────────────────────────────────────────────────────────

def _two_compass_rose(rng: random.Random, phase: str) -> Task:
    scene = Scene(5, 5, grid_labels=False)
    _with_hints(scene, phase, labeled_compass=True)
    start = (rng.randrange(1, 4), rng.randrange(1, 4))
    first = rng.choice(DIRECTIONS)
    second = rng.choice([d for d in DIRECTIONS if _STEP[d][0] != _STEP[first][0] and _STEP[d][1] != _STEP[first][1]])

    def walk(cell: Cell, direction: str, steps: int) -> Cell:
        return (cell[0] + _STEP[direction][0] * steps, cell[1] + _STEP[direction][1] * steps)

    first_steps = rng.choice([n for n in (1, 2) if scene.inside(walk(start, first, n))])
    mid = walk(start, first, first_steps)
    second_steps = rng.choice([n for n in (1, 2) if scene.inside(walk(mid, second, n))])
    end = walk(mid, second, second_steps)
    scene.items.append(("gate", start))
    route = [walk(start, first, n) for n in range(1, first_steps + 1)]
    route += [walk(mid, second, n) for n in range(1, second_steps + 1)]
    _scatter(rng, scene, _pick(rng, SYMBOLS, 2, exclude=("gate",)), avoid={start, *route})
    return Task(scene, "walk_tap",
                {"start": "gate", "first_steps": first_steps, "first": first,
                 "second_steps": second_steps, "second": second},
                "tap", accept_cells=frozenset({end}), guide_cells=tuple(route))


def _two_grid_squares(rng: random.Random, phase: str) -> Task:
    scene = Scene(5, 5, grid_labels=True)
    symbols = _pick(rng, SYMBOLS, 3)
    _scatter(rng, scene, symbols, avoid=set())
    target = symbols[0]
    cell = scene.where(target)
    column = tuple((cell[0], r) for r in range(5))
    row = tuple((c, cell[1]) for c in range(5))
    if rng.random() < 0.5:
        return Task(scene, "square_tap", {"square": cell_label(cell)}, "tap",
                    accept_cells=frozenset({cell}), guide_cells=column + row)
    wrong = _pick(rng, [cell_label(c) for c in _all_cells(5, 5)], 3, exclude=(cell_label(cell),))
    choices = tuple(sorted(wrong + [cell_label(cell)]))
    return Task(scene, "square_choice", {"thing": target}, "choice",
                choices=choices, accept_choice=cell_label(cell), guide_cells=column + row)


def _two_land_and_water(rng: random.Random, phase: str) -> Task:
    scene = Scene(5, 5, grid_labels=True)
    river_col = rng.randrange(1, 4)
    water = [(river_col, r) for r in range(5)]
    bend = rng.randrange(1, 4)
    side = rng.choice([-1, 1])
    water += [(river_col + side, r) for r in range(bend, 5)] if rng.random() < 0.5 else []
    scene.water = sorted(set(c for c in water if scene.inside(c)))
    _scatter(rng, scene, _pick(rng, SYMBOLS, 2, exclude=("pond", "bridge", "well")), avoid=set(scene.water))
    if rng.random() < 0.5:
        ground = rng.choice(GROUND)
        accept = frozenset(scene.water) if ground == "water" else frozenset(
            c for c in _all_cells(5, 5) if c not in scene.water)
        return Task(scene, "ground_tap", {"ground": ground}, "tap",
                    accept_cells=accept, guide_cells=tuple(sorted(accept)))
    cell = rng.choice(_all_cells(5, 5))
    ground = "water" if cell in scene.water else "land"
    return Task(scene, "ground_choice", {"square": cell_label(cell)}, "choice",
                choices=GROUND, accept_choice=ground, marked=cell)


_BUILDERS = {
    "position_words": _k_position_words, "birds_eye": _k_birds_eye, "follow_path": _k_follow_path,
    "symbols_and_key": _one_symbols_and_key, "four_directions": _one_four_directions,
    "place_on_map": _one_place_on_map,
    "compass_rose": _two_compass_rose, "grid_squares": _two_grid_squares,
    "land_and_water": _two_land_and_water,
}

PHASES = ("together", "your_turn")
_PHASE_COUNT = {"together": TOGETHER_TASKS, "your_turn": YOUR_TURN_TASKS}


# ── The lesson ───────────────────────────────────────────────────────────────

def skill_for(level: str, seed: int, requested: Optional[str] = None) -> str:
    """The skill a lesson practises: the requested one when it belongs to
    this level, otherwise the level's skills in turn by seed."""
    skills = SKILLS[level]
    return requested if requested in skills else skills[seed % len(skills)]


def build_task(level: str, skill: str, seed: int, phase: str, index: int) -> Task:
    """One task, the same every time for the same arguments."""
    if level not in LEVELS or skill not in SKILLS[level]:
        raise ValueError("unknown level or skill")
    if phase not in PHASES or not 0 <= index < _PHASE_COUNT[phase]:
        raise ValueError("unknown task")
    rng = random.Random(f"map:{level}:{skill}:{seed}:{phase}:{index}")
    return _BUILDERS[skill](rng, phase)


def build_watch(level: str, skill: str, seed: int) -> dict:
    """The Watch step: a scene that tilts from a side view to a view from
    above, then one move shown. The move is a real task with its answer, so
    what Bede shows is exactly what the child is about to do."""
    rng = random.Random(f"map:{level}:{skill}:{seed}:watch")
    task = _BUILDERS[skill](rng, "together")
    return {
        "scene": task.scene.public(),
        "prompt": {"key": task.prompt_key, "args": task.prompt_args},
        "answer_kind": task.answer_kind,
        **({"choices": list(task.choices)} if task.choices else {}),
        **({"options": [o.public() for o in task.options]} if task.options else {}),
        **({"side_view": list(task.side_view)} if task.side_view else {}),
        **({"marked": list(task.marked)} if task.marked is not None else {}),
        "guide_cells": [list(c) for c in task.guide_cells],
        "answer": task.reveal(),
    }


def build_lesson(level: str, seed: int, requested_skill: Optional[str] = None) -> dict:
    """The whole lesson as sent to the child's screen. Answers are included
    for Watch only; Together and Your turn are checked on the server."""
    if level not in LEVELS:
        raise ValueError("unknown level")
    skill = skill_for(level, seed, requested_skill)
    return {
        "level": level, "skill": skill, "symbols": list(SYMBOLS),
        "watch": build_watch(level, skill, seed),
        "together": [build_task(level, skill, seed, "together", i).public("together", i)
                     for i in range(TOGETHER_TASKS)],
        "your_turn": [build_task(level, skill, seed, "your_turn", i).public("your_turn", i)
                      for i in range(YOUR_TURN_TASKS)],
    }


def match_spoken(task: Task, text: str) -> Optional[str]:
    """The task's own choice a spoken answer names, or None when it names
    none or more than one. Never returns anything outside `task.choices`."""
    if task.answer_kind != "choice":
        return None
    words = set("".join(ch.lower() if ch.isalnum() else " " for ch in (text or "")[:200]).split())
    hits = []
    for choice in task.choices:
        spoken = _SPOKEN.get(choice, (choice.lower(),))
        if any(w in words for w in spoken):
            hits.append(choice)
    return hits[0] if len(hits) == 1 else None
