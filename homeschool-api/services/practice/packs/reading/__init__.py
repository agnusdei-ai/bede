"""Reading and language arts pack: comprehension questions on a passage.

Two kinds of reading question need two different treatments, and telling
them apart is this pack's whole job:

- A question whose answer is in the passage (a detail, a word's meaning, a
  multiple-choice item with a marked answer) is checked against the
  teacher's correction, like the short-answer pack, and practised by going
  back to the passage to find the answer.
- A question that asks for judgement (why, the main idea, the theme, the
  author's purpose, an inference, a written response) has no single right
  answer Bede can compare against. Bede never marks it. It goes to the
  parent with the child's answer and the teacher's comment.

Like the short-answer pack, this pack never supplies an answer the page did
not give. A multiple-choice item is always checked against the teacher's
marked answer, whatever kind of question it is, because the answer is then
on the page.
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
from services.practice.packs.recall import _CHOICE, _OPTIONS, _clip, _distance, _find, _ref

_ROOT = Path(__file__).resolve().parent
_TAXONOMY = json.loads((_ROOT / "taxonomy.json").read_text(encoding="utf-8"))

# Questions that ask for judgement rather than a detail from the passage.
_JUDGEMENT = re.compile(
    r"\b(why|explain|how do you know|infer|inference|main idea|central idea|theme|"
    r"author'?s purpose|purpose of|most likely|suggests?|conclude|conclusion|evidence|"
    r"in your own words|summari[sz]e|summary|describe|compare|contrast|opinion|"
    r"do you think|predict|lesson|moral|point of view|meant|mean by|mean when)\b",
    re.IGNORECASE,
)
_VOCABULARY = re.compile(r"\b(mean|means|meaning|definition|synonym|antonym|closest in meaning)\b", re.IGNORECASE)
# Beyond this many words an answer is a written response, never auto-marked.
_LONG_ANSWER_WORDS = 12


def _words(text: str) -> int:
    return len(text.split())


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
            choice = bool(_OPTIONS.search(item.prompt) and _CHOICE.match(given))
            if not choice and (
                _JUDGEMENT.search(item.prompt)
                or _words(given) > _LONG_ANSWER_WORDS
                or _words(wanted) > _LONG_ANSWER_WORDS
            ):
                out.append(ErrorInstance(
                    item_ref=ref, category="reading.needs_judgement", audience="parent_only",
                    evidence=_clip("a question that asks for judgement; Bede does not mark it. "
                                   "Read the child's answer with the teacher's comment"),
                ))
                continue
            if not wanted:
                out.append(ErrorInstance(
                    item_ref=ref, category="reading.needs_answer", audience="parent_only",
                    evidence="no correct answer is written on the page; add it to practise this question",
                ))
                continue
            g, w = normalize(given), normalize(wanted)
            if choice and _CHOICE.match(wanted):
                category, evidence = "reading.choice", f"chose {given}; the answer is {wanted}"
            # A spelling slip is at most one edit per five letters, so a
            # different real word ("angry" for "hungry") is never called the
            # right answer spelled differently.
            elif w and g and len(w) >= 5 and _distance(g, w) <= max(1, len(w) // 5):
                category, evidence = "reading.spelling", f"wrote {given} for {wanted}: the right answer, spelled differently"
            # Partial only when the child gave part of the answer, never when
            # their answer merely contains it ("not the barn" for "the barn").
            elif item.teacher_mark == "partial" or (g and w and g in w):
                category, evidence = "reading.partial", f"wrote {given}; the full answer is {wanted}"
            elif _VOCABULARY.search(item.prompt):
                category, evidence = "reading.vocabulary", f"gave {given} as the meaning; the answer is {wanted}"
            else:
                category, evidence = "reading.detail", f"wrote {given}; the passage says {wanted}"
            out.append(ErrorInstance(item_ref=ref, category=category, evidence=_clip(evidence)))
    return out


def find_strengths(assessment: GradedAssessment) -> list[Strength]:
    out = []
    for section in assessment.sections:
        items = [i for i in section.items if not i.needs_parent() and i.teacher_mark != "unmarked"]
        if len(items) >= 2 and all(i.teacher_mark == "correct" for i in items):
            out.append(Strength(category="reading.section", note=f"{section.label}: {_TAXONOMY['strengths']['reading.section']}"))
    return out


_HINTS = {
    "reading.choice": "Check each option against the passage.",
    "reading.vocabulary": "Reread the sentence the word is in.",
}
_PASSAGE_HINT = "Find the sentence in the passage that tells you."


def generate_practice(diagnosis: Diagnosis, assessment: GradedAssessment, constraints: dict | None = None) -> PracticeSet | None:
    constraints = constraints or {}
    max_items = constraints.get("max_items", 12)
    items: list[PracticeItem] = []
    targets: list[str] = []
    script: list[str] = []
    asked: set[str] = set()

    for error in diagnosis.errors:
        if error.audience != "parent_and_child" or not error.category.startswith("reading."):
            continue
        if error.item_ref in asked:
            continue
        section, item = _find(assessment, error.item_ref)
        asked.add(error.item_ref)
        if error.category not in targets:
            targets.append(error.category)
            guidance = _TAXONOMY["categories"][error.category].get("parent_script")
            if guidance:
                script.append(guidance)
        items.append(PracticeItem(
            kind="retrieval", target=error.category, prompt=item.prompt,
            expected_answer=item.teacher_correction.strip()[:200],
            hint=_HINTS.get(error.category, _PASSAGE_HINT), diagram=item.diagram,
        ))

    if not items:
        return None

    known = [(s, i) for s in assessment.sections for i in s.items
             if not i.needs_parent() and i.teacher_mark == "correct" and (i.student_response or "").strip()
             and not _JUDGEMENT.search(i.prompt) and _words(i.student_response) <= _LONG_ANSWER_WORDS]
    seed = hashlib.sha256("|".join(sorted(asked)).encode()).hexdigest()
    random.Random(int(seed[:16], 16)).shuffle(known)
    room = max(0, min(len(items), max_items - len(items)))
    for _, item in known[:room]:
        items.append(PracticeItem(
            kind="retrieval", target="reading.review",
            prompt=item.prompt, expected_answer=item.student_response.strip()[:200], diagram=item.diagram,
        ))

    items = items[:max_items]
    minutes = max(3, min(constraints.get("max_minutes", 10), round(len(items) * 0.8)))
    text = " ".join(dict.fromkeys(script)) + (
        " Keep the passage open. Ask each question and wait; if they are stuck, "
        "ask them to find where the passage talks about it, then give the answer."
    )
    return PracticeSet(
        targets=targets,
        mode="retrieval",
        est_minutes=minutes,
        items=items,
        parent_script=text.strip()[:1200],
        recheck_schedule=["+3d", "+7d"],
    )
