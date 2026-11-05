"""Mathematics subject pack: what an arithmetic miss means, and new problems
that practise the same thing.

Deterministic on purpose, like the Latin pack. The model reads the photo;
after that every step is arithmetic a parent could check by hand:

* **Diagnosis** works the problem out exactly (``fractions.Fraction``, never
  floating point) and then asks which known slip would produce the child's
  answer: adding without carrying, taking the smaller digit from the larger,
  forgetting to shift a partial product, adding across a fraction, a misplaced
  decimal point, a dropped sign, working left to right. A miss that no rule
  explains is handed to the parent rather than guessed at.
* **Practice** generates fresh problems of the same shape, so the pattern is
  practised and the missed problem itself is never simply asked again. Every
  expected answer is computed, not written.
* **The page wins.** When the teacher's correction disagrees with what this
  pack computes, the pack has probably misread the problem, so the item goes
  to the parent instead of being diagnosed.

Problems written as an expression can be diagnosed (``27 + 15 =``,
``3/4 - 1/8``, ``2 + 3 × 4``), and so can picture problems the reader
recorded as a ``diagram`` (a shaded fraction, a clock, an array, base-ten
blocks, a rectangle's area or perimeter, a number line, a coordinate point):
``services/practice/diagrams.py`` works the picture's answer out, names the
slip, and draws fresh pictures of the same kind for practice. Word problems
and anything with a variable are counted and named for the parent but not
diagnosed.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from fractions import Fraction
from pathlib import Path
from typing import Optional

from services.practice import diagrams
from models.practice import (
    Diagnosis,
    ErrorInstance,
    GradedAssessment,
    PracticeItem,
    PracticeSet,
    Strength,
)

_ROOT = Path(__file__).resolve().parent
_TAXONOMY = json.loads((_ROOT / "taxonomy.json").read_text(encoding="utf-8"))
_STRENGTH_TEXT = _TAXONOMY["strengths"]
_HINTS = {k: v.get("hint", "") for k, v in _TAXONOMY["categories"].items()}

_OPS = {"+": "+", "-": "-", "−": "-", "–": "-", "×": "*", "*": "*", "·": "*", "÷": "/", ":": "/"}
_SYMBOL = {"+": "+", "-": "−", "*": "×", "/": "÷"}


# ── Numbers ───────────────────────────────────────────────────────────────────

class _Num:
    """A literal as written: its exact value and how it was written."""

    __slots__ = ("value", "kind", "text")

    def __init__(self, value: Fraction, kind: str, text: str):
        self.value, self.kind, self.text = value, kind, text


_NUMBER = re.compile(r"\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+")


def _literal(text: str) -> Optional[_Num]:
    text = text.strip().replace(",", "")
    if re.fullmatch(r"\d+\s+\d+/\d+", text):
        whole, frac = text.split()
        num, den = frac.split("/")
        if int(den) == 0:
            return None
        return _Num(int(whole) + Fraction(int(num), int(den)), "fraction", text)
    if re.fullmatch(r"\d+/\d+", text):
        num, den = text.split("/")
        if int(den) == 0:
            return None
        return _Num(Fraction(int(num), int(den)), "fraction", text)
    if re.fullmatch(r"\d*\.\d+", text):
        return _Num(Fraction(text), "decimal", text)
    if re.fullmatch(r"\d+", text):
        return _Num(Fraction(int(text)), "whole", text)
    return None


def parse_answer(text: str | None) -> Optional[Fraction]:
    """A written answer as an exact value, or None if it is not a number."""
    if not text:
        return None
    t = text.strip().rstrip(".").replace("−", "-").replace("–", "-").replace(" ", " ")
    t = re.sub(r"^[a-zA-Z]\s*=\s*", "", t)  # "x = 4" -> "4"
    negative = t.startswith("-")
    if negative:
        t = t[1:].strip()
    num = _literal(t)
    if num is None:
        return None
    return -num.value if negative else num.value


# ── Expressions ───────────────────────────────────────────────────────────────

def _tokens(prompt: str) -> Optional[list]:
    """Tokens of an arithmetic expression, or None if the prompt is not one."""
    text = prompt.strip()
    text = re.sub(r"[=?]\s*(_+|\.\.\.|…)?\s*$", "", text).strip()
    text = re.sub(r"(?<=[\d)])\s*[xX]\s*(?=[\d(])", " × ", text)  # 3 x 4 means times
    text = text.replace(",", "")
    out: list = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()":
            out.append(ch)
            i += 1
            continue
        # A slash with spaces round it is division; "3/4" is a fraction.
        if ch == "/" and i > 0 and text[i - 1] == " ":
            out.append("/")
            i += 1
            continue
        if ch in _OPS:
            out.append(_OPS[ch])
            i += 1
            continue
        match = _NUMBER.match(text, i)
        if match:
            literal = match.group(0)
            # "2 3/4" is a mixed number only when nothing else could be meant.
            if " " in literal and out and out[-1] not in ("+", "-", "*", "/", "("):
                literal = literal.split()[0]
            num = _literal(literal)
            if num is None:
                return None
            out.append(num)
            i += len(literal)
            continue
        return None  # a letter, a variable, a word problem
    if not any(isinstance(t, str) and t in "+-*/" for t in out):
        return None
    return out


class _Parser:
    def __init__(self, tokens: list, precedence: bool = True):
        self.tokens, self.pos, self.precedence = tokens, 0, precedence

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def expr(self) -> Fraction:
        if not self.precedence:
            value = self.unary()
            while self.peek() in ("+", "-", "*", "/"):
                value = _apply(value, self.take(), self.unary())
            return value
        value = self.term()
        while self.peek() in ("+", "-"):
            value = _apply(value, self.take(), self.term())
        return value

    def term(self) -> Fraction:
        value = self.unary()
        while self.peek() in ("*", "/"):
            value = _apply(value, self.take(), self.unary())
        return value

    def unary(self) -> Fraction:
        if self.peek() == "-":
            self.take()
            return -self.unary()
        tok = self.take()
        if tok == "(":
            value = self.expr()
            if self.take() != ")":
                raise ValueError("unbalanced")
            return value
        if isinstance(tok, _Num):
            return tok.value
        raise ValueError("unexpected token")


def _apply(a: Fraction, op: str, b: Fraction) -> Fraction:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        raise ZeroDivisionError
    return a / b


def evaluate(prompt: str, precedence: bool = True) -> Optional[Fraction]:
    tokens = _tokens(prompt)
    if tokens is None:
        return None
    parser = _Parser(tokens, precedence)
    try:
        value = parser.expr()
    except (ValueError, ZeroDivisionError):
        return None
    if parser.pos != len(tokens):
        return None
    return value


class Problem:
    """A two-number problem, the shape most slips can be read from."""

    def __init__(self, a: _Num, op: str, b: _Num, negative_a: bool = False):
        self.a, self.op, self.b = a, op, b
        self.av = -a.value if negative_a else a.value
        self.bv = b.value

    @property
    def kinds(self) -> set:
        return {self.a.kind, self.b.kind}


def binary(prompt: str) -> Optional[Problem]:
    tokens = _tokens(prompt)
    if tokens is None:
        return None
    negative = False
    if tokens and tokens[0] == "-":
        negative, tokens = True, tokens[1:]
    if len(tokens) == 3 and isinstance(tokens[0], _Num) and isinstance(tokens[2], _Num) and tokens[1] in "+-*/":
        return Problem(tokens[0], tokens[1], tokens[2], negative)
    if (len(tokens) == 6 and isinstance(tokens[0], _Num) and tokens[1] in "+-*/" and tokens[2] == "("
            and tokens[3] == "-" and isinstance(tokens[4], _Num) and tokens[5] == ")"):
        # 4 - (-2): the second number is negative.
        problem = Problem(tokens[0], tokens[1], tokens[4], negative)
        problem.bv = -tokens[4].value
        return problem
    return None


def operator_count(prompt: str) -> int:
    tokens = _tokens(prompt) or []
    return sum(1 for i, t in enumerate(tokens) if t in ("+", "*", "/") or (t == "-" and i and tokens[i - 1] not in ("(", "+", "-", "*", "/")))


# ── Column slips ─────────────────────────────────────────────────────────────

def _digits(n: int, width: int) -> list[int]:
    return [int(c) for c in str(n).zfill(width)]


def no_carry_sum(a: int, b: int) -> int:
    width = max(len(str(a)), len(str(b)))
    return int("".join(str((x + y) % 10) for x, y in zip(_digits(a, width), _digits(b, width))))


def needs_carry(a: int, b: int) -> bool:
    return no_carry_sum(a, b) != a + b


def smaller_from_larger(a: int, b: int) -> int:
    width = max(len(str(a)), len(str(b)))
    return int("".join(str(abs(x - y)) for x, y in zip(_digits(a, width), _digits(b, width))))


def needs_borrow(a: int, b: int) -> bool:
    return a >= b and smaller_from_larger(a, b) != a - b


def unshifted_product(a: int, b: int) -> int:
    return sum(a * int(d) for d in str(b))


def _reducible(text: str | None) -> bool:
    """True when the written fraction itself could be put in lower terms."""
    from math import gcd

    match = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    return bool(match) and gcd(int(match.group(1)), int(match.group(2))) > 1


def _is_whole(value: Fraction) -> bool:
    return value.denominator == 1 and value >= 0


# ── Diagnosis ─────────────────────────────────────────────────────────────────

def _clip(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ref(section, item) -> str:
    return f"{section.label} #{item.number}"


def _family(prompt: str) -> Optional[str]:
    """What kind of problem this is, for strengths and retrieval."""
    if evaluate(prompt) is None:
        return None
    if operator_count(prompt) >= 2:
        return "order_of_operations"
    problem = binary(prompt)
    if problem is None:
        return None
    if "fraction" in problem.kinds:
        return "fractions"
    if "decimal" in problem.kinds:
        return "decimals"
    if problem.av < 0 or problem.bv < 0:
        return "integers"
    return {"+": "addition", "-": "subtraction", "*": "multiplication", "/": "division"}[problem.op]


def _explain(prompt: str, given: Fraction, right: Fraction) -> tuple[str, str]:
    """(category, evidence) for a wrong answer to a computable problem."""
    shown = prompt.strip().rstrip("=?_ ").strip()
    if operator_count(prompt) >= 2:
        if evaluate(prompt, precedence=False) == given:
            return "math.order_of_operations", f"{shown}: worked left to right and got {_fmt(given)}; multiplying or dividing first gives {_fmt(right)}"
    problem = binary(prompt)
    if problem is not None:
        a, b, op = problem.av, problem.bv, problem.op
        if right != 0 and given == -right:
            return "math.integer.sign", f"{shown}: the size is right ({_fmt(abs(right))}) but the sign is not"
        if (a < 0 or b < 0) and op in "+-":
            # A negative number handled as if it were positive, or the
            # subtraction of a negative read as subtraction of a positive.
            slips = {abs(a) + abs(b), abs(a) - abs(b), abs(b) - abs(a), -(abs(a) + abs(b)), a - abs(b), a + abs(b)}
            if given in slips:
                return "math.integer.sign", f"{shown}: wrote {_fmt(given)}; with the negative number kept negative it is {_fmt(right)}"
        for other in "+-*/":
            if other == op:
                continue
            try:
                if _apply(a, other, b) == given:
                    return "math.operation_swap", f"{shown}: {_fmt(given)} is what {_SYMBOL[other]} gives; the sign asked for {_SYMBOL[op]}"
            except ZeroDivisionError:
                continue
        if "fraction" in problem.kinds and op in "+-":
            fa, fb = Fraction(a), Fraction(b)
            n = fa.numerator + fb.numerator if op == "+" else fa.numerator - fb.numerator
            d = fa.denominator + fb.denominator if op == "+" else fa.denominator - fb.denominator
            if d and Fraction(n, d) == given:
                return "math.fraction.add_across", f"{shown}: added the tops and the bottoms separately to get {_fmt(given)}"
        if "fraction" in problem.kinds and op == "/" and b != 0:
            if Fraction(a) * Fraction(b) == given:
                return "math.fraction.divide_no_invert", f"{shown}: multiplied straight across instead of dividing"
        if "decimal" in problem.kinds and given != 0:
            ratio = given / right if right else None
            if ratio in (Fraction(10), Fraction(100), Fraction(1000), Fraction(1, 10), Fraction(1, 100), Fraction(1, 1000)):
                return "math.decimal.place_value", f"{shown}: the digits are right but the decimal point is in the wrong place ({_fmt(given, True)} for {_fmt(right, True)})"
        if _is_whole(a) and _is_whole(b) and _is_whole(given):
            ia, ib, ig = int(a), int(b), int(given)
            if op == "+" and needs_carry(ia, ib) and no_carry_sum(ia, ib) == ig:
                return "math.add.no_regroup", f"{shown}: added each column but did not carry the ten"
            if op == "-" and needs_borrow(ia, ib) and smaller_from_larger(ia, ib) == ig:
                return "math.sub.smaller_from_larger", f"{shown}: took the smaller digit from the larger in each column instead of regrouping"
            if op == "*" and ib >= 10 and unshifted_product(ia, ib) == ig:
                return "math.mult.place_value_shift", f"{shown}: the second row was not moved one place left"
            if ia <= 12 and ib <= 12 and op in "+-*/" and right.denominator == 1:
                return "math.fact_recall", f"{shown}: wrote {ig}; the fact is {_fmt(right)}"
    return "", ""


def classify_errors(assessment: GradedAssessment, history: list | None = None) -> list[ErrorInstance]:
    out: list[ErrorInstance] = []
    for section in assessment.sections:
        for item in section.items:
            if item.needs_parent() or item.teacher_mark not in ("incorrect", "partial"):
                continue
            if not (item.student_response or "").strip():
                continue  # core.unanswered owns blanks
            ref = _ref(section, item)
            if item.diagram is not None:
                out.append(_classify_picture(ref, item))
                continue
            right = evaluate(item.prompt)
            given = parse_answer(item.student_response)
            correction = parse_answer(item.teacher_correction)

            if right is None or given is None:
                out.append(ErrorInstance(
                    item_ref=ref, category="math.unclassified", audience="parent_only",
                    evidence="this is not written as a sum Bede can work out (a word problem or a variable); please say what went wrong",
                ))
                continue
            if correction is not None and correction != right:
                out.append(ErrorInstance(
                    item_ref=ref, category="math.unclassified", audience="parent_only",
                    evidence=f"the teacher's answer ({item.teacher_correction}) differs from {_fmt(right)}; please check the problem was read correctly",
                ))
                continue
            if given == right:
                if _reducible(item.student_response):
                    lowest = f"{right.numerator}/{right.denominator}"
                    out.append(ErrorInstance(
                        item_ref=ref, category="math.fraction.not_simplified",
                        evidence=f"{item.student_response} is the right amount; the teacher wanted it in lowest terms, {lowest}",
                    ))
                else:
                    out.append(ErrorInstance(
                        item_ref=ref, category="math.unclassified", audience="parent_only",
                        evidence=f"{item.student_response} equals the answer; the teacher's mark may be about the working or the form",
                    ))
                continue
            category, evidence = _explain(item.prompt, given, right)
            if category:
                out.append(ErrorInstance(item_ref=ref, category=category, evidence=_clip(evidence)))
            else:
                out.append(ErrorInstance(
                    item_ref=ref, category="math.unclassified", audience="parent_only",
                    evidence=f"wrote {item.student_response} for {_fmt(right)}; no common slip explains it, so ask how they worked it",
                ))
    return out


def _classify_picture(ref: str, item) -> ErrorInstance:
    """A miss on a picture problem: checked against the picture itself."""
    right = diagrams.answer(item.diagram, item.prompt)
    if right is None:
        return ErrorInstance(
            item_ref=ref, category="math.unclassified", audience="parent_only",
            evidence="Bede cannot work out what this picture question asks; please say what went wrong",
        )
    if item.teacher_correction and not diagrams.same(item.diagram, item.teacher_correction, right):
        return ErrorInstance(
            item_ref=ref, category="math.unclassified", audience="parent_only",
            evidence=f"the teacher's answer ({item.teacher_correction}) differs from what the picture shows ({right}); please check the picture was read correctly",
        )
    if diagrams.same(item.diagram, item.student_response, right):
        return ErrorInstance(
            item_ref=ref, category="math.unclassified", audience="parent_only",
            evidence=f"{item.student_response} matches the picture; the teacher's mark may be about the working or the form",
        )
    evidence = diagrams.explain(item.diagram, item.prompt, item.student_response)
    if not evidence:
        return ErrorInstance(
            item_ref=ref, category="math.unclassified", audience="parent_only",
            evidence=f"wrote {item.student_response} for {right}; no common slip explains it, so ask how they read the picture",
        )
    return ErrorInstance(item_ref=ref, category=diagrams.category(item.diagram), evidence=_clip(evidence))


def find_strengths(assessment: GradedAssessment) -> list[Strength]:
    families: dict[str, list] = {}
    for section in assessment.sections:
        for item in section.items:
            if item.needs_parent() or item.teacher_mark == "unmarked":
                continue
            family = diagrams.FAMILY.get(item.diagram.kind) if item.diagram is not None else _family(item.prompt)
            if family:
                families.setdefault(family, []).append(item)
    out = []
    for family, items in families.items():
        if len(items) >= 2 and all(i.teacher_mark == "correct" for i in items):
            out.append(Strength(category=f"math.{family}", note=f"{_STRENGTH_TEXT[f'math.{family}']} ({len(items)} of {len(items)})"))
    return out


# ── Practice ──────────────────────────────────────────────────────────────────

def _fmt(value: Fraction, decimal: bool = False) -> str:
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    if decimal:
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
        if Fraction(text) == value:
            return text
    text = f"{value.numerator}/{value.denominator}"
    if abs(value) > 1:
        whole, rest = divmod(abs(value.numerator), value.denominator)
        sign = "-" if value < 0 else ""
        text += f" (= {sign}{whole} {rest}/{value.denominator})"
    return text


def _rng(*parts: str) -> random.Random:
    seed = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def _sized(rng: random.Random, digits: int) -> int:
    digits = max(1, min(digits, 4))
    return rng.randint(10 ** (digits - 1) if digits > 1 else 1, 10 ** digits - 1)


def _width(value: Fraction) -> int:
    return len(str(abs(int(value))))


def _gen(category: str, problem: Optional[Problem], rng: random.Random) -> Optional[tuple[str, Fraction, bool]]:
    """One fresh (prompt, answer, as_decimal) with the same shape as the miss."""
    wa = _width(problem.av) if problem else 2
    wb = _width(problem.bv) if problem else 2
    for _ in range(200):
        if category == "math.add.no_regroup":
            a, b = _sized(rng, max(wa, 2)), _sized(rng, max(wb, 2))
            if needs_carry(a, b):
                return f"{a} + {b} =", Fraction(a + b), False
        elif category == "math.sub.smaller_from_larger":
            a, b = _sized(rng, max(wa, 2)), _sized(rng, max(wb, 2))
            a, b = max(a, b), min(a, b)
            if needs_borrow(a, b):
                return f"{a} − {b} =", Fraction(a - b), False
        elif category == "math.mult.place_value_shift":
            a, b = _sized(rng, max(wa, 2)), _sized(rng, 2)
            return f"{a} × {b} =", Fraction(a * b), False
        elif category == "math.fact_recall":
            op = problem.op if problem else "*"
            x, y = rng.randint(2, 12), rng.randint(2, 12)
            if op == "+":
                return f"{x} + {y} =", Fraction(x + y), False
            if op == "-":
                return f"{x + y} − {y} =", Fraction(x), False
            if op == "/":
                return f"{x * y} ÷ {y} =", Fraction(x), False
            return f"{x} × {y} =", Fraction(x * y), False
        elif category == "math.operation_swap":
            op = problem.op if problem else "-"
            a, b = _sized(rng, max(wa, 1)), _sized(rng, max(min(wb, wa), 1))
            if op == "-":
                a, b = max(a, b), min(a, b)
                return f"{a} − {b} =", Fraction(a - b), False
            if op == "/":
                return f"{a * b} ÷ {b} =", Fraction(a), False
            if op == "*":
                a, b = rng.randint(2, 12), rng.randint(2, 12)
                return f"{a} × {b} =", Fraction(a * b), False
            return f"{a} + {b} =", Fraction(a + b), False
        elif category in ("math.fraction.add_across", "math.fraction.not_simplified"):
            d1, d2 = rng.choice([2, 3, 4, 5, 6, 8]), rng.choice([2, 3, 4, 6, 8, 10])
            n1, n2 = rng.randint(1, d1 - 1), rng.randint(1, d2 - 1)
            op = "-" if problem and problem.op == "-" else "+"
            if category == "math.fraction.not_simplified":
                k = rng.randint(2, 4)
                value = Fraction(n1, d1)
                if value.denominator == 1:
                    continue
                return f"Write {value.numerator * k}/{value.denominator * k} in lowest terms.", value, False
            value = Fraction(n1, d1) + Fraction(n2, d2) if op == "+" else Fraction(n1, d1) - Fraction(n2, d2)
            if value > 0 and d1 != d2:
                return f"{n1}/{d1} {_SYMBOL[op]} {n2}/{d2} =", value, False
        elif category == "math.fraction.divide_no_invert":
            d1, d2 = rng.choice([2, 3, 4, 5, 6]), rng.choice([2, 3, 4, 5, 8])
            n1, n2 = rng.randint(1, d1), rng.randint(1, d2 - 1)
            return f"{n1}/{d1} ÷ {n2}/{d2} =", Fraction(n1, d1) / Fraction(n2, d2), False
        elif category == "math.decimal.place_value":
            op = problem.op if problem else "*"
            a = Fraction(rng.randint(11, 99), 10)
            b = Fraction(rng.randint(2, 9), 10)
            if op == "+":
                b = Fraction(rng.randint(101, 999), 100)
                return f"{_fmt(a, True)} + {_fmt(b, True)} =", a + b, True
            if op == "-":
                b = Fraction(rng.randint(11, 99), 100)
                return f"{_fmt(a, True)} − {_fmt(b, True)} =", a - b, True
            if op == "/":
                return f"{_fmt(a * b, True)} ÷ {_fmt(b, True)} =", a, True
            return f"{_fmt(a, True)} × {_fmt(b, True)} =", a * b, True
        elif category == "math.integer.sign":
            a, b = rng.randint(-15, 15), rng.randint(-15, 15)
            if a == 0 or b == 0 or (a > 0 and b > 0):
                continue
            op = problem.op if problem and problem.op in "+-*" else rng.choice("+-")
            shown_b = f"({b})" if b < 0 else str(b)
            value = _apply(Fraction(a), op, Fraction(b))
            return f"{a} {_SYMBOL[op]} {shown_b} =".replace("-", "−"), value, False
        elif category == "math.order_of_operations":
            a, b, c = rng.randint(2, 20), rng.randint(2, 9), rng.randint(2, 9)
            if rng.random() < 0.5:
                return f"{a} + {b} × {c} =", Fraction(a + b * c), False
            return f"{a + b * c} − {b * c} ÷ {c} =", Fraction(a + b * c - b), False
        else:
            return None
    return None


def _find(assessment: GradedAssessment, ref: str):
    for section in assessment.sections:
        for item in section.items:
            if _ref(section, item) == ref:
                return item
    raise KeyError(ref)


def _normal(prompt: str) -> str:
    return re.sub(r"\s+", "", prompt.replace("−", "-").replace("×", "*").replace("÷", "/").rstrip("=? "))


def generate_practice(diagnosis: Diagnosis, assessment: GradedAssessment, constraints: dict | None = None) -> PracticeSet | None:
    constraints = constraints or {}
    seen = {_normal(i.prompt) for s in assessment.sections for i in s.items}
    items: list[PracticeItem] = []
    targets: list[str] = []
    script: list[str] = []

    def add_pictures(category: str, source, prompt: str, kind: str, count: int, salt: str) -> None:
        rng = _rng(category, salt)
        made = 0
        for _ in range(count * 20):
            if made >= count:
                break
            fresh = diagrams.new_like(source, prompt, rng)
            if fresh is None:
                return
            picture, text, right = fresh
            mark = text + diagrams.key(picture)
            if mark in seen or diagrams.key(picture) == diagrams.key(source):
                continue
            seen.add(mark)
            items.append(PracticeItem(
                kind=kind, target=category, prompt=text, expected_answer=right,
                hint=_HINTS.get(category, ""), diagram=picture,
            ))
            made += 1

    def add(category: str, problem: Optional[Problem], kind: str, count: int, salt: str) -> None:
        rng = _rng(category, salt)
        made = 0
        for _ in range(count * 20):
            if made >= count:
                break
            generated = _gen(category, problem, rng)
            if generated is None:
                return
            prompt, answer, as_decimal = generated
            if _normal(prompt) in seen:
                continue
            seen.add(_normal(prompt))
            items.append(PracticeItem(
                kind=kind, target=category, prompt=prompt,
                expected_answer=_fmt(answer, as_decimal), hint=_HINTS.get(category, ""),
            ))
            made += 1

    first_miss: dict[str, ErrorInstance] = {}
    for error in diagnosis.errors:
        if error.audience == "parent_and_child" and error.category.startswith("math.") \
                and error.category != "math.unclassified":
            first_miss.setdefault(error.category, error)
    max_items = constraints.get("max_items", 12)
    # Every pattern found gets practice: share the set out rather than letting
    # the first patterns on the page use it all up.
    per_pattern = max(1, min(3, max_items // max(1, len(first_miss))))
    for category, error in first_miss.items():
        item = _find(assessment, error.item_ref)
        targets.append(category)
        if item.diagram is not None:
            add_pictures(category, item.diagram, item.prompt, "drill", per_pattern, error.item_ref + item.prompt)
        else:
            add(category, binary(item.prompt), "drill", per_pattern, error.item_ref + item.prompt)
        guidance = _TAXONOMY["categories"][category].get("parent_script")
        if guidance:
            script.append(guidance)

    if not items:
        return None

    # Room left over: a second problem for each pattern, in page order.
    if per_pattern == 1:
        for category, error in first_miss.items():
            if len(items) >= max_items:
                break
            item = _find(assessment, error.item_ref)
            if item.diagram is not None:
                add_pictures(category, item.diagram, item.prompt, "drill", 1, "second" + error.item_ref + item.prompt)
            else:
                add(category, binary(item.prompt), "drill", 1, "second" + error.item_ref + item.prompt)

    # Mixed review of what went well, so the set ends on familiar ground.
    review = {"addition": "math.add.no_regroup", "subtraction": "math.sub.smaller_from_larger",
              "multiplication": "math.fact_recall", "fractions": "math.fraction.add_across",
              "decimals": "math.decimal.place_value", "integers": "math.integer.sign",
              "order_of_operations": "math.order_of_operations"}
    for strength in diagnosis.strengths[:2]:
        family = strength.category.removeprefix("math.")
        if family in review and len(items) < max_items:
            add(review[family], None, "retrieval", 1, "review" + family)

    items = items[:max_items]
    minutes = max(3, min(constraints.get("max_minutes", 10), round(len(items) * 0.8)))
    text = " ".join(dict.fromkeys(script)) + " Let them talk through each step; a miss gets a hint, not the answer. No timer."
    return PracticeSet(
        targets=targets,
        mode="drill",
        est_minutes=minutes,
        items=items,
        parent_script=text.strip()[:1200],
        recheck_schedule=["+3d", "+7d"],
    )
