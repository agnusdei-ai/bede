"""Checks that apply to every subject (docs/PRACTICE_COACH.md, Diagnose).

All three report to the PARENT only. They describe the work on the page, never
the child: "four of six answers were single words", not "skips instructions".

Two rules here are the ones a careless implementation gets wrong:

* **An item the teacher marked correct is never "unanswered"**, however empty
  it looks. A colour circle left white for *alba* is the answer, and the
  teacher's tick says so.
* **Anything the reader was unsure of is left out** until the parent confirms
  it (`AssessmentItem.needs_parent`), so a misread is never diagnosed.
"""
from __future__ import annotations

import re
import unicodedata

from models.practice import ErrorInstance, GradedAssessment

TAXONOMY = {
    "core.instruction.format": {
        "description": "Answers did not take the form the instructions asked for.",
        "remediation_strategy": "Re-answer a few items in the asked-for form, reading the instruction aloud first.",
    },
    "core.unanswered": {
        "description": "An item was left blank and not marked correct.",
        "remediation_strategy": "Ask the parent whether it was skipped, unfinished, or not reached.",
    },
    "core.unmarked_review": {
        "description": "An unmarked answer that does not match the word bank; worth a parent's look.",
        "remediation_strategy": "Parent checks the item; nothing is said to the child.",
    },
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def normalize(text: str | None) -> str:
    """Lower-cased, macrons and punctuation removed, for comparison only."""
    if not text:
        return ""
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    return " ".join(_WORD.findall(stripped.lower()))


def word_count(text: str | None) -> int:
    return len(_WORD.findall(text or ""))


def _blank(response: str | None) -> bool:
    return not (response or "").strip()


def instruction_format(assessment: GradedAssessment) -> list[ErrorInstance]:
    out = []
    for section in assessment.sections:
        if section.required_format != "complete_sentence":
            continue
        answered = [i for i in section.items if not i.needs_parent() and not _blank(i.student_response)]
        short = [i for i in answered if word_count(i.student_response) < 2]
        if not short:
            continue
        # A format deduction shows up as partial credit; none means the
        # teacher let the format go.
        undeducted = not any(i.teacher_mark == "partial" for i in short)
        evidence = (
            f"The instructions asked for complete sentences; {len(short)} of {len(answered)} answers "
            f"were single words"
        )
        if undeducted:
            evidence += " (the teacher did not take marks off for the format)"
        out.append(ErrorInstance(
            item_ref=section.label,
            category="core.instruction.format",
            evidence=evidence + ".",
            severity="low",
            audience="parent_only",
        ))
    return out


def unanswered(assessment: GradedAssessment) -> list[ErrorInstance]:
    out = []
    for section in assessment.sections:
        for item in section.items:
            if item.needs_parent() or item.teacher_mark == "correct":
                continue
            if not _blank(item.student_response):
                continue
            out.append(ErrorInstance(
                item_ref=f"{section.label} #{item.number}",
                category="core.unanswered",
                evidence="Nothing was written for this item and it was not marked correct.",
                severity="low",
                audience="parent_only",
            ))
    return out


def unmarked_review(assessment: GradedAssessment) -> list[ErrorInstance]:
    out = []
    for section in assessment.sections:
        bank = {normalize(w) for w in section.word_bank}
        if not bank:
            continue
        for item in section.items:
            if item.needs_parent() or item.teacher_mark != "unmarked" or _blank(item.student_response):
                continue
            words = set(normalize(item.student_response).split())
            if words and not words & bank:
                out.append(ErrorInstance(
                    item_ref=f"{section.label} #{item.number}",
                    category="core.unmarked_review",
                    evidence=f"'{item.student_response}' is not in this section's word bank and has no teacher mark.",
                    severity="low",
                    audience="parent_only",
                ))
    return out


def run(assessment: GradedAssessment) -> list[ErrorInstance]:
    return instruction_format(assessment) + unanswered(assessment) + unmarked_review(assessment)
