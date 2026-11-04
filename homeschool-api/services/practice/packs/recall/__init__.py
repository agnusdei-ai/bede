"""Short-answer recall pack: history, science, geography, reading and
grammar quizzes, and any other test of things to remember.

The pack never supplies a fact. Every practice answer is one the page itself
gives: the teacher's correction for a miss, or the child's own right answer
for review. Bede has no verified source for a school's content, so inventing
a question or an answer here would be making things up in a child's
practice. A miss with no correction on the page goes to the parent instead.

That is also why the practice works differently from Latin and maths: for
remembered material, answering the same question again later is the
practice (retrieval practice), so a missed question is asked again, mixed in
with a few the child already knew. Diagnosis names only what the page shows:
a partial answer, a different option chosen, a nearly-right spelling of the
right answer, or a different answer.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

from models.practice import (
    Diagnosis,
    ErrorInstance,
    GradedAssessment,
    PracticeItem,
    PracticeSet,
    Strength,
)
from services.practice.core_checks import normalize

_ROOT = Path(__file__).resolve().parent
_TAXONOMY = json.loads((_ROOT / "taxonomy.json").read_text(encoding="utf-8"))
# An option letter on its own ("B", "b)", "(c)"), never an answer that merely
# starts with the article "a".
_CHOICE = re.compile(r"^\(?([a-eA-E])[).:]?$")
_OPTIONS = re.compile(r"(?:^|\s)\(?[A-Ea-e][).:]\s")


def _clip(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ref(section, item) -> str:
    return f"{section.label} #{item.number}"


def _distance(a: str, b: str) -> int:
    """Levenshtein distance, for a nearly-right spelling of the right answer."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def classify_errors(assessment: GradedAssessment, history: list | None = None) -> list[ErrorInstance]:
    out: list[ErrorInstance] = []
    for section in assessment.sections:
        for item in section.items:
            if item.needs_parent() or item.teacher_mark not in ("incorrect", "partial"):
                continue
            given = (item.student_response or "").strip()
            if not given:
                continue  # core.unanswered owns blanks
            ref = _ref(section, item)
            wanted = (item.teacher_correction or "").strip()
            if not wanted:
                out.append(ErrorInstance(
                    item_ref=ref, category="recall.needs_answer", audience="parent_only",
                    evidence="no correct answer is written on the page; add it to practise this question",
                ))
                continue
            g, w = normalize(given), normalize(wanted)
            if _OPTIONS.search(item.prompt) and _CHOICE.match(given) and _CHOICE.match(wanted):
                category, evidence = "recall.choice", f"chose {given}; the answer is {wanted}"
            elif w and g and len(w) >= 5 and _distance(g, w) <= max(1, len(w) // 5):
                category, evidence = "recall.spelling", f"wrote {given} for {wanted}: the right answer, spelled differently"
            elif item.teacher_mark == "partial" or (g and w and g in w):
                category, evidence = "recall.partial", f"wrote {given}; the full answer is {wanted}"
            else:
                category, evidence = "recall.fact", f"wrote {given}; the answer is {wanted}"
            out.append(ErrorInstance(item_ref=ref, category=category, evidence=_clip(evidence)))
    return out


def find_strengths(assessment: GradedAssessment) -> list[Strength]:
    out = []
    for section in assessment.sections:
        items = [i for i in section.items if not i.needs_parent() and i.teacher_mark != "unmarked"]
        if len(items) >= 2 and all(i.teacher_mark == "correct" for i in items):
            out.append(Strength(category="recall.section", note=f"{section.label}: {_TAXONOMY['strengths']['recall.section']}"))
    return out


def _find(assessment: GradedAssessment, ref: str):
    for section in assessment.sections:
        for item in section.items:
            if _ref(section, item) == ref:
                return section, item
    raise KeyError(ref)


def _hint(answer: str) -> str:
    first = answer.strip().lstrip("(").strip()
    if _CHOICE.match(answer):
        return "Read every option before you choose."
    if len(first.split()) > 3:
        return ""  # a first letter says nothing useful about a sentence-long answer
    return f"It starts with “{first[0].upper()}”." if first else ""


def generate_practice(diagnosis: Diagnosis, assessment: GradedAssessment, constraints: dict | None = None) -> PracticeSet | None:
    constraints = constraints or {}
    max_items = constraints.get("max_items", 12)
    items: list[PracticeItem] = []
    targets: list[str] = []
    script: list[str] = []
    asked: set[str] = set()

    for error in diagnosis.errors:
        if error.audience != "parent_and_child" or not error.category.startswith("recall."):
            continue
        section, item = _find(assessment, error.item_ref)
        if error.item_ref in asked:
            continue
        asked.add(error.item_ref)
        if error.category not in targets:
            targets.append(error.category)
            guidance = _TAXONOMY["categories"][error.category].get("parent_script")
            if guidance:
                script.append(guidance)
        items.append(PracticeItem(
            kind="retrieval", target=error.category,
            prompt=item.prompt, expected_answer=item.teacher_correction.strip()[:200], hint=_hint(item.teacher_correction),
        ))

    if not items:
        return None

    # Mix in a few the child already knew: interleaving, and an easy start.
    known = [(s, i) for s in assessment.sections for i in s.items
             if not i.needs_parent() and i.teacher_mark == "correct" and (i.student_response or "").strip()]
    seed = hashlib.sha256("|".join(sorted(asked)).encode()).hexdigest()
    random.Random(int(seed[:16], 16)).shuffle(known)
    room = max(0, min(len(items), max_items - len(items)))
    for _, item in known[:room]:
        items.append(PracticeItem(
            kind="retrieval", target="recall.review",
            prompt=item.prompt, expected_answer=item.student_response.strip()[:200],
        ))

    items = items[:max_items]
    minutes = max(3, min(constraints.get("max_minutes", 10), round(len(items) * 0.7)))
    text = " ".join(dict.fromkeys(script)) + (
        " Ask each question and wait; if they are stuck, give the hint, then the answer, "
        "and come back to that question at the end."
    )
    return PracticeSet(
        targets=targets,
        mode="retrieval",
        est_minutes=minutes,
        items=items,
        parent_script=text.strip()[:1200],
        recheck_schedule=["+3d", "+7d"],
    )
