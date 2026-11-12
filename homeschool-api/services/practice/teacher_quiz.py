"""Teacher quizzes with reviewable answer keys (docs/PRACTICE_COACH.md,
"Teacher quizzes with answer keys").

The workflow, and which step does what:

1. The teacher writes a quiz, or uploads one (``extract``) for Bede to read.
2. The teacher reviews the questions and supplies or approves the key
   (``approval_problems`` / ``approve``). Nothing is approved for them.
3. The teacher prints and gives the quiz (on the screen; nothing here).
4. The teacher uploads one student's completed work (``read_submission``).
5. Bede proposes readings and scores (``score_responses``). Scoring is
   deterministic: a response is compared with the approved key in code,
   numbers with the maths pack's exact evaluator. Only a written response
   with a rubric gets a model-proposed score, and it is always marked for
   the teacher.
6. The teacher approves or corrects each result (``finalize``). Nothing
   counts until every result is settled, and Bede never settles one.

Three rules hold throughout:

* **The school's own model only.** A teacher's upload can hold students'
  work, so every model call here goes through ``resolve_local_only()`` and
  never a cloud provider (register entry 39). With no local model the
  teacher is told so plainly.
* **The key never reaches the reader of a student's work.** The reader sees
  the questions and options, not the answers, so it copies what the student
  wrote rather than what the key says.
* **Nothing is stored.** Pages, the quiz, the student's answers and the
  results exist only in the request and on the teacher's screen. No learner
  is named.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from fractions import Fraction

from pydantic import ValidationError

from core.config import settings
from models.practice import (
    CONFIDENCE_FLOOR,
    MAX_QUESTION_POINTS,
    ExtractQuizRequest,
    FinalizeResultsRequest,
    ProposedScore,
    StudentResponse,
    TeacherQuestion,
    TeacherQuiz,
)
from models.schemas import SUBJECT_LABELS, Subject
from services.practice import extract, generate
from services.practice.core_checks import normalize
from services.practice.packs import math as math_pack

log = logging.getLogger(__name__)

READ_TIMEOUT_SECONDS = 120
LOCAL_PROVIDER = "the school's own AI model"


class UploadConsentRequired(Exception):
    """Pages were sent without the teacher's acknowledgement for this upload."""


class QuizNotApproved(ValueError):
    def __init__(self, problems: list[dict]):
        self.problems = problems
        super().__init__("This quiz is not approved yet.")


class ResultsNotSettled(ValueError):
    def __init__(self, numbers: list[int]):
        self.numbers = numbers
        super().__init__("Some results still need the teacher.")


# ── Approving the key ────────────────────────────────────────────────────────

def _subject_problems(subject: str, grade: str) -> list[dict]:
    try:
        chosen = Subject(subject)
    except ValueError:
        return [{"number": None, "problem": "unknown_subject"}]
    if chosen in generate.NOT_QUIZZED:
        return [{"number": None, "problem": "not_quizzed"}]
    if chosen == Subject.logic and grade in generate.K2:
        return [{"number": None, "problem": "logic_below_grade_3"}]
    return []


def _option_for(question: TeacherQuestion, text: str | None) -> str | None:
    """The option a written answer names, by its text or its letter."""
    if not text or not question.options:
        return None
    return generate._option_answer({"options": question.options, "answer": text})


def approval_problems(quiz: TeacherQuiz) -> list[dict]:
    """Everything that stops the key being approved. Empty means approvable."""
    problems = _subject_problems(quiz.subject, quiz.grade)
    numbers = [q.number for q in quiz.questions]
    if len(set(numbers)) != len(numbers):
        problems.append({"number": None, "problem": "duplicate_numbers"})
    for q in quiz.questions:
        if q.reading_note:
            problems.append({"number": q.number, "problem": "reading_unsettled"})
        if q.type in ("multiple_choice", "true_false") and len(q.options) < 2:
            problems.append({"number": q.number, "problem": "too_few_options"})
        if q.type != "written_response" and not q.answer.strip():
            problems.append({"number": q.number, "problem": "no_key"})
            continue
        if q.type in ("multiple_choice", "true_false") and q.answer and _option_for(q, q.answer) is None:
            problems.append({"number": q.number, "problem": "answer_not_an_option"})
        if q.has_key() and not q.key_approved:
            problems.append({"number": q.number, "problem": "key_not_approved"})
    return problems


def approve(quiz: TeacherQuiz) -> TeacherQuiz:
    problems = approval_problems(quiz)
    if problems:
        raise QuizNotApproved(problems)
    approved = quiz.model_copy(deep=True)
    approved.approved = True
    return approved


def require_approved(quiz: TeacherQuiz) -> None:
    """Scoring trusts no flag the client set: it checks the key again."""
    problems = approval_problems(quiz)
    if not quiz.approved and not problems:
        problems = [{"number": None, "problem": "not_approved"}]
    if problems:
        raise QuizNotApproved(problems)


# ── Reading a quiz the teacher already has ───────────────────────────────────

def _client():
    """The school's own model, never a cloud provider (register entry 39)."""
    from services.adapters import router

    if "local" not in router.configured_adapters():
        raise extract.ReadingUnavailable(
            "Teacher quizzes are read on the school's own AI model, and none is set up on this install.")
    return router.resolve_local_only()


_EXTRACT_RULES = """You are reading a school quiz or exam a teacher wrote, so the teacher can review it before giving it to a class.
The pages may mix printed text, scanned text, diagrams, and handwritten marks.
Return ONLY one JSON object, no prose, in this shape:
{"title": str, "questions": [{"number": int, "type": "multiple_choice"|"true_false"|"short_answer"|"fill_in_blank"|"computation"|"written_response",
  "prompt": str, "stimulus": str|null, "options": [str], "answer": str|null, "answer_from_page": true|false,
  "points": int|null, "confidence": number 0-1, "ask_teacher": str|null}]}
Rules:
- Copy every question as written. Do not rewrite, add or drop questions.
- "stimulus" briefly describes a diagram or picture the question needs (e.g. "diagram: a right triangle with sides 3 and 4").
- If the page shows the answer (an answer key, or the teacher's marked answer), copy it into "answer" and set "answer_from_page" true.
- Otherwise suggest the answer yourself and set "answer_from_page" false. For a written response with no single answer, leave "answer" null.
- For multiple choice, "options" lists each choice's text without its letter, and "answer" is exactly one option.
- If you cannot read something with confidence, give your best reading, lower "confidence", and say what is uncertain in "ask_teacher".
- Never transcribe a person's name, a school, a teacher, a class or a date. There is no field for them."""


def _parse_json(text: str) -> dict:
    raw = (text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise extract.ReadingFailed("Bede could not read a quiz from this; try clearer pages or paste the text.")
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError as exc:
        raise extract.ReadingFailed("Bede could not read a quiz from this; try clearer pages or paste the text.") from exc
    if not isinstance(data, dict):
        raise extract.ReadingFailed("Bede could not read a quiz from this; try clearer pages or paste the text.")
    return data


def finish_extracted(data: dict, subject: str, grade: str) -> TeacherQuiz:
    """Turn the reader's output into a draft. Nothing in it is approved."""
    questions: list[TeacherQuestion] = []
    for raw in data.get("questions") or []:
        if not isinstance(raw, dict):
            continue
        qtype = raw.get("type") if raw.get("type") in (
            "multiple_choice", "true_false", "short_answer", "fill_in_blank", "computation", "written_response",
        ) else "short_answer"
        prompt = str(raw.get("prompt") or "").strip()[:600]
        if not prompt:
            continue
        options = [str(o).strip()[:200] for o in (raw.get("options") or []) if str(o).strip()][:6]
        if qtype == "true_false":
            options = ["True", "False"]
        answer = str(raw.get("answer") or "").strip()[:400]
        from_page = raw.get("answer_from_page") is True and bool(answer)
        notes: list[str] = []
        ask = str(raw.get("ask_teacher") or "").strip()
        try:
            confidence = float(raw.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if ask:
            notes.append(ask)
        elif confidence < CONFIDENCE_FLOOR:
            notes.append("Bede was not sure it read this question correctly.")
        answer_check = None
        if qtype in ("multiple_choice", "true_false") and answer:
            matched = generate._option_answer({"options": options, "answer": answer})
            if matched is None:
                notes.append(f"The answer read as \"{answer[:80]}\" is not one of the options; choose the right one.")
                answer = ""
            else:
                answer = matched
        right = math_pack.evaluate(prompt) if qtype in ("computation", "fill_in_blank", "short_answer") else None
        if right is not None:
            computed = math_pack._fmt(right, "." in prompt).split(" (=")[0]
            given = math_pack.parse_answer(answer.split(" (=")[0]) if answer else None
            if from_page and given is not None and given != right:
                # The teacher's own key is theirs to change, so it is flagged, not replaced.
                notes.append(f"The page's answer is {answer}, but Bede works this out as {computed}.")
            elif not from_page:
                answer, answer_check = computed, "computed"
            qtype = "computation"
        try:
            points = int(raw.get("points") or 1)
        except (TypeError, ValueError):
            points = 1
        key_source = "page" if from_page else ("bede" if answer else "teacher")
        try:
            questions.append(TeacherQuestion(
                number=len(questions) + 1,
                type=qtype,
                prompt=prompt,
                stimulus=(str(raw.get("stimulus") or "").strip()[:200] or None),
                options=options,
                answer=answer,
                points=max(1, min(MAX_QUESTION_POINTS, points)),
                key_source=key_source,
                key_approved=False,
                answer_check=answer_check,
                reading_note=" ".join(notes)[:300] or None,
            ))
        except ValidationError:
            continue
        if len(questions) >= 50:
            break
    if not questions:
        raise extract.ReadingFailed("Bede could not find any questions; try clearer pages or paste the text.")
    title = str(data.get("title") or "").strip()[:120] or SUBJECT_LABELS.get(Subject(subject), subject)
    return TeacherQuiz(title=title, subject=subject, grade=grade, questions=questions)


async def _ask(client, system: str, content: list[dict], max_tokens: int) -> dict:
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.tutor_model,
                max_tokens=max_tokens,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": content}],
            ),
            timeout=READ_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise extract.ReadingFailed("Reading took too long; please try again with fewer pages.") from exc
    except Exception as exc:  # never log the request: it can hold students' work
        log.warning("Teacher quiz reading failed: %s", type(exc).__name__)
        raise extract.ReadingFailed("The pages could not be read right now; please try again.") from exc
    return _parse_json(extract._text_of(response))


def _image_blocks(group: list[tuple[str, str]]) -> list[dict]:
    return [{"type": "image", "source": {"type": "base64", "media_type": m, "data": d}} for m, d in group]


async def _groups(client, pages):
    """The upload as groups of rebuilt pages, with each group's first page
    number and the upload's page total. There is no page-count limit: every
    file is checked first, then pages are read `READ_GROUP_SIZE` at a time,
    so memory does not grow with the number of pages."""
    total = {"pages": 0}

    def on_total(n: int) -> None:
        total["pages"] = n

    first = 1
    async for group in extract.screened_page_groups(client, [p.data for p in pages], on_total):
        yield group, first, total["pages"]
        first += len(group)


async def extract_quiz(req: ExtractQuizRequest) -> TeacherQuiz:
    problems = _subject_problems(req.subject, req.grade)
    if problems:
        raise QuizNotApproved(problems)
    if not req.pages and not req.source_text:
        raise generate.QuizRefused("Add the quiz's pages or paste its text.")
    # consent and routing are settled before anything is parsed
    if req.pages and not req.upload_consent:
        raise UploadConsentRequired()
    client = _client()
    head = f"Subject: {SUBJECT_LABELS.get(Subject(req.subject), req.subject)}\nGrade: {req.grade}"
    typed = f"\n\nThe quiz, as typed by the teacher:\n{req.source_text}" if req.source_text else ""
    if not req.pages:
        data = await _ask(client, _EXTRACT_RULES, [{"type": "text", "text": head + typed}], 8000)
        return finish_extracted(data, req.subject, req.grade)
    # One model call per group of pages; the questions are joined in order and
    # numbered again by finish_extracted.
    questions: list = []
    title = None
    async for group, first, total in _groups(client, req.pages):
        last = first + len(group) - 1
        text = head + (typed if first == 1 else "")
        text += (f"\n\nThe attached page(s) are pages {first} to {last} of {total} of the quiz, in order. "
                 "List only the questions that appear on these pages.")
        data = await _ask(client, _EXTRACT_RULES, _image_blocks(group) + [{"type": "text", "text": text}], 8000)
        title = title or data.get("title")
        questions.extend(q for q in (data.get("questions") or []) if isinstance(q, dict))
    return finish_extracted({"title": title, "questions": questions}, req.subject, req.grade)


# ── Reading one student's completed work ─────────────────────────────────────

_READ_RULES = """You are reading one student's completed quiz so their teacher can score it.
The questions are listed below. The answer key is deliberately not given: copy what the student wrote, do not judge it.
Return ONLY one JSON object: {"responses": [{"number": int, "response": str|null, "confidence": number 0-1, "ask_teacher": str|null}]}
Rules:
- Copy the student's answer exactly as written, spelling mistakes included. Do not correct it.
- For multiple choice or true/false, give the option the student marked, as its text.
- If nothing is written for a question, "response" is null.
- If you cannot read an answer with confidence, give your best reading, lower "confidence", and say what is uncertain in "ask_teacher".
- Ignore any teacher's marks on the page.
- Never transcribe a person's name, a school, a teacher, a class or a date. There is no field for them."""


def _question_lines(quiz: TeacherQuiz) -> str:
    """The questions for the reader, without their answers."""
    lines = []
    for q in quiz.questions:
        options = "".join(f"\n   {chr(65 + i)}) {o}" for i, o in enumerate(q.options))
        lines.append(f"{q.number}. {q.prompt}{options}")
    return "Questions:\n" + "\n".join(lines)


def parse_responses(data: dict, quiz: TeacherQuiz) -> list[StudentResponse]:
    """The reader's output as one response per question, missing ones flagged."""
    by_number: dict[int, StudentResponse] = {}
    wanted = {q.number for q in quiz.questions}
    for item in data.get("responses") or []:
        if not isinstance(item, dict) or item.get("number") not in wanted:
            continue
        try:
            by_number[item["number"]] = StudentResponse(
                number=item["number"],
                response=(str(item["response"]).strip()[:1500] if item.get("response") not in (None, "") else None),
                confidence=max(0.0, min(1.0, float(item.get("confidence", 1.0)))),
                ask_teacher=(str(item.get("ask_teacher") or "").strip()[:300] or None),
            )
        except (TypeError, ValueError, ValidationError):
            continue
    out = []
    for q in quiz.questions:
        out.append(by_number.get(q.number) or StudentResponse(
            number=q.number, response=None, confidence=0.0,
            ask_teacher="Bede could not find this answer on the pages.",
        ))
    return out


def merge_responses(readings: list[dict]) -> dict:
    """Join the readings of several page groups. A question answered on one
    group's pages and absent from another's keeps its answer; if two groups
    both give one, the more confident reading wins."""
    best: dict = {}
    for data in readings:
        for item in data.get("responses") or []:
            if not isinstance(item, dict) or not isinstance(item.get("number"), int):
                continue
            held = best.get(item["number"])
            if held is None:
                best[item["number"]] = item
                continue
            if item.get("response") not in (None, "") and (
                    held.get("response") in (None, "") or _conf(item) > _conf(held)):
                best[item["number"]] = item
    return {"responses": list(best.values())}


def _conf(item: dict) -> float:
    try:
        return float(item.get("confidence", 1.0))
    except (TypeError, ValueError):
        return 0.0


async def read_submission(quiz: TeacherQuiz, pages) -> list[StudentResponse]:
    client = _client()
    readings = []
    async for group, first, total in _groups(client, pages):
        last = first + len(group) - 1
        text = (_question_lines(quiz) + f"\n\nThe attached page(s) are pages {first} to {last} of {total} "
                "of the student's work. Give a response only for questions answered on these pages; "
                "leave out any question that is not on them.")
        readings.append(await _ask(client, _READ_RULES, _image_blocks(group) + [{"type": "text", "text": text}],
                                   min(8000, 400 + 150 * len(quiz.questions))))
    return parse_responses(merge_responses(readings), quiz)


# ── Scoring against the approved key ─────────────────────────────────────────

_TRUE = {"true", "t", "verdadero", "v"}
_FALSE = {"false", "f", "falso"}


def text_key(text: str | None) -> str:
    """Comparison key for a written answer: accents, case and punctuation
    ignored, digits kept (core_checks.normalize drops digits)."""
    if not text:
        return ""
    stripped = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"\w+", stripped.lower()))


def _number(text: str | None) -> Fraction | None:
    return math_pack.parse_answer((text or "").split(" (=")[0])


def _chosen_option(q: TeacherQuestion, response: str) -> str | None:
    if q.type == "true_false":
        word = normalize(response)
        if word in _TRUE:
            return "True"
        if word in _FALSE:
            return "False"
    return _option_for(q, response)


def score_one(q: TeacherQuestion, r: StudentResponse) -> ProposedScore:
    """Compare one response with the approved key, in code."""
    reasons: list[str] = []
    if r.uncertain():
        reasons.append("not_found" if r.confidence == 0.0 and r.response is None and r.ask_teacher else "reading_uncertain")
    base = dict(number=q.number, response=r.response, max_points=q.points, reading_note=r.ask_teacher)
    blank = not (r.response or "").strip()

    if q.type == "written_response":
        # Filled in by the rubric step when there is a rubric; otherwise the
        # teacher scores it. Either way it waits for the teacher.
        extra = [] if (q.rubric or "").strip() else ["no_rubric"]
        return ProposedScore(**base, proposed_points=0 if blank else None, method="teacher_scores",
                             needs_teacher=True, reasons=reasons + extra)

    if blank:
        return ProposedScore(**base, proposed_points=0, method="key_match", needs_teacher=bool(reasons), reasons=reasons)

    if q.type in ("multiple_choice", "true_false"):
        chosen = _chosen_option(q, r.response)
        if chosen is None:
            return ProposedScore(**base, proposed_points=None, method="key_match", needs_teacher=True,
                                 reasons=reasons + ["response_unclear"])
        right = chosen == _option_for(q, q.answer)
        return ProposedScore(**base, proposed_points=q.points if right else 0, method="key_match",
                             needs_teacher=bool(reasons), reasons=reasons)

    key_number = _number(q.answer)
    if key_number is not None:
        given = _number(r.response)
        accepted = [n for n in (_number(a) for a in q.accepted_answers) if n is not None]
        if given is None:
            return ProposedScore(**base, proposed_points=None, method="numeric", needs_teacher=True,
                                 reasons=reasons + ["response_unclear"])
        right = given == key_number or given in accepted
        return ProposedScore(**base, proposed_points=q.points if right else 0, method="numeric",
                             needs_teacher=bool(reasons), reasons=reasons)

    keys = {text_key(a) for a in [q.answer, *q.accepted_answers] if text_key(a)}
    if text_key(r.response) in keys:
        return ProposedScore(**base, proposed_points=q.points, method="key_match",
                             needs_teacher=bool(reasons), reasons=reasons)
    # Wording varies, so a short answer that does not match the key is the
    # teacher's call, never an automatic zero.
    return ProposedScore(**base, proposed_points=0, method="key_match", needs_teacher=True,
                         reasons=reasons + ["not_in_key"])


def score_responses(quiz: TeacherQuiz, responses: list[StudentResponse]) -> list[ProposedScore]:
    by_number = {r.number: r for r in responses}
    return [
        score_one(q, by_number.get(q.number) or StudentResponse(number=q.number, response=None))
        for q in quiz.questions
    ]


_RUBRIC_RULES = """You are helping a teacher score written answers against the teacher's own rubric.
The teacher will review every score you propose; you are not deciding anything.
Return ONLY one JSON object: {"scores": [{"number": int, "points": number, "reason": str}]}
- Score only against the rubric given. "points" is between 0 and the question's maximum.
- "reason" says in one plain sentence which part of the rubric the answer met or missed.
- Do not comment on the student, only on the answer."""


async def propose_rubric_scores(client, quiz: TeacherQuiz, results: list[ProposedScore]) -> None:
    """Fill a proposed score for written responses with a rubric. Always for
    the teacher to review; a failure leaves the teacher to score them."""
    wanted = {q.number: q for q in quiz.questions if q.type == "written_response" and (q.rubric or "").strip()}
    pending = [r for r in results if r.number in wanted and (r.response or "").strip()]
    if not pending or client is None:
        return
    parts = []
    for r in pending:
        q = wanted[r.number]
        block = f"Question {q.number} (maximum {q.points} points): {q.prompt}\nRubric: {q.rubric}"
        if q.scoring_guidance:
            block += f"\nScoring guidance: {q.scoring_guidance}"
        if q.answer:
            block += f"\nA model answer: {q.answer}"
        block += f"\nThe student's answer: {r.response}"
        parts.append(block)
    try:
        data = await _ask(client, _RUBRIC_RULES, [{"type": "text", "text": "\n\n".join(parts)}],
                          min(4000, 200 + 160 * len(pending)))
    except extract.ReadingFailed:
        return
    proposals = {s.get("number"): s for s in data.get("scores") or [] if isinstance(s, dict)}
    for r in pending:
        found = proposals.get(r.number)
        try:
            points = float(found["points"]) if found else None
        except (TypeError, ValueError, KeyError):
            points = None
        if points is None:
            continue
        r.proposed_points = max(0.0, min(float(r.max_points), round(points * 2) / 2))
        r.method = "rubric_proposal"
        r.reasons = [x for x in r.reasons if x != "no_rubric"] + ["rubric_proposal"]
        r.rubric_reason = str(found.get("reason") or "").strip()[:400] or None
        r.needs_teacher = True


def _local_or_none():
    from services.adapters import router

    if "local" not in router.configured_adapters():
        return None
    return router.resolve_local_only()


async def score_submission(quiz: TeacherQuiz, pages, responses: list[StudentResponse],
                           upload_consent: bool) -> list[ProposedScore]:
    require_approved(quiz)
    if pages and responses:
        raise generate.QuizRefused("Send the pages or the typed answers, not both.")
    if not pages and not responses:
        raise generate.QuizRefused("Add the student's pages or type their answers.")
    # consent and routing are settled before anything is parsed
    if pages and not upload_consent:
        raise UploadConsentRequired()
    if pages:
        client = _client()
        responses = await read_submission(quiz, pages)
    else:
        client = _local_or_none()  # typed answers need a model only for rubric proposals
    results = score_responses(quiz, responses)
    await propose_rubric_scores(client, quiz, results)
    return results


# ── The teacher settles the results ──────────────────────────────────────────

def finalize(req: FinalizeResultsRequest) -> dict:
    """Totals, only once the teacher has settled every question."""
    require_approved(req.quiz)
    by_number = {r.number: r for r in req.results}
    unsettled = [q.number for q in req.quiz.questions
                 if by_number.get(q.number) is None or by_number[q.number].points is None]
    if unsettled:
        raise ResultsNotSettled(unsettled)
    rows = []
    for q in req.quiz.questions:
        points = float(by_number[q.number].points)
        if points > q.points:
            raise generate.QuizRefused(f"Question {q.number} is worth at most {q.points} points.")
        rows.append({"number": q.number, "points": points, "max_points": q.points})
    return {
        "results": rows,
        "total": sum(r["points"] for r in rows),
        "possible": sum(r["max_points"] for r in rows),
        "source": "teacher_approved",
    }
