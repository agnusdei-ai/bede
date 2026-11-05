"""Draft a new quiz or exam from an existing one (docs/PRACTICE_COACH.md,
"Quizzes and exams").

The adult gives Bede something to learn from: photos of a quiz, a previous
or prep exam, its text pasted in, or just a description of the lesson. Bede
works out what it covers and writes a fresh quiz for the chosen grade, level
and kind, from a quick ad-hoc check to a final exam.

Bede writes the questions and the answers, so the model's output is checked
in code before anyone sees it:

* **Maths answers are recomputed.** Any question written as an arithmetic
  expression is worked out with the maths pack's exact evaluator; a wrong
  model answer is replaced and the question marked ``computed``.
* **Every other answer is answered again, independently.** A second call
  sees the questions and the source material but not the first answers.
  Where the two agree the answer is ``checked``; where they disagree it stays
  ``verify`` and the second answer is shown beside it. This is a cross-check
  by the same kind of model against the material provided, not research
  against outside sources, so ``checked`` lowers the chance of a wrong key
  and does not remove it. Nothing is shown to a student until the adult
  approves the quiz.
* **Multiple-choice and true/false answers must be one of the options**, or
  the question is dropped rather than shipped with a broken key.
* **Faith subjects are not quizzed.** Scripture, Saints & Catechism and
  Morning Time are never scored, by the constitution's standing rule against
  measuring a child's spiritual life, so a scored quiz is refused for them.
* **Logic is not offered below grade 3**, the same stage gate the rest of the
  product applies.

Reading goes through the same route as photo reading (``extract.py``): the
household's local model, or the configured cloud provider only with consent
for this request. Nothing is stored: the photos, the source text and the
draft exist only in the request and on the adult's screen.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from pydantic import ValidationError

from core.config import settings
from models.practice import MAX_QUIZ_QUESTIONS, GeneratedQuiz, GenerateQuizRequest
from models.schemas import SUBJECT_LABELS, Subject
from services.practice import extract
from services.practice.core_checks import normalize
from services.practice.packs import math as math_pack

log = logging.getLogger(__name__)

GENERATE_TIMEOUT_SECONDS = 180

# Never scored: a child's spiritual life is not measured (CLAUDE.md, "Bede's
# Constitution"). Free Study has no content of its own to quiz.
NOT_QUIZZED = {Subject.scripture, Subject.saints, Subject.morning_time, Subject.free_study}
K2 = {"K", "1", "2"}

KIND_GUIDANCE = {
    "ad_hoc": "a quick check of one idea, a few minutes long",
    "quiz": "a short quiz on the lesson or week's work",
    "unit_test": "a test covering the whole unit, from simpler to harder questions",
    "midterm": "a midterm covering the term so far, mixing every topic in proportion",
    "final": "a cumulative final exam covering everything, with the most important ideas weighted most",
    "prep_exam": "practice for an upcoming exam, matching the source exam's format, question types and difficulty",
}
LEVEL_GUIDANCE = {
    "review": "easier than grade level: shore up the basics",
    "on_level": "at grade level",
    "challenge": "harder than grade level: stretch a strong student",
}
# Minutes a K-8 student typically needs per question of each type.
MINUTES = {"multiple_choice": 1.0, "true_false": 0.5, "short_answer": 1.5, "fill_in_blank": 1.0,
           "computation": 2.0, "written_response": 5.0}


class QuizRefused(ValueError):
    """The request is not one this feature will draft (subject, grade, material)."""


class QuizFailed(Exception):
    pass


def quiz_subjects() -> list[dict]:
    """The Bede subjects a quiz can be drafted for, for the subject picker."""
    return [{"id": s.value, "display_name": SUBJECT_LABELS.get(s, s.value)}
            for s in Subject if s not in NOT_QUIZZED]


def check_request(req: GenerateQuizRequest) -> Subject:
    try:
        subject = Subject(req.subject)
    except ValueError:
        raise QuizRefused(f"Bede has no subject called {req.subject!r}.")
    if subject in NOT_QUIZZED:
        raise QuizRefused(f"{SUBJECT_LABELS.get(subject, subject.value)} is not quizzed or scored.")
    if subject == Subject.logic and req.grade in K2:
        raise QuizRefused("Logic starts in grade 3.")
    if not req.has_material():
        raise QuizRefused("Add a quiz or exam to learn from, or describe what to cover.")
    return subject


def _rules() -> str:
    from services.ai_service import _constitution_preamble

    return _constitution_preamble() + """

You are drafting a school quiz or exam for an adult (a parent or teacher) to review before any student sees it.
Return ONLY one JSON object, no prose, in this shape:
{"title": str, "coverage": [str], "questions": [{"number": int, "type": "multiple_choice"|"true_false"|"short_answer"|"fill_in_blank"|"computation"|"written_response",
  "topic": str, "prompt": str, "options": [str], "answer": str}]}
Rules:
- First work out what the source material covers: topics, skills, question types and difficulty. List the topics in "coverage".
- Write NEW questions on that material. Never copy a source question word for word.
- Match the requested grade, level and kind. Use the question types the source uses, mixed sensibly.
- Every question has a correct answer in "answer". For multiple_choice give 3 or 4 "options" and make "answer" exactly one of them. For true_false the options are ["True", "False"].
- For a computation, write the problem as a plain expression with + − × ÷ and = (for example "48 ÷ 6 ="), so it can be checked.
- Keep every question age-appropriate and factual. If you are not sure of a fact, leave that question out.
- Never include a person's name, a school, a teacher, a class or a date.
- Do not ask about a student's beliefs, faith or feelings, and do not score them."""


def _request_text(req: GenerateQuizRequest, subject: Subject) -> str:
    grade = "Kindergarten" if req.grade == "K" else f"grade {req.grade}"
    parts = [
        f"Subject: {SUBJECT_LABELS.get(subject, subject.value)}",
        f"Grade: {grade}",
        f"Kind: {KIND_GUIDANCE[req.kind]}",
        f"Level: {LEVEL_GUIDANCE[req.level]}",
        f"Number of questions: exactly {req.question_count}",
    ]
    if req.focus:
        parts.append(f"What to cover: {req.focus}")
    if req.source_text:
        parts.append(f"Source material (an existing quiz or exam):\n{req.source_text}")
    if req.pages:
        parts.append("The attached pages are an existing quiz or exam to learn from.")
    return "\n".join(parts)


def _json_object(text: str) -> dict:
    raw = text.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise QuizFailed("Bede could not draft a quiz from this; try again or add more detail.")
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError as exc:
        raise QuizFailed("Bede could not draft a quiz from this; try again or add more detail.") from exc
    if not isinstance(data, dict):
        raise QuizFailed("Bede could not draft a quiz from this; try again or add more detail.")
    return data


def _key(text: str | None) -> str:
    """Comparison key that keeps digits and symbols (normalize() drops them)."""
    return re.sub(r"[^\w+\-×÷*/=.]+", " ", (text or "").lower()).strip(" .=")


def _option_answer(question: dict) -> str | None:
    """The answer as one of the options, or None if it is not one."""
    options = [str(o).strip() for o in question.get("options") or [] if str(o).strip()]
    answer = str(question.get("answer") or "").strip()
    if not options or not answer:
        return None
    for option in options:
        if normalize(option) == normalize(answer):
            return option
    match = re.fullmatch(r"\(?([A-Fa-f])[).:]?", answer)
    if match and ord(match.group(1).upper()) - 65 < len(options):
        return options[ord(match.group(1).upper()) - 65]
    return None


def finish(data: dict, req: GenerateQuizRequest, subject: Subject) -> tuple[GeneratedQuiz, dict]:
    """Check and clean the model's draft. Returns the quiz and what changed."""
    source = _key(req.source_text)
    seen: set[str] = set()
    questions: list[dict] = []
    report = {"answers_recomputed": 0, "dropped": 0}
    for raw in data.get("questions") or []:
        if not isinstance(raw, dict):
            report["dropped"] += 1
            continue
        q = {k: raw.get(k) for k in ("type", "topic", "prompt", "options", "answer")}
        q["prompt"] = str(q.get("prompt") or "").strip()[:600]
        q["topic"] = str(q.get("topic") or "").strip()[:80]
        q["options"] = [str(o).strip()[:200] for o in (q.get("options") or []) if str(o).strip()][:6]
        q["answer"] = str(q.get("answer") or "").strip()[:400]
        key = _key(q["prompt"])
        copied = len(key) >= 25 and key in source
        if not q["prompt"] or not q["answer"] or key in seen or copied:
            report["dropped"] += 1
            continue
        q["answer_check"] = "verify"
        if q.get("type") == "true_false":
            q["options"] = ["True", "False"]
        if q.get("type") in ("multiple_choice", "true_false"):
            fixed = _option_answer(q)
            if fixed is None:
                report["dropped"] += 1
                continue
            q["answer"] = fixed
        right = math_pack.evaluate(q["prompt"]) if q.get("type") in ("computation", "fill_in_blank", "short_answer") else None
        if right is not None:
            computed = math_pack._fmt(right, "." in q["prompt"])
            if math_pack.parse_answer(q["answer"].split(" (=")[0]) != right:
                report["answers_recomputed"] += 1
            q["answer"] = computed
            q["answer_check"] = "computed"
            q["type"] = "computation"
        seen.add(key)
        questions.append(q)
        if len(questions) >= req.question_count:
            break
    if not questions:
        raise QuizFailed("Bede could not draft usable questions from this; add more detail and try again.")
    for number, q in enumerate(questions, 1):
        q["number"] = number
    minutes = round(sum(MINUTES.get(q.get("type"), 1.5) for q in questions))
    coverage = [str(c).strip()[:120] for c in (data.get("coverage") or []) if str(c).strip()][:20]
    title = str(data.get("title") or "").strip()[:120] or SUBJECT_LABELS.get(subject, subject.value)
    try:
        quiz = GeneratedQuiz(
            title=title, subject=subject.value, grade=req.grade, kind=req.kind, level=req.level,
            coverage=coverage, est_minutes=max(1, min(120, minutes)), questions=questions,
        )
    except ValidationError as exc:
        raise QuizFailed("Bede's draft did not come out in a usable shape; please try again.") from exc
    report["short_by"] = max(0, req.question_count - len(questions))
    return quiz, report


_CHECK_RULES = """You are checking a school quiz before a teacher or parent uses it.
Answer every question yourself. Use the source material when it is given.
Return ONLY one JSON object: {"answers": [{"number": int, "answer": str, "sure": true|false}]}
- For multiple choice, answer with the exact text of one option.
- For true/false, answer "True" or "False".
- Set "sure" to false if the question is ambiguous, has more than one right answer, or you are not certain of the fact."""


def _same(a: str, b: str, options: list[str]) -> bool:
    na, nb = _key(a), _key(b)
    if not na or not nb:
        return False
    if options:
        return na == nb
    return na == nb or (len(nb) >= 3 and nb in na) or (len(na) >= 3 and na in nb)


def apply_check(quiz: GeneratedQuiz, answers: list) -> dict:
    """Mark each `verify` answer `checked` when the independent answer agrees."""
    by_number = {}
    for item in answers or []:
        if isinstance(item, dict) and isinstance(item.get("number"), int):
            by_number[item["number"]] = item
    report = {"checked": 0, "disagreed": 0, "unsure": 0}
    for q in quiz.questions:
        if q.answer_check != "verify" or q.type == "written_response":
            continue
        second = by_number.get(q.number)
        if not second:
            continue
        other = str(second.get("answer") or "").strip()[:400]
        if second.get("sure") is not True:
            report["unsure"] += 1
            continue
        if _same(q.answer, other, q.options):
            q.answer_check = "checked"
            report["checked"] += 1
        elif other:
            q.second_answer = other
            report["disagreed"] += 1
    return report


async def _check(client, quiz: GeneratedQuiz, req: GenerateQuizRequest) -> dict:
    """The independent second answer. Failure leaves every answer `verify`."""
    pending = [q for q in quiz.questions if q.answer_check == "verify" and q.type != "written_response"]
    if not pending:
        return {"checked": 0, "disagreed": 0, "unsure": 0}
    lines = []
    for q in pending:
        options = "".join(f"\n   {chr(65 + i)}) {o}" for i, o in enumerate(q.options))
        lines.append(f"{q.number}. {q.prompt}{options}")
    text = "Questions:\n" + "\n".join(lines)
    if req.source_text:
        text += f"\n\nSource material:\n{req.source_text}"
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.tutor_model,
                max_tokens=min(8000, 300 + 120 * len(pending)),
                temperature=0,
                system=_CHECK_RULES,
                messages=[{"role": "user", "content": [{"type": "text", "text": text}]}],
            ),
            timeout=GENERATE_TIMEOUT_SECONDS,
        )
        data = _json_object(extract._text_of(response))
    except Exception as exc:  # never log the request
        log.warning("Quiz answer check failed: %s", type(exc).__name__)
        return {"checked": 0, "disagreed": 0, "unsure": 0, "check_failed": True}
    return apply_check(quiz, data.get("answers") or [])


def _local_client():
    from services.adapters import router

    if "local" not in router.configured_adapters():
        raise extract.ReadingUnavailable(
            "Teacher quizzes are drafted on the school's own AI model, and none is set up on this install.")
    return router.resolve_local_only()


def _image(media: str, data: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


TRANSCRIPT_CHARS_PER_GROUP = 6000


async def _transcribe(client, group: list[tuple[str, str]], first_page: int, before_call=None) -> str:
    """Copy one group of source pages out as plain text for the drafting call."""
    if before_call is not None:
        await before_call()
    last = first_page + len(group) - 1
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.tutor_model,
                max_tokens=3000,
                temperature=0,
                system=("Copy out the questions, answer choices and any marked answers on these quiz pages as "
                        "plain text, in order. Leave out any person's name, school, teacher, class or date."),
                messages=[{"role": "user", "content": [_image(m, d) for m, d in group] + [
                    {"type": "text", "text": f"Pages {first_page} to {last} of the source."}]}],
            ),
            timeout=GENERATE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise QuizFailed("Reading the uploaded pages took too long; please try again.") from exc
    except Exception as exc:  # never log the request: it holds the photos
        log.warning("Quiz source reading failed: %s", type(exc).__name__)
        raise QuizFailed("Bede could not read the uploaded pages right now; please try again.") from exc
    return f"[Pages {first_page}-{last}]\n" + extract._text_of(response)[:TRANSCRIPT_CHARS_PER_GROUP]


async def generate(req: GenerateQuizRequest, local_only: bool = False,
                   before_call=None) -> tuple[GeneratedQuiz, dict]:
    """Draft, check in code, then cross-check. `local_only` (teachers) never
    reaches a cloud provider: their uploads can hold students' work."""
    subject = check_request(req)
    # consent and routing are settled before anything is parsed
    if local_only:
        client = _local_client()
    elif req.pages:
        # Photos: the photo-reading rules, including PRACTICE_CLOUD_READING_ENABLED.
        client = extract._choose_client(req)
    else:
        # Typed text only: no photo leaves the browser, so the photo switch
        # does not apply; the parent still agrees to the provider by name.
        client = extract.text_draft_client(req)
    content: list[dict] = []
    transcripts: list[str] = []
    if req.pages:
        groups = extract.page_groups([p.data for p in req.pages])
        first = await groups.__anext__()
        second = await anext(groups, None)
        if second is None:
            # Up to one group: the drafting call sees the pages themselves.
            content += [_image(m, d) for m, d in first]
        else:
            # A longer source is copied out as text a group at a time, so no
            # call (and no moment in memory) holds more than one group.
            page = 1
            for group in (first, second):
                transcripts.append(await _transcribe(client, group, page, before_call))
                page += len(group)
            del first, second
            async for group in groups:
                transcripts.append(await _transcribe(client, group, page, before_call))
                page += len(group)
    text = _request_text(req, subject)
    if transcripts:
        text += "\nThe uploaded pages, copied out as text:\n" + "\n\n".join(transcripts)
    content.append({"type": "text", "text": text})
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.tutor_model,
                max_tokens=min(16000, 600 + 280 * req.question_count),
                temperature=0.4,
                system=_rules(),
                messages=[{"role": "user", "content": content}],
            ),
            timeout=GENERATE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise QuizFailed("Drafting took too long; try fewer questions.") from exc
    except Exception as exc:  # never log the request: it can hold the photos
        log.warning("Quiz drafting failed: %s", type(exc).__name__)
        raise QuizFailed("Bede could not draft a quiz right now; please try again.") from exc
    quiz, report = finish(_json_object(extract._text_of(response)), req, subject)
    report.update(await _check(client, quiz, req))
    return quiz, report


__all__ = ["MAX_QUIZ_QUESTIONS", "QuizFailed", "QuizRefused", "apply_check", "check_request", "finish", "generate", "quiz_subjects"]
