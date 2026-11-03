"""Spelling subject pack: what a misspelling shows, and words that practise it.

Deterministic, like the Latin and maths packs. Each miss is compared letter by
letter with the teacher's correction and named by the pattern that explains
it: a homophone, two letters swapped, ie/ei, a doubled consonant, a silent e,
a suffix rule, a vowel pattern, a sound spelled another way, a letter left out
or added. A word with no correction on the page is handed to the parent,
because guessing the intended word would be guessing.

Practice is look-say-cover-write-check: the missed word itself first (unlike
Latin or maths, practising the very word IS the remedy for spelling), then
words from ``item_bank/patterns.json`` that share its pattern. The bank only
supplies example words for a pattern the child already missed; it never adds
a pattern.
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

_ROOT = Path(__file__).resolve().parent
_TAXONOMY = json.loads((_ROOT / "taxonomy.json").read_text(encoding="utf-8"))
_BANK = json.loads((_ROOT / "item_bank" / "patterns.json").read_text(encoding="utf-8"))
_HOMOPHONES = [{w.lower() for w in group} for group in _BANK["homophones"]]
_FRAMES = [(sentence, word) for sentence, word in _BANK["homophone_frames"]]
_VOWELS = set("aeiouy")


def words(text: str | None) -> list[str]:
    return [w.lower().strip("'") for w in re.findall(r"[a-zA-Z']+", text or "") if w.strip("'")]


def word(text: str | None) -> str:
    """The first word written, lower-cased, without punctuation. A teacher's
    correction leads with the right spelling ("their (not there)")."""
    found = words(text)
    return found[0] if found else ""


def as_written(text: str | None) -> str:
    """The first word of a correction with its own capitals, for display."""
    found = [w.strip("'") for w in re.findall(r"[a-zA-Z']+", text or "") if w.strip("'")]
    return found[0] if found else ""


def answer_word(response: str | None, wanted: str) -> str:
    """The child's attempt at `wanted`: their only word, or, when they wrote a
    whole sentence, the word in it closest to the target."""
    found = words(response)
    if len(found) <= 1:
        return found[0] if found else ""
    return min(found, key=lambda w: (_distance(w, wanted), abs(len(w) - len(wanted))))


def _distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _clip(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ref(section, item) -> str:
    return f"{section.label} #{item.number}"


def _skeleton(w: str) -> str:
    return "".join(c for c in w if c not in _VOWELS)


def _sounds(w: str) -> str:
    """A rough sound-alike key: the same sound spelled another way maps alike."""
    w = w.replace("ph", "f").replace("ck", "k").replace("qu", "kw").replace("x", "ks")
    w = re.sub(r"c(?=[eiy])", "s", w)
    w = w.replace("c", "k").replace("q", "k").replace("kn", "n").replace("wr", "r").replace("gh", "")
    w = re.sub(r"(.)\1", r"\1", w)
    return w


def _one_deleted(longer: str, shorter: str) -> bool:
    if len(longer) != len(shorter) + 1:
        return False
    return any(longer[:i] + longer[i + 1:] == shorter for i in range(len(longer)))


def _undouble(w: str) -> str:
    return re.sub(r"([b-df-hj-np-tv-z])\1", r"\1", w)


def _y_kept(g: str, c: str) -> bool:
    """happyness/happiness, cryed/cried, babys/babies: the y was not changed."""
    if len(g) == len(c):
        diffs = [i for i in range(len(c)) if g[i] != c[i]]
        return len(diffs) == 1 and g[diffs[0]] == "y" and c[diffs[0]] == "i"
    return any(c.endswith(end) and c[: -len(end)] + short == g for end, short in (("ies", "ys"), ("ied", "yed")))


def explain(given: str, wanted: str) -> tuple[str, str]:
    """(category, evidence) for one misspelling."""
    g, c = given.lower(), wanted.lower()
    shown = f"wrote {given} for {wanted}"
    if any(g in group and c in group for group in _HOMOPHONES):
        return "spelling.homophone", f"{shown}: a word that sounds the same but means something else"
    if len(g) == len(c) and sorted(g) == sorted(c):
        diffs = [i for i in range(len(c)) if g[i] != c[i]]
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            if {g[diffs[0]], g[diffs[1]]} == {"i", "e"}:
                return "spelling.ie_ei", f"{shown}: i and e the other way round"
            return "spelling.transposition", f"{shown}: two letters swapped"
    if _undouble(g) == _undouble(c) and g != c:
        return "spelling.double_consonant", f"{shown}: the doubled letter is {'missing' if len(g) < len(c) else 'extra'}"
    if c.endswith(("ing", "ed")):
        stem_c = c[:-3] if c.endswith("ing") else c[:-2]
        stem_g = g[:-3] if g.endswith("ing") else (g[:-2] if g.endswith("ed") else g)
        if stem_g == stem_c + "e":
            return "spelling.suffix.drop_e", f"{shown}: the silent e drops before -{c[len(stem_c):]}"
    if _y_kept(g, c):
        return "spelling.suffix.y_to_i", f"{shown}: the y changes to i before the ending"
    if c.endswith("e") and g == c[:-1]:
        return "spelling.silent_e", f"{shown}: the silent e at the end is missing"
    if _skeleton(g) == _skeleton(c) and g != c:
        return "spelling.vowel_pattern", f"{shown}: the consonants are right; the vowel spelling is different"
    if _sounds(g) == _sounds(c):
        return "spelling.sound_spelling", f"{shown}: the same sound spelled another way"
    if _one_deleted(c, g):
        return "spelling.omitted_letter", f"{shown}: one letter left out"
    if _one_deleted(g, c):
        return "spelling.extra_letter", f"{shown}: one letter added"
    return "spelling.word_specific", f"{shown}"


def classify_errors(assessment: GradedAssessment, history: list | None = None) -> list[ErrorInstance]:
    out: list[ErrorInstance] = []
    for section in assessment.sections:
        for item in section.items:
            if item.needs_parent() or item.teacher_mark not in ("incorrect", "partial"):
                continue
            if not words(item.student_response):
                continue  # core.unanswered owns blanks
            wanted = word(item.teacher_correction)
            given = answer_word(item.student_response, wanted) if wanted else word(item.student_response)
            ref = _ref(section, item)
            if not wanted:
                out.append(ErrorInstance(
                    item_ref=ref, category="spelling.unclassified", audience="parent_only",
                    evidence=_clip(f"wrote {item.student_response}; there is no correct spelling on the page to compare with, so please add it"),
                ))
                continue
            if given == wanted:
                out.append(ErrorInstance(
                    item_ref=ref, category="spelling.unclassified", audience="parent_only",
                    evidence=_clip(f"{item.student_response} matches the correction; the mark may be about a capital letter or handwriting"),
                ))
                continue
            category, evidence = explain(given, wanted)
            out.append(ErrorInstance(item_ref=ref, category=category, evidence=_clip(evidence)))
    return out


def find_strengths(assessment: GradedAssessment) -> list[Strength]:
    text = _TAXONOMY["strengths"]
    marked = [i for s in assessment.sections for i in s.items if not i.needs_parent() and i.teacher_mark != "unmarked"]
    right = [i for i in marked if i.teacher_mark == "correct" and word(i.student_response)]
    out: list[Strength] = []
    long_words = [word(i.student_response) for i in right if len(word(i.student_response)) >= 8]
    if long_words:
        out.append(Strength(category="spelling.long_words", note=f"{text['spelling.long_words']}: {', '.join(long_words[:5])}"))
    if marked and len(right) == len(marked):
        out.append(Strength(category="spelling.all_correct", note=text["spelling.all_correct"]))
    return out


def _rng(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], 16))


def _find(assessment: GradedAssessment, ref: str):
    for section in assessment.sections:
        for item in section.items:
            if _ref(section, item) == ref:
                return item
    raise KeyError(ref)


def generate_practice(diagnosis: Diagnosis, assessment: GradedAssessment, constraints: dict | None = None) -> PracticeSet | None:
    constraints = constraints or {}
    max_items = constraints.get("max_items", 12)
    on_page = {word(i.student_response) for s in assessment.sections for i in s.items} | \
              {word(i.teacher_correction) for s in assessment.sections for i in s.items}
    used: set[str] = set()
    items: list[PracticeItem] = []
    targets: list[str] = []
    script: list[str] = []
    misses = [e for e in diagnosis.errors if e.audience == "parent_and_child" and e.category.startswith("spelling.")]
    if not misses:
        return None
    extra_per_miss = max(0, min(2, (max_items - len(misses)) // len(misses)))

    for error in misses:
        item = _find(assessment, error.item_ref)
        wanted = as_written(item.teacher_correction)
        hint = _TAXONOMY["categories"][error.category].get("hint", "")
        if error.category not in targets:
            targets.append(error.category)
            guidance = _TAXONOMY["categories"][error.category].get("parent_script")
            if guidance:
                script.append(guidance)
        if error.category == "spelling.homophone":
            items.append(PracticeItem(
                kind="drill", target=error.category,
                prompt=_clip(f"Which spelling fits? {item.prompt}") if "_" in (item.prompt or "") else f"Use {wanted} in a sentence of your own, then write it.",
                expected_answer=wanted, hint=hint,
            ))
            group = next(g for g in _HOMOPHONES if word(wanted) in g)
            frames = [(s, w) for s, w in _FRAMES if w.lower() in group and w.lower() not in used]
            for sentence, answer in _rng(error.item_ref, wanted).sample(frames, min(extra_per_miss, len(frames))):
                used.add(answer.lower())
                items.append(PracticeItem(kind="drill", target=error.category,
                                          prompt=f"Fill in the right word: {sentence}", expected_answer=answer, hint=hint))
            continue
        items.append(PracticeItem(
            kind="drill", target=error.category,
            prompt=f"Look, say, cover, write, check: {wanted}",
            expected_answer=wanted, hint=hint,
        ))
        used.add(word(wanted))
        pool = [w for w in _BANK.get(error.category, []) if w.lower() not in on_page and w.lower() not in used]
        pool.sort(key=lambda w: abs(len(w) - len(wanted)))
        nearby = pool[: max(4, extra_per_miss * 2)]
        for extra in _rng(error.item_ref, wanted).sample(nearby, min(extra_per_miss, len(nearby))):
            used.add(extra.lower())
            items.append(PracticeItem(kind="drill", target=error.category,
                                      prompt=f"Same pattern: look, say, cover, write, check: {extra}",
                                      expected_answer=extra, hint=hint))

    # End with the missed words once more, unseen, as retrieval.
    for error in misses:
        if len(items) >= max_items:
            break
        wanted = as_written(_find(assessment, error.item_ref).teacher_correction)
        items.append(PracticeItem(kind="retrieval", target=error.category,
                                  prompt="Ask the adult to say the word, then write it without looking.",
                                  expected_answer=wanted))

    items = items[:max_items]
    minutes = max(3, min(constraints.get("max_minutes", 10), round(len(items) * 0.6)))
    text = " ".join(dict.fromkeys(script)) + " Say each word clearly once; let them check their own spelling against the word before you do."
    return PracticeSet(
        targets=targets,
        mode="drill",
        est_minutes=minutes,
        items=items,
        parent_script=text.strip()[:1200],
        recheck_schedule=["+3d", "+7d"],
    )
