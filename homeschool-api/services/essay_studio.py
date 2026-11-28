"""Essay Studio: the rules that do not depend on HTTP (docs/ESSAY_STUDIO.md).

Built on classical writing practice: three exercises from the progymnasmata
(narrative, refutation, thesis), a model read first, the opposing view stated
fairly before it is answered, and coaching whose emphasis moves from clarity
and form to reasoning and evidence to audience.

What is code here rather than prompt, and why:

- **Eligibility and stage.** Grades 6-12 only. Whether a student is in the
  logic or the rhetoric stage comes from their saved grade and the
  per-student `essay_rhetoric_from_grade` setting, never from a request, and
  decides which exercises they may start.
- **Criteria** are a closed list, tiered, and limited by exercise and stage.
  Coaching may only name one of them, so the model cannot invent a grade, a
  level or a ranking.
- **Counts** (words, paragraphs, sentences) are worked out here.
- **The reflect questions** are written here, not by a model.
- **Authorship.** `clean_coaching` is the gate between the model's reply and
  the student: one note and one question, each length-capped, the question
  ending in a question mark, and anything quoting words that are not in the
  student's own draft dropped, since that is the shape of a sentence written
  FOR them or an invented quotation. Nothing here can change the draft; the
  draft only changes through the student's own saves.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

from models.schemas import GradeStage, SessionConfig, Subject, grade_to_stage

MAX_TEXT_CHARS = 20_000
MAX_PROMPT_CHARS = 300
MAX_FIELD_CHARS = 1_200
MAX_PLAN_POINTS = 6
MAX_COACHING_PER_DAY = 12
MAX_NOTE_CHARS = 240
DEFAULT_RHETORIC_FROM_GRADE = 9

ESSAY_SUBJECTS = (Subject.language_arts, Subject.living_books)

#: The card's prefix, the same in every locale, so the once-a-session scan of
#: the conversation keys on it rather than on translated words.
CARD_PREFIX = "\U0001F4DD "  # memo

STAGES = ("task", "model", "position", "plan", "draft", "examine", "revise", "reflect")
EXERCISES = ("narrative", "refutation", "thesis")
#: Exercises answering another view; only these have the opposing-view step.
DIALECTIC_EXERCISES = frozenset({"refutation", "thesis"})
STAGE_EXERCISES = {
    "logic": ("narrative", "refutation"),
    "rhetoric": ("narrative", "refutation", "thesis"),
}

_EXERCISE_LABELS = {
    "narrative": ("Narrative", "Narración"),
    "refutation": ("Refutation", "Refutación"),
    "thesis": ("Thesis", "Tesis"),
}

#: (id, tier, English, Spanish). The first five are the composition
#: dimensions in services/diagnostic/composition.py, reused by name only.
CRITERIA: tuple[tuple[str, str, str, str], ...] = (
    ("sequence", "form", "Logical order", "Orden lógico"),
    ("language_quality", "form", "Own words and voice", "Palabras y voz propias"),
    ("completeness", "reasoning", "Covers the main ideas", "Cubre las ideas principales"),
    ("detail", "reasoning", "Evidence and detail", "Evidencia y detalle"),
    ("synthesis", "reasoning", "Connects to what you know", "Conecta con lo que sabes"),
    ("position", "reasoning", "Clear position", "Postura clara"),
    ("opposing_view", "reasoning", "Fair opposing view", "Postura contraria justa"),
    ("audience", "audience", "Audience and persuasion", "Público y persuasión"),
)
_DIALECTIC_ONLY = frozenset({"position", "opposing_view"})
_AUDIENCE_STAGES = frozenset({"examine", "revise"})

_REFLECT = {
    "en": (
        "Did you describe your source fairly, in a way its author would recognize?",
        "Is every fact and quotation in your essay really from your source, word for word where you quoted it?",
    ),
    "es": (
        "¿Describiste tu fuente con justicia, de un modo que su autor reconocería?",
        "¿Cada dato y cita de tu ensayo viene de verdad de tu fuente, palabra por palabra donde citaste?",
    ),
}
_REFLECT_DIALECTIC = {
    "en": "Did you state the other side as its best defenders would, before you answered it?",
    "es": "¿Presentaste la otra postura como la defenderían sus mejores defensores, antes de responderla?",
}


# ── Eligibility and stage ────────────────────────────────────────────────────

def _grade_number(grade: Optional[str]) -> Optional[int]:
    try:
        return int(str(grade).strip())
    except (TypeError, ValueError):
        return None


def stage_band(config: SessionConfig) -> Optional[str]:
    """"logic" or "rhetoric" for grades 6-12, None otherwise."""
    number = _grade_number(config.grade)
    if number is None or grade_to_stage(str(number)) != GradeStage.independent:
        return None
    start = config.essay_rhetoric_from_grade or DEFAULT_RHETORIC_FROM_GRADE
    return "rhetoric" if number >= start else "logic"


def exercises_for(config: SessionConfig) -> tuple[str, ...]:
    band = stage_band(config)
    return STAGE_EXERCISES[band] if band else ()


def exercise_label(exercise: str, locale: str = "en") -> str:
    return _EXERCISE_LABELS[exercise][1 if locale == "es" else 0]


def uses_opposing_view(exercise: str) -> bool:
    return exercise in DIALECTIC_EXERCISES


def criteria_for(exercise: str, stage: Optional[str] = None, locale: str = "en") -> list[dict]:
    """The criteria coaching may name for this exercise, at this stage when
    one is given: no argument criteria for narrative, and audience only once
    the student is examining or revising."""
    out = []
    for cid, tier, en, es in CRITERIA:
        if cid in _DIALECTIC_ONLY and not uses_opposing_view(exercise):
            continue
        if tier == "audience" and stage is not None and stage not in _AUDIENCE_STAGES:
            continue
        out.append({"id": cid, "tier": tier, "label": es if locale == "es" else en})
    return out


def reflect_questions(exercise: str, locale: str = "en") -> list[str]:
    lang = "es" if locale == "es" else "en"
    questions = list(_REFLECT[lang])
    if uses_opposing_view(exercise):
        questions.insert(1, _REFLECT_DIALECTIC[lang])
    return questions


# ── Counts and titles ────────────────────────────────────────────────────────

_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def paragraph_count(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text or "") if p.strip()])


def sentence_count(text: str) -> int:
    body = (text or "").strip()
    if not body:
        return 0
    return len(_SENTENCE_END.findall(body)) + (0 if re.search(r"[.!?]\s*$", body) else 1)


def analysis(text: str) -> dict:
    return {"word_count": word_count(text), "paragraph_count": paragraph_count(text),
            "sentence_count": sentence_count(text)}


def title_for(prompt: str, exercise: str, locale: str = "en") -> str:
    words = (prompt or "").split()
    if not words:
        return exercise_label(exercise, locale)
    return " ".join(words[:8]) + ("…" if len(words) > 8 else "")


# ── Coaching: the prompt and the gate ────────────────────────────────────────

_TIER_ORDER = ("form", "reasoning", "audience")


def coaching_system_prompt(exercise: str, stage: str, band: str, locale: str = "en",
                           learning_support: Optional[list[str]] = None) -> str:
    from services.ai_service import _constitution_preamble, _sanitize_parent_field

    allowed = criteria_for(exercise, stage)
    tiers = [t for t in _TIER_ORDER if any(c["tier"] == t for c in allowed)]
    by_tier = "; ".join(
        f"{t}: " + ", ".join(c["id"] for c in allowed if c["tier"] == t) for t in tiers
    )
    exercise_line = {
        "narrative": "a narrative: telling one event clearly, in order, with the details that matter",
        "refutation": "a refutation: showing why a stated claim does not hold, after stating it fairly",
        "thesis": "a thesis: arguing a general question, stating and answering the other side fairly",
    }[exercise]
    dialectic = (
        "- If the student has not yet stated the opposing view fairly, your question asks them to state it, "
        "in their own words, before replying to it. Never argue the opposing side for them and never supply it.\n"
        if uses_opposing_view(exercise) else ""
    )
    supports = [s for s in (_sanitize_parent_field(x, 120) for x in (learning_support or [])) if s]
    support_line = (
        "- What helps this student (from their parent; follow it, never mention it): " + "; ".join(supports) + "\n"
        if supports else ""
    )
    language = "Write the note and the question in Spanish." if locale == "es" else "Write in English."
    return _constitution_preamble() + f"""

<essay_studio_coaching>
You are Bede, coaching a student in grades 6 to 12 ({band} stage) who is writing {exercise_line}.
They are at the "{stage}" step. This is FORMATIVE coaching: you name the single most useful
thing to work on next and ask one question. You are a guide, not the teacher, and not a grader.

Rules you must follow:
- The student is the author. Never write any part of their essay: no thesis, topic sentence,
  outline, replacement sentence, model paragraph or example of how it could read. Do not
  rewrite their words. Ask a question that helps them write it themselves.
- Never invent a quotation, a source, a fact or evidence. Quote only words that are in the
  student's own draft.
- Never give a grade, score, level or percentage, and never compare the student with anyone.
- Emphasis follows the task: clarity and form first, then reasoning and evidence, then
  audience and persuasion. Choose the earliest tier that still needs work.
  Allowed criteria by tier — {by_tier}.
- Do not impose one template on every essay. Work with how this student is building theirs.
{dialectic}{support_line}- The note is at most two short sentences. The question is one question.
- {language}

Reply with ONLY a JSON object:
{{"criterion": one allowed criterion id, "note": "...", "question": "..."}}
</essay_studio_coaching>"""


def coaching_user_message(draft: dict) -> str:
    points = "\n".join(f"- {p}" for p in draft.get("plan") or []) or "(none yet)"
    parts = [
        f"Task: {draft.get('prompt') or '(the student did not give one)'}",
        f"What the student said their model passage does: {draft.get('model_observation') or '(nothing yet)'}",
        f"Position: {draft.get('position') or '(none yet)'}",
    ]
    if uses_opposing_view(draft["exercise"]):
        parts.append(f"Opposing view, as the student stated it: {draft.get('opposing_view') or '(not stated yet)'}")
    parts.append(f"Plan:\n{points}")
    parts.append(f"Draft:\n<<<DRAFT\n{draft.get('text') or ''}\nDRAFT>>>")
    return "\n\n".join(parts)


_QUOTED = re.compile(r"[\"“”«»]([^\"“”«»]{12,})[\"“”«»]")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def quotes_outside(value: str, own_words: str) -> bool:
    """True when `value` quotes a span of 12+ characters that the student's
    own words do not contain."""
    body = _norm(own_words)
    return any(_norm(q) not in body for q in _QUOTED.findall(value or ""))


def _short(value, limit: int = MAX_NOTE_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def parse_model_json(raw: str) -> dict:
    if not raw:
        return {}
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class CoachingUnusable(Exception):
    """The model's reply had nothing that passed the gate."""


def own_words(draft: dict) -> str:
    """Everything the student wrote in this draft, for the quotation check."""
    return "\n".join(str(draft.get(k) or "") for k in (
        "prompt", "model_source", "model_observation", "position", "opposing_view", "text", "reflection",
    )) + "\n" + "\n".join(draft.get("plan") or [])


def clean_coaching(data: dict, *, draft: dict, stage: str, draft_version: int,
                   locale: str = "en", now: Optional[datetime] = None) -> dict:
    """Turn the model's reply into what the student sees, or raise
    CoachingUnusable."""
    allowed = {c["id"]: c for c in criteria_for(draft["exercise"], stage, locale)}
    choice = allowed.get(str(data.get("criterion") or ""))
    note = _short(data.get("note"))
    question = _short(data.get("question"))
    words = own_words(draft)
    if (choice is None or not note or not question.endswith("?")
            or quotes_outside(note, words) or quotes_outside(question, words)):
        raise CoachingUnusable
    return {
        "draft_version": draft_version,
        "created_at": (now or datetime.now(timezone.utc)).isoformat(),
        "stage": stage,
        "formative": True,
        "criterion": choice["id"],
        "label": choice["label"],
        "tier": choice["tier"],
        "note": note,
        "question": question,
        "analysis": analysis(draft.get("text") or ""),
    }


def coaching_used_today(history: list, now: Optional[datetime] = None) -> int:
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    return sum(1 for at in history or [] if str(at)[:10] == today)
