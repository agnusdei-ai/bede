"""Latin subject pack: what a Latin miss means, and what practice fixes it.

Deterministic on purpose. The model reads the photo; everything after that is
a rule a parent could check by hand, so the same quiz always gets the same
diagnosis and the same practice, and a test can pin both.

Two constraints govern `generate_practice`:

* **Only words the child has already met.** Every Latin word in a practice
  answer comes from the quiz's own word banks; the lexicon supplies meanings
  and which animal can do which action, never new vocabulary.
* **New items, never the missed one again.** The pattern is practised with
  scenes the quiz did not use, and the re-check uses fresh combinations again.
"""
from __future__ import annotations

import json
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
LEXICON = json.loads((_ROOT / "item_bank" / "lexicon.json").read_text(encoding="utf-8"))
_NOUNS = {normalize(k): (k, v) for k, v in LEXICON["nouns"].items()}
_VERBS = {normalize(k): (k, v) for k, v in LEXICON["verbs"].items()}
_MACRONS = set("āēīōūȳĀĒĪŌŪȲ")
_STRENGTH_TEXT = json.loads((_ROOT / "taxonomy.json").read_text(encoding="utf-8"))["strengths"]


def _key(text: str | None) -> str:
    """The content word of an answer: 'Anas est.' -> 'anas'."""
    words = [w for w in normalize(text).split() if w != "est"]
    return words[0] if words else ""


def _ref(section, item) -> str:
    return f"{section.label} #{item.number}"


def _asks_what(prompt: str) -> bool:
    return "quid est" in normalize(prompt)


def _asks_doing(prompt: str) -> bool:
    return "quid agit" in normalize(prompt)


def classify_errors(assessment: GradedAssessment, history: list | None = None) -> list[ErrorInstance]:
    out: list[ErrorInstance] = []
    bank = {normalize(w) for w in assessment.word_bank()}
    for section in assessment.sections:
        for item in section.items:
            if item.needs_parent() or item.teacher_mark not in ("incorrect", "partial"):
                continue
            if not (item.student_response or "").strip():
                continue  # core.unanswered owns blanks
            given, wanted = _key(item.student_response), _key(item.teacher_correction)
            ref = _ref(section, item)

            if item.teacher_correction and normalize(item.student_response) == normalize(item.teacher_correction) \
                    and item.student_response.strip() != item.teacher_correction.strip():
                out.append(ErrorInstance(
                    item_ref=ref, category="latin.macron_omission",
                    evidence=f"wrote {item.student_response} for {item.teacher_correction}: same word, macron missing",
                ))
            elif wanted in _NOUNS and normalize(_NOUNS[wanted][1]["broader"]) == given:
                specific, general = _NOUNS[wanted], _NOUNS[given]
                evidence = (
                    f"wrote {general[0]} ({general[1]['gloss']}) for {specific[0]} "
                    f"({specific[1]['gloss']}): the general word for the specific one"
                )
                if given in bank and wanted in bank:
                    evidence += "; both were in the word bank"
                out.append(ErrorInstance(
                    item_ref=ref, category="latin.vocab.hypernym_substitution", evidence=evidence,
                ))
            elif (_asks_what(item.prompt) and given in _VERBS) or (_asks_doing(item.prompt) and given in _NOUNS):
                out.append(ErrorInstance(
                    item_ref=ref, category="latin.question.what_vs_doing",
                    evidence=f"answered '{item.prompt}' with {item.student_response}",
                ))
            elif wanted and given in bank and wanted in bank and (
                (given in _NOUNS and wanted in _NOUNS) or (given in _VERBS and wanted in _VERBS)
            ):
                out.append(ErrorInstance(
                    item_ref=ref, category="latin.vocab.confusable_pair",
                    evidence=f"wrote {item.student_response} for {item.teacher_correction}; both in the word bank",
                ))
            elif bank and given not in bank and given not in _NOUNS and given not in _VERBS:
                out.append(ErrorInstance(
                    item_ref=ref, category="latin.vocab.unknown_word",
                    evidence=f"wrote {item.student_response}, which is not in the word bank",
                ))
            else:
                out.append(ErrorInstance(
                    item_ref=ref, category="latin.unclassified",
                    evidence="this pack cannot tell what went wrong here; please describe it",
                    audience="parent_only",
                ))
    return out


def find_strengths(assessment: GradedAssessment) -> list[Strength]:
    strengths = _STRENGTH_TEXT
    out: list[Strength] = []
    solid = [(s, i) for s in assessment.sections for i in s.items if not i.needs_parent()]

    doing = [i for _, i in solid if _asks_doing(i.prompt)]
    if doing and all(i.teacher_mark == "correct" for i in doing):
        words = ", ".join(i.student_response for i in doing if i.student_response)
        out.append(Strength(category="latin.verbs.action_words", note=f"{strengths['latin.verbs.action_words']}: {words}"))

    what = [i for _, i in solid if _asks_what(i.prompt)]
    if what and all(i.teacher_mark == "correct" for i in what):
        out.append(Strength(category="latin.nouns.naming", note=strengths["latin.nouns.naming"]))

    macroned = [i.student_response for _, i in solid
                if i.teacher_mark == "correct" and _MACRONS & set(i.student_response or "")]
    if macroned:
        out.append(Strength(category="latin.macrons", note=f"{strengths['latin.macrons']}: {', '.join(macroned)}"))

    for section in assessment.sections:
        items = [i for i in section.items if not i.needs_parent()]
        if not items or not all(i.teacher_mark == "correct" for i in items):
            continue
        if section.required_format == "color_fill":
            out.append(Strength(category="latin.colors", note=strengths["latin.colors"]))
        elif section.required_format == "single_word" and section.word_bank:
            out.append(Strength(category="latin.word_bank_fill", note=strengths["latin.word_bank_fill"]))
    return out



def _scene(noun_key: str, verb_key: str) -> tuple[str, str]:
    noun, verb = _NOUNS[noun_key], _VERBS[verb_key]
    prompt = f"A {noun[1]['gloss']} {verb[1]['scene']}. Quid est? Quid agit?"
    answer = f"{noun[0].capitalize()} est. {noun[0].capitalize()} {verb[0]}."
    return prompt, answer


def _used_scenes(assessment: GradedAssessment) -> set[tuple[str, str]]:
    """(noun, verb) pairs the quiz itself showed, so practice avoids them."""
    used = set()
    for section in assessment.sections:
        by_stimulus: dict[str, dict] = {}
        for item in section.items:
            if not item.stimulus:
                continue
            slot = by_stimulus.setdefault(item.stimulus, {})
            answer = _key(item.teacher_correction or item.student_response)
            if _asks_what(item.prompt):
                slot["noun"] = answer
            elif _asks_doing(item.prompt):
                slot["verb"] = answer
        used |= {(s.get("noun"), s.get("verb")) for s in by_stimulus.values()}
    return used


def generate_practice(diagnosis: Diagnosis, assessment: GradedAssessment, constraints: dict | None = None) -> PracticeSet | None:
    constraints = constraints or {}
    bank = {normalize(w) for w in assessment.word_bank()}
    nouns = [k for k in _NOUNS if k in bank]
    used = _used_scenes(assessment)
    taken: set[tuple[str, str]] = set(used)
    items: list[PracticeItem] = []
    targets: list[str] = []
    hints: list[str] = []

    def add_scene(target: str, noun: str, verbs: list[str], kind: str, hint: str = "") -> bool:
        for verb in verbs:
            if verb in bank and verb in _VERBS and (noun, verb) not in taken:
                prompt, answer = _scene(noun, verb)
                items.append(PracticeItem(kind=kind, target=target, prompt=prompt, expected_answer=answer, hint=hint))
                taken.add((noun, verb))
                return True
        return False

    for error in diagnosis.errors:
        if error.category == "latin.vocab.hypernym_substitution":
            ref_item = _find(assessment, error.item_ref)
            specific, general = _key(ref_item.teacher_correction), _key(ref_item.student_response)
            if specific not in bank or general not in bank:
                continue
            targets.append(error.category)
            gen_gloss = _NOUNS[general][1]["gloss"]
            hint = f"It is a {gen_gloss}. Is there a more exact word in your word bank?"
            add_scene(error.category, general, _NOUNS[general][1]["can"], "drill")
            shared = [v for v in _NOUNS[specific][1]["can"] if v in _NOUNS[general][1]["can"]]
            only_specific = [v for v in _NOUNS[specific][1]["can"] if v not in shared]
            add_scene(error.category, specific, only_specific + shared, "drill", hint)
            # The "trick" pair: the specific animal doing what the general one does.
            add_scene(error.category, specific, shared, "drill", hint)
            add_scene(error.category, general, _NOUNS[general][1]["can"], "drill")
            hints.append(
                f"If they give the general word ({_NOUNS[general][0]}), say: \"Yes, it is a {gen_gloss}. "
                f"Is there a more exact word in the bank?\" If they hesitate: \"Think of what it does that "
                f"other {gen_gloss}s don't.\""
            )
        elif error.category in ("latin.vocab.confusable_pair", "latin.question.what_vs_doing"):
            ref_item = _find(assessment, error.item_ref)
            wanted = _key(ref_item.teacher_correction)
            noun = wanted if wanted in _NOUNS else next((n for n in nouns), None)
            if noun and noun in bank:
                targets.append(error.category)
                add_scene(error.category, noun, _NOUNS[noun][1]["can"], "drill")
                add_scene(error.category, noun, list(reversed(_NOUNS[noun][1]["can"])), "drill")
        elif error.category == "latin.macron_omission":
            ref_item = _find(assessment, error.item_ref)
            targets.append(error.category)
            items.append(PracticeItem(
                kind="drill", target=error.category,
                prompt=f"Say the word aloud, stretching the long vowel, then write it: {ref_item.teacher_correction}",
                expected_answer=ref_item.teacher_correction,
            ))

    if any(e.category == "core.instruction.format" for e in diagnosis.errors):
        targets.append("core.instruction.format")
        # Re-answer scenes the child got right, never the missed one.
        missed = {_key(_find(assessment, e.item_ref).teacher_correction)
                  for e in diagnosis.errors if e.category.startswith("latin.")}
        solid = sorted(n for n in used if n[0] in _NOUNS and n[1] in _VERBS and n[0] not in missed)
        for noun, verb in solid[:2]:
            prompt, answer = _scene(noun, verb)
            items.append(PracticeItem(
                kind="sentence_habit", target="core.instruction.format",
                prompt="Answer in a whole sentence. " + prompt, expected_answer=answer,
            ))
        hints.append("Praise whole-sentence answers: \"Anas est.\" rather than \"anas\".")

    if not items:
        return None

    # Fresh retrieval at the end: animals and actions not used above.
    retrieval_target = targets[0]
    for noun in nouns:
        if sum(1 for i in items if i.kind == "retrieval") >= 2:
            break
        add_scene(retrieval_target, noun, list(reversed(_NOUNS[noun][1]["can"])), "retrieval")

    items = items[: constraints.get("max_items", 12)]
    minutes = max(3, min(constraints.get("max_minutes", 10), round(len(items) * 0.75)))
    script = " ".join(dict.fromkeys(hints)) + " No timer and no score; a miss gets a hint, not a correction."
    return PracticeSet(
        targets=list(dict.fromkeys(targets)),
        mode="drill",
        est_minutes=minutes,
        items=items,
        parent_script=script.strip(),
        recheck_schedule=["+3d", "+7d"],
    )


def _find(assessment: GradedAssessment, ref: str):
    for section in assessment.sections:
        for item in section.items:
            if _ref(section, item) == ref:
                return item
    raise KeyError(ref)
