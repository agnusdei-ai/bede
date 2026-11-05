"""Picture questions, in any subject: diagrams Bede can draw, check, and vary.

A question whose picture is the question (a shaded fraction, a clock, an
animal to name, a scene, a timeline, a Venn diagram, a table, the water
cycle) carries a `Diagram`
(models/practice.py): numbers and short labels from a closed list of kinds,
never markup. The app draws it (Diagram.tsx), and this module:

* works out the answer the picture shows (`answer`), from the diagram and the
  question's own words, or returns None when the question asks something it
  cannot settle (a bar graph's "how many more", say), so the item is left to
  the parent or marked for the adult to check;
* names the slip that produces a child's wrong answer (`explain`), and only
  slips a parent could check against the picture by hand;
* makes a fresh diagram of the same kind with its own answer (`new_like`), so
  practice is drawn too and the missed picture itself is never asked again.

Deterministic: every answer is counted or multiplied here, never written by a
model.
"""
from __future__ import annotations

import random
import re
from fractions import Fraction
from typing import Optional

from pydantic import TypeAdapter

from models.practice import ACTIONS, COIN_CENTS, ICONS, Diagram

_ADAPTER = TypeAdapter(Diagram)

# What a reader or a drafting model is told it may use. One copy, so the two
# prompts cannot drift from each other or from the model above.
PROMPT_SCHEMA = """  {"kind": "fraction_bar"|"fraction_circle", "parts": int, "shaded": int}
  {"kind": "array", "rows": int, "cols": int}
  {"kind": "base_ten", "hundreds": int, "tens": int, "ones": int}
  {"kind": "clock", "hour": 1-12, "minute": 0-59}
  {"kind": "rectangle", "width": int, "height": int, "unit": str}
  {"kind": "right_triangle", "base": int, "height": int, "unit": str}
  {"kind": "number_line", "start": int, "end": int, "step": int, "marks": [int], "mark_labels": [str]}
  {"kind": "bar_graph", "title": str, "bars": [{"label": str, "value": int}]}
  {"kind": "coordinate_plane", "size": int, "four_quadrants": bool, "points": [{"label": str, "x": int, "y": int}]}
  {"kind": "pictures", "groups": [{"icon": ICON, "count": int, "label": str}]}  (things to name, sort or count)
  {"kind": "scene", "icon": ICON, "action": ACTION|null}  (one thing doing one thing)
  {"kind": "timeline", "events": [{"label": str, "year": int}], "show_years": bool}  (negative years are BC)
  {"kind": "venn", "left": str, "right": str, "left_items": [str], "right_items": [str], "both_items": [str]}
  {"kind": "table", "header": [str], "rows": [[str]]}
  {"kind": "cycle"|"sequence", "steps": [str]}  (a step written "?" is a blank)
  {"kind": "ruler", "unit": "cm"|"in", "length": int, "objects": [{"label": str, "start": number, "end": number, "icon": ICON|null}]}  (things laid along a ruler, ends on whole or half units)
  {"kind": "money", "pieces": [{"coin": "penny"|"nickel"|"dime"|"quarter"|"half_dollar"|"dollar_coin"|"one_bill"|"five_bill"|"ten_bill"|"twenty_bill", "count": int}]}
  {"kind": "thermometer", "unit": "F"|"C", "low": int, "high": int, "step": int, "reading": int}
ICON is one of: """ + ", ".join(ICONS) + """
ACTION is one of: """ + ", ".join(ACTIONS) + """
Labels are short (about 20 characters at most)."""


def parse(raw) -> Optional[object]:
    """A diagram from a model's JSON, or None if it is not one we can draw."""
    if not isinstance(raw, dict):
        return None
    try:
        return _ADAPTER.validate_python(raw)
    except Exception:
        return None


def key(diagram) -> str:
    """Stable text for duplicate checks: two questions with one prompt but
    different pictures are different questions."""
    return "" if diagram is None else diagram.model_dump_json()


# ── Reading answers ───────────────────────────────────────────────────────────

def _number(text: str | None) -> Optional[Fraction]:
    from services.practice.packs.math import parse_answer

    return parse_answer(text)


def _time(text: str | None) -> Optional[tuple[int, int]]:
    t = (text or "").strip().lower()
    m = re.search(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\b", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\b(\d{1,2})\s*(o'?clock|oclock)\b", t)
        if not m:
            return None
        hour, minute = int(m.group(1)), 0
    if hour == 0:
        hour = 12
    if hour > 12:
        hour -= 12
    if not (1 <= hour <= 12 and 0 <= minute <= 59):
        return None
    return hour, minute


def _point(text: str | None) -> Optional[tuple[int, int]]:
    m = re.search(r"\(?\s*(−|-)?\s*(\d+)\s*,\s*(−|-)?\s*(\d+)\s*\)?", text or "")
    if not m:
        return None
    x = -int(m.group(2)) if m.group(1) else int(m.group(2))
    y = -int(m.group(4)) if m.group(3) else int(m.group(4))
    return x, y


def _fmt_time(hour: int, minute: int) -> str:
    return f"{hour}:{minute:02d}"


def _fmt_point(x: int, y: int) -> str:
    return f"({x}, {y})"


def _fmt_num(value: Fraction) -> str:
    from services.practice.packs.math import _fmt

    return _fmt(value)


def _measure(prompt: str) -> Optional[str]:
    words = (prompt or "").lower()
    if "perimeter" in words or "distance around" in words or "all the way around" in words:
        return "perimeter"
    if "area" in words:
        return "area"
    return None


def _named_point(diagram, prompt: str):
    """The labelled point a question names ("point B"), or the only one."""
    labels = [p.label for p in diagram.points] if diagram.kind == "coordinate_plane" else list(diagram.mark_labels)
    for label in labels:
        if re.search(rf"\b{re.escape(label)}\b", prompt or ""):
            return labels.index(label)
    count = len(diagram.points) if diagram.kind == "coordinate_plane" else len(diagram.marks)
    return 0 if count == 1 else None



# ── Measuring pictures: ruler, money, thermometer ─────────────────────────────

def _amount(text: str | None) -> Optional[Fraction]:
    """The first number in an answer, ignoring a unit ("9 cm", "2.5 in")."""
    m = re.search(r"-?\d+(?:\.\d+)?(?:\s+\d+/\d+|/\d+)?", (text or "").replace("−", "-"))
    return _number(m.group(0)) if m else None


def _cents(text: str | None) -> Optional[int]:
    t = (text or "").lower().replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", t)
    if not m:
        return None
    value = Fraction(m.group(0))
    if "$" in t or "dollar" in t or ("." in m.group(0) and "cent" not in t and "¢" not in t):
        value *= 100
    return int(value) if value.denominator == 1 else None


def _fmt_measure(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _fmt_cents(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}" if cents >= 100 else f"{cents}¢"


def _named(diagram, prompt: str) -> list:
    words = (prompt or "").lower()
    found = [(words.find(o.label.lower()), o) for o in diagram.objects
             if re.search(rf"(?<!\w){re.escape(o.label.lower())}(?!\w)", words)]
    return [o for _, o in sorted(found, key=lambda pair: pair[0])]


def _ruler_answer(diagram, prompt: str) -> Optional[str]:
    words = (prompt or "").lower()
    named = _named(diagram, prompt)
    length = lambda o: o.end - o.start
    if len(named) >= 2 and re.search(r"\b(total|together|altogether|in all|combined)\b", words):
        return _fmt_measure(sum(length(o) for o in named))
    if len(named) == 2 and re.search(r"\b(shorter|longer|difference|how much more|how much less)\b", words):
        return _fmt_measure(abs(length(named[0]) - length(named[1])))
    if len(named) == 1 or (len(diagram.objects) == 1 and not named):
        target = named[0] if named else diagram.objects[0]
        if re.search(r"\b(how long|length|long is|measure)\b", words):
            return _fmt_measure(length(target))
    return None


def answer(diagram, prompt: str) -> Optional[str]:
    """The answer the picture shows, as text, or None if it cannot be settled."""
    kind = diagram.kind
    if kind in ("fraction_bar", "fraction_circle"):
        words = (prompt or "").lower()
        shaded = diagram.parts - diagram.shaded if ("not shaded" in words or "unshaded" in words) else diagram.shaded
        return f"{shaded}/{diagram.parts}"
    if kind == "array":
        return str(diagram.rows * diagram.cols)
    if kind == "base_ten":
        return str(100 * diagram.hundreds + 10 * diagram.tens + diagram.ones)
    if kind == "clock":
        return _fmt_time(diagram.hour, diagram.minute)
    if kind == "rectangle":
        measure = _measure(prompt)
        if measure == "area":
            return str(diagram.width * diagram.height)
        if measure == "perimeter":
            return str(2 * (diagram.width + diagram.height))
        return None
    if kind == "right_triangle":
        if _measure(prompt) == "area":
            return _fmt_num(Fraction(diagram.base * diagram.height, 2))
        return None
    if kind == "number_line":
        index = _named_point(diagram, prompt)
        if index is None or index >= len(diagram.marks):
            return None
        return str(diagram.marks[index])
    if kind == "coordinate_plane":
        index = _named_point(diagram, prompt)
        if index is None:
            return None
        point = diagram.points[index]
        return _fmt_point(point.x, point.y)
    if kind == "ruler":
        return _ruler_answer(diagram, prompt)
    if kind == "money":
        if re.search(r"\b(how much|total|in all|altogether|worth)\b", (prompt or "").lower()):
            return _fmt_cents(sum(COIN_CENTS[p.coin] * p.count for p in diagram.pieces))
        return None
    if kind == "thermometer":
        if re.search(r"\b(temperature|how (hot|cold|warm)|degrees|read)\b", (prompt or "").lower()):
            return f"{diagram.reading}°{diagram.unit}"
        return None
    if kind == "pictures":
        words = (prompt or "").lower()
        if "how many" in words:
            groups = diagram.groups
            named = [g for g in groups if g.label and re.search(rf"\b{re.escape(g.label.lower())}\b", words)]
            if len(named) == 1:
                return str(named[0].count)
            if len(groups) == 1:
                return str(groups[0].count)
        return None
    # A bar graph, a scene, a timeline, a Venn diagram, a table or steps: the
    # question decides what is asked, so the adult checks the answer.
    return None


def same(diagram, given: str | None, right: str) -> bool:
    """Does the child's (or a model's) answer match the picture's answer?"""
    if diagram.kind == "clock":
        return _time(given) == _time(right)
    if diagram.kind == "coordinate_plane":
        return _point(given) == _point(right)
    if diagram.kind == "money":
        return _cents(given) is not None and _cents(given) == _cents(right)
    if diagram.kind in ("ruler", "thermometer"):
        a, b = _amount(given), _amount(right)
        return a is not None and a == b
    a, b = _number(given), _number(right)
    return a is not None and a == b


# ── Naming the slip ───────────────────────────────────────────────────────────

def explain(diagram, prompt: str, given: str | None) -> str:
    """Evidence for a wrong answer to a picture problem, or "" if no known
    slip explains it (then the parent is asked, as for any other miss)."""
    right = answer(diagram, prompt)
    if right is None or not (given or "").strip() or same(diagram, given, right):
        return ""
    kind = diagram.kind
    if kind == "coordinate_plane":
        return explain_point(diagram, prompt, given)
    if kind == "ruler":
        value = _amount(given)
        named = _named(diagram, prompt) or list(diagram.objects[:1])
        if value is None:
            return ""
        lengths = [Fraction(o.end - o.start).limit_denominator(2) for o in named]
        for o in named:
            if o.start and value == Fraction(o.end).limit_denominator(2):
                return f"wrote {given} for {right}: read the number where the {o.label} ends; it starts at {_fmt_measure(o.start)}, so count from there"
            if value == Fraction(o.end - o.start).limit_denominator(2) + 1:
                return f"wrote {given} for {right}: counted the marks instead of the spaces between them"
        if len(named) >= 2 and value in lengths:
            return f"wrote {given} for {right}: gave one length instead of putting the two together" \
                if "total" in (prompt or "").lower() or "together" in (prompt or "").lower() \
                else f"wrote {given} for {right}: gave a length, not how much longer or shorter one is"
        return ""
    if kind == "money":
        cents = _cents(given)
        if cents is not None and cents == sum(p.count for p in diagram.pieces):
            return f"wrote {given} for {right}: counted the coins, not what each one is worth"
        return ""
    if kind == "thermometer":
        value = _amount(given)
        if value is not None and value in (diagram.reading + diagram.step, diagram.reading - diagram.step):
            return f"wrote {given} for {right}: read the line next to the top of the liquid"
        return ""
    if kind in ("fraction_bar", "fraction_circle"):
        value = _number(given)
        p, s = diagram.parts, diagram.shaded
        if value is None:
            return ""
        if p - s and value == Fraction(s, p - s):
            return f"wrote {given} for {right}: compared the shaded parts with the unshaded ones, not with all {p} parts"
        if value == Fraction(p - s, p) and s != p - s:
            return f"wrote {given} for {right}: counted the parts that are not shaded"
        if s and value == Fraction(p, s):
            return f"wrote {given} for {right}: the fraction is upside down; the bottom number is how many parts in all"
        return ""
    if kind == "clock":
        time = _time(given)
        if time is None:
            return ""
        h, m = diagram.hour, diagram.minute
        if m % 5 == 0 and time == ((m // 5) or 12, (h % 12) * 5):
            return f"wrote {given} for {right}: read the two hands the other way round (the short hand shows the hour)"
        if time == ((h % 12) + 1, m) and m >= 30:
            return f"wrote {given} for {right}: read the next hour; the short hand has not reached {(h % 12) + 1} yet"
        return ""
    value = _number(given)
    if value is None:
        return ""
    if kind == "array":
        if value == diagram.rows + diagram.cols:
            return f"wrote {given} for {right}: added the rows and the columns instead of multiplying them"
        return ""
    if kind == "base_ten":
        h, t, o = diagram.hundreds, diagram.tens, diagram.ones
        if value == h + t + o:
            return f"wrote {given} for {right}: counted the blocks, not what each one is worth"
        if value in {100 * h + 10 * o + t, 100 * t + 10 * h + o, 100 * o + 10 * t + h} - {Fraction(right)}:
            return f"wrote {given} for {right}: put a digit in the wrong place (hundreds, tens, ones)"
        return ""
    if kind == "rectangle":
        w, h = diagram.width, diagram.height
        measure = _measure(prompt)
        if measure == "area" and value == 2 * (w + h):
            return f"wrote {given} for {right}: found the perimeter (the distance around) instead of the area"
        if measure == "perimeter" and value == w * h:
            return f"wrote {given} for {right}: found the area instead of the perimeter (the distance around)"
        if value == w + h:
            return f"wrote {given} for {right}: added two sides once; {'multiply them for the area' if measure == 'area' else 'go all the way around, every side'}"
        return ""
    if kind == "right_triangle":
        if value == diagram.base * diagram.height:
            return f"wrote {given} for {right}: multiplied base by height but did not halve it"
        return ""
    if kind == "number_line":
        if value in (Fraction(right) + diagram.step, Fraction(right) - diagram.step):
            return f"wrote {given} for {right}: one step out; count the spaces between the marks, not the marks"
        return ""
    return ""


def explain_point(diagram, prompt: str, given: str | None) -> str:
    """The coordinate-plane slip, kept apart because it compares pairs."""
    right = answer(diagram, prompt)
    point = _point(given)
    if right is None or point is None:
        return ""
    rx, ry = _point(right)
    if point == (ry, rx) and rx != ry:
        return f"wrote {given} for {right}: gave the up-and-down number first; x (across) comes first"
    return ""


# ── Fresh practice ────────────────────────────────────────────────────────────

_PROMPTS = {
    "fraction_bar": "What fraction of the bar is shaded?",
    "fraction_circle": "What fraction of the circle is shaded?",
    "array": "How many dots are there in all?",
    "base_ten": "What number do the blocks show?",
    "clock": "What time does the clock show?",
    "rectangle_area": "What is the area of the rectangle?",
    "rectangle_perimeter": "What is the perimeter of the rectangle?",
    "right_triangle": "What is the area of the triangle?",
    "number_line": "What number is at point A?",
    "coordinate_plane": "What are the coordinates of point A?",
}


def new_like(diagram, prompt: str, rng: random.Random):
    """(diagram, prompt, answer) of the same kind, or None for a kind with
    no fixed question (a bar graph)."""
    kind = diagram.kind
    d = None
    text = _PROMPTS.get(kind, "")
    if kind in ("fraction_bar", "fraction_circle"):
        parts = rng.choice([2, 3, 4, 5, 6, 8, 10, 12])
        d = {"kind": kind, "parts": parts, "shaded": rng.randint(1, parts - 1)}
    elif kind == "array":
        d = {"kind": "array", "rows": rng.randint(2, max(3, diagram.rows + 1)),
             "cols": rng.randint(2, max(3, diagram.cols + 1))}
    elif kind == "base_ten":
        d = {"kind": "base_ten", "hundreds": rng.randint(0, 3) if diagram.hundreds else 0,
             "tens": rng.randint(1, 9), "ones": rng.randint(0, 9)}
    elif kind == "clock":
        step = 1 if diagram.minute % 5 else (15 if diagram.minute % 15 == 0 else 5)
        d = {"kind": "clock", "hour": rng.randint(1, 12), "minute": step * rng.randint(0, 59 // step)}
    elif kind == "rectangle":
        measure = _measure(prompt) or "area"
        text = _PROMPTS[f"rectangle_{measure}"]
        d = {"kind": "rectangle", "width": rng.randint(2, 12), "height": rng.randint(2, 9), "unit": diagram.unit}
    elif kind == "right_triangle":
        d = {"kind": "right_triangle", "base": 2 * rng.randint(1, 6), "height": rng.randint(2, 10), "unit": diagram.unit}
    elif kind == "number_line":
        step = diagram.step
        start = diagram.start
        count = max(4, min(10, (diagram.end - diagram.start) // step))
        mark = start + step * rng.randint(1, count - 1)
        d = {"kind": "number_line", "start": start, "end": start + step * count, "step": step,
             "marks": [mark], "mark_labels": ["A"]}
    elif kind == "ruler":
        words = (prompt or "").lower()
        ordered = sorted(diagram.objects[:2], key=lambda o: o.end - o.start, reverse=True)
        the = lambda label: label if label[:1].isupper() else f"the {label}"
        icons = {o.label: o.icon for o in diagram.objects}
        if len(ordered) == 2:
            long_label, short_label = ordered[0].label, ordered[1].label
            together = re.search(r"\b(total|together|altogether|in all|combined)\b", words)
            room = diagram.length if not together else diagram.length - 1
            big = rng.randint(3, max(3, (room if not together else room - 2)))
            small = rng.randint(1, big - 1) if not together else rng.randint(1, max(1, room - big))
            if together:
                small = min(small, diagram.length - big)
                objects = [{"label": long_label, "start": 0, "end": big, "icon": icons[long_label]},
                           {"label": short_label, "start": big, "end": big + small, "icon": icons[short_label]}]
                text = f"What is the total length of {the(long_label)} and {the(short_label)}?"
            else:
                objects = [{"label": long_label, "start": 0, "end": big, "icon": icons[long_label]},
                           {"label": short_label, "start": 0, "end": small, "icon": icons[short_label]}]
                text = f"How much shorter is {the(short_label)} than {the(long_label)}?"
        else:
            only = diagram.objects[0]
            start_at = rng.randint(0, 3) if only.start else 0  # a measure that does not start at 0 stays that way
            size = rng.randint(2, max(2, diagram.length - start_at))
            objects = [{"label": only.label, "start": start_at, "end": start_at + size, "icon": only.icon}]
            text = f"How long is {the(only.label)}?"
        d = {"kind": "ruler", "unit": diagram.unit, "length": diagram.length, "objects": objects}
    elif kind == "money":
        kinds = sorted({p.coin for p in diagram.pieces}, key=lambda c: COIN_CENTS[c])
        d = {"kind": "money", "pieces": [{"coin": c, "count": rng.randint(1, 4)} for c in kinds]}
        text = "How much money is shown?"
    elif kind == "thermometer":
        steps = (diagram.high - diagram.low) // diagram.step
        reading = diagram.low + diagram.step * rng.randint(1, max(1, steps - 1))
        d = {"kind": "thermometer", "unit": diagram.unit, "low": diagram.low, "high": diagram.high,
             "step": diagram.step, "reading": reading}
        text = "What temperature does the thermometer show?"
    elif kind == "pictures":
        if len(diagram.groups) != 1:
            return None
        icon = rng.choice(["apple", "star", "fish", "flower", "ball", "bird", "leaf", "coin"])
        text = f"How many pictures are there?"
        d = {"kind": "pictures", "groups": [{"icon": icon, "count": rng.randint(2, 12)}]}
    elif kind == "coordinate_plane":
        lo = -diagram.size if diagram.four_quadrants else 0
        x, y = rng.randint(lo, diagram.size), rng.randint(lo, diagram.size)
        if x == y:
            y = lo if y != lo else diagram.size
        d = {"kind": "coordinate_plane", "size": diagram.size, "four_quadrants": diagram.four_quadrants,
             "points": [{"label": "A", "x": x, "y": y}]}
    if d is None:
        return None
    fresh = _ADAPTER.validate_python(d)
    right = answer(fresh, text)
    return (fresh, text, right) if right is not None else None


FAMILY = {
    "fraction_bar": "fraction_model", "fraction_circle": "fraction_model", "array": "array",
    "base_ten": "base_ten", "clock": "clock", "rectangle": "area_perimeter",
    "right_triangle": "area_perimeter", "number_line": "number_line",
    "coordinate_plane": "coordinates", "bar_graph": "graph", "pictures": "counting",
    "ruler": "measuring", "money": "money", "thermometer": "temperature",
}


def category(diagram) -> str:
    """The maths-pack category for a miss on this kind of picture."""
    return f"math.diagram.{FAMILY.get(diagram.kind, 'graph')}"


__all__ = ["FAMILY", "category", "answer", "explain", "explain_point", "key", "new_like", "parse", "same"]
