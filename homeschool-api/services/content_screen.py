"""Check every uploaded picture is fit for a school before Bede uses it for teaching.

**Checked before instructional analysis is not "never processed".** The check
is itself a model call: to judge a picture, the checker has to see it. What
this guarantees is order and outcome: a refused picture never reaches the
reading, drafting, scoring or tutoring call that would use it for teaching,
and nothing from it is kept. Where the check runs is stated below.

Two places take a picture from a person and hand it to a model:

* **Practice Coach and quiz uploads** (services/practice/): photographed or
  scanned worksheets, quizzes, exams and source pages, from a parent, a
  teacher, or a demo visitor. Each group of pages is checked here before it is
  read (`services/practice/extract.screened_page_groups`).
* **A lesson photo or drawing in the chat** (routers/tutor.py): a child's
  drawing from the canvas, or a photo attached to a lesson. Checked before the
  turn reaches the tutor.

What is refused (the categories below): self-harm or suicide, sexual content
or nudity, graphic violence or gore, illicit material (drugs, weapons, crime), anything else rated
for adults (profanity, hate symbols, alcohol, tobacco, gambling), and, for a
worksheet upload, a picture that is not school material at all. Ordinary school
material is allowed even when its subject is hard: a history page about a war,
a science diagram of the body's organs, a famous painting in an art lesson.
Every rule applies in any style: a photo, a drawing, a cartoon, an animation
frame or a sticker is judged by what it shows.

**Self-harm and sexual content are safeguarding signals, not only unsafe
pictures** (owner rulings 2026-11-11). A lesson picture showing either takes
the chat's crisis path (routers/tutor.py: the safeguarding response,
`AuditEvent.SAFEGUARDING` and an immediate email to the parent), the same as a
child writing about self-harm. A child sending a sexual picture can be a sign
of harm being done to them, so it is not left to the three-in-ten-minutes
anomaly rule the other categories use.

**It fails closed.** A check that errors, times out, or answers anything but
the expected verdict refuses the picture (`ScreeningUnavailable`). A safety
check that lets a picture through because it could not ask is
indistinguishable from one that looked and found nothing wrong.

**Where the check runs.** It uses the same client that would use the picture
next, so it adds no new provider:

* an upload (worksheet, quiz source, teacher quiz or student work): the
  household's or school's own local model, or the one cloud provider the
  parent ticked by name, with no failover (teacher uploads are local only);
* a lesson photo or drawing: the tutor's own client, which is the provider
  that answers the lesson, including its configured backup if the first
  provider errors, exactly as the lesson turn itself would be routed. On the
  public demo that is OpenAI, with Mistral or Claude as backup.

Nothing is stored. The picture is never logged, and neither is the model's
reply; only the refusal category is recorded (`AuditEvent.UPLOAD_REFUSED`).

**Off-topic is not harmful.** `not_schoolwork` (a game screenshot, a selfie,
a meme) is refused with a plain message and is not audited or alerted. The
unsafe categories are audited. Only `CRISIS_CATEGORIES` (possible self-harm
or sexual content in a child's lesson) raise a safeguarding concern, routed by
services/safeguarding_alerts.py, and worded as a possible concern, never as a
fact about the child.

**It is a model's judgment, not a guarantee.** A classifier can be wrong in
either direction. It is one layer: the file is still validated and rebuilt
(services/practice/upload_safety.py), and the tutor still answers under the
constitution.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextvars import ContextVar
from typing import Literal

from fastapi import Request

from core.config import settings

log = logging.getLogger(__name__)

SCREEN_TIMEOUT_SECONDS = 45

# The unsafe categories. "not_schoolwork" is separate: it is refused for a
# worksheet upload but is not a safety matter, so it is not audited as one.
UNSAFE_CATEGORIES = ("self_harm", "sexual_content", "graphic_violence", "illicit", "mature")
# Refused AND treated as a safeguarding signal in a child's lesson. The label
# is what the parent's alert email and the safeguarding audit entry say.
CRISIS_LABELS = {"self_harm": "self-harm", "sexual_content": "sexual content"}
CRISIS_CATEGORIES = tuple(CRISIS_LABELS)
REFUSAL_CATEGORIES = UNSAFE_CATEGORIES + ("not_schoolwork",)

Context = Literal["worksheet", "lesson"]


class ContentRefused(ValueError):
    """The picture is not allowed. `category` is one of REFUSAL_CATEGORIES."""

    def __init__(self, category: str, context: Context):
        self.category = category
        self.context = context
        super().__init__(refusal_message(category, context))

    @property
    def unsafe(self) -> bool:
        return self.category in UNSAFE_CATEGORIES

    @property
    def crisis(self) -> bool:
        return self.category in CRISIS_CATEGORIES


class ScreeningUnavailable(Exception):
    """The check could not run, so the picture is refused, never read."""


_SHARED_RULES = """You check pictures before a K-8 school app uses them. Look at every picture.
Judge what a picture shows in any style: a photo, a drawing, a cartoon, an animation frame,
a sticker or a meme is refused for the same things a photo would be.
Refuse if ANY picture shows:
- self_harm: self-harm or suicide, shown or encouraged: cutting, hanging, overdosing, jumping,
  starving or hurting oneself, or a person (or cartoon character) planning or doing it
- sexual_content: sexual content, nudity, or sexualised poses (a labelled diagram of organs or bones in a science lesson is fine)
- graphic_violence: gore, blood, injury, torture, or a weapon used against a person, shown graphically (a history page that tells of a battle, or a famous painting of one, is fine)
- illicit: drugs or drug use, weapons for sale, instructions for a crime, or other illegal activity
- mature: anything else rated for adults: profanity, hate symbols or slurs, alcohol, tobacco or vaping, gambling
"""

_WORKSHEET_RULES = _SHARED_RULES + """- not_schoolwork: anything that is not school material. School material is a quiz, test, exam,
  worksheet, homework, answer key, textbook or book page, study notes, or a student's written or drawn work.
  Photos of people, selfies, screenshots of games, videos or social media, memes and unrelated objects are not.
"""

_LESSON_RULES = _SHARED_RULES + """- not_schoolwork: only something plainly unrelated to learning, such as a screenshot of a game,
  video or social media, or a meme. A child's drawing or writing, a book page, a pet, a plant, a craft,
  an experiment, an object or a place is fine.
"""

_ANSWER = """Reply with ONLY one JSON object and nothing else:
{"verdict": "ok"} if every picture is fine, or
{"verdict": "refuse", "category": "<one of the categories above>"} naming the most serious problem."""


def _rules(context: Context) -> str:
    return (_WORKSHEET_RULES if context == "worksheet" else _LESSON_RULES) + "\n" + _ANSWER


_MESSAGES = {
    "worksheet": {
        "not_schoolwork": ("This upload doesn't look like schoolwork, so it was not used. "
                           "Upload quizzes, worksheets, tests or book pages."),
        "unsafe": ("This upload can't be used. Bede's safety check flagged content that isn't "
                   "appropriate for school, so the pages were not used and were not kept."),
        "self_harm": ("This upload can't be used. Bede's safety check flagged it as possibly showing "
                      "self-harm, so the pages were not used and were not kept. If you think a child "
                      "may be at risk, please talk with them and get help from a professional."),
    },
    "lesson": {
        "not_schoolwork": "Bede can only use pictures that are part of your lesson.",
        "unsafe": "Bede can't use that picture in the lesson. Let's keep going.",
    },
}

_LESSON_MESSAGES_ES = {
    "not_schoolwork": "Bede solo puede usar imágenes que sean parte de tu lección.",
    "unsafe": "Bede no puede usar esa imagen en la lección. Sigamos.",
    "unavailable": "Bede no pudo revisar esa imagen ahora, así que no se usó. Inténtalo de nuevo.",
}


def refusal_message(category: str, context: Context, locale: str = "en") -> str:
    """For a lesson, a crisis-category refusal is answered with the
    safeguarding response instead (routers/tutor.py), never with this text."""
    if context == "worksheet" and category == "self_harm":
        return _MESSAGES["worksheet"]["self_harm"]
    kind = "not_schoolwork" if category == "not_schoolwork" else "unsafe"
    if context == "lesson" and locale == "es":
        return _LESSON_MESSAGES_ES[kind]
    return _MESSAGES[context][kind]


def unavailable_message(context: Context, locale: str = "en") -> str:
    if context == "lesson":
        if locale == "es":
            return _LESSON_MESSAGES_ES["unavailable"]
        return "Bede couldn't check that picture just now, so it wasn't used. Please try sending it again."
    return "The pages couldn't be checked just now, so they weren't used. Please try again."


_SNIFF = (("/9j/", "image/jpeg"), ("iVBOR", "image/png"), ("UklGR", "image/webp"))


def media_type_of(image_b64: str, default: str = "image/png") -> str:
    """The picture's real type from its first bytes. A lesson photo arrives
    as bare base64 with no type, and may be a JPEG or WebP."""
    for prefix, media in _SNIFF:
        if image_b64.startswith(prefix):
            return media
    return default


def _text_of(response) -> str:
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


_OBJECT = re.compile(r"\{[^{}]*\}")


def parse_verdict(text: str) -> str | None:
    """None when every picture is fine, else the refusal category.

    Anything that is not exactly one of the two expected shapes raises
    ScreeningUnavailable: an unclear answer refuses, it never passes.
    """
    found = _OBJECT.findall(text or "")
    if len(found) != 1:
        raise ScreeningUnavailable("unexpected reply")
    try:
        data = json.loads(found[0])
    except ValueError as exc:
        raise ScreeningUnavailable("unexpected reply") from exc
    if not isinstance(data, dict):
        raise ScreeningUnavailable("unexpected reply")
    verdict = data.get("verdict")
    if verdict == "ok" and set(data) == {"verdict"}:
        return None
    if verdict == "refuse":
        category = data.get("category")
        if category in REFUSAL_CATEGORIES:
            return category
    raise ScreeningUnavailable("unexpected reply")


async def screen_images(client, images: list[tuple[str, str]], context: Context) -> None:
    """Raise ContentRefused or ScreeningUnavailable unless every picture is fine.

    `images` is (media_type, base64 data) pairs, the shape every upload path
    already sends. The pictures go to `client`, the same one that would read
    them next.
    """
    if not images:
        return
    blocks = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": d}} for m, d in images]
    blocks.append({"type": "text", "text": "Check these pictures."})
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.tutor_model,
                max_tokens=60,
                system=_rules(context),
                messages=[{"role": "user", "content": blocks}],
            ),
            timeout=SCREEN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise ScreeningUnavailable("timeout") from exc
    except Exception as exc:  # never log the request: it holds the pictures
        log.warning("Upload content check failed: %s", type(exc).__name__)
        raise ScreeningUnavailable(type(exc).__name__) from exc
    category = parse_verdict(_text_of(response))
    if category is not None:
        raise ContentRefused(category, context)


# ── Audit ─────────────────────────────────────────────────────────────────────
# The practice routes do not pass their request down to where pages are read,
# so the router binds who is asking here (an async dependency, which runs in
# the request's own context) and a refusal is audited with it.

_request_audit: ContextVar[dict | None] = ContextVar("upload_request_audit", default=None)


async def bind_request(request: Request) -> None:
    from core.audit import audit_from_request

    _request_audit.set(audit_from_request(request))


def record_refusal(exc: ContentRefused, audit: dict | None = None, **who) -> None:
    """Audit an unsafe refusal: the category only, never the picture or reply.

    `audit` is the request's ip/user-agent; without it, the ones bound by
    `bind_request` are used. `who` may carry role and student_name.
    """
    if not exc.unsafe:
        return
    from core.audit import AuditEvent, log_event_nowait

    fields = audit if audit is not None else (_request_audit.get() or {})
    try:
        log_event_nowait(
            AuditEvent.UPLOAD_REFUSED,
            success=False,
            detail=f"category={exc.category} surface={exc.context}",
            **fields,
            **who,
        )
    except RuntimeError:  # no running loop (a synchronous test); the refusal still stands
        log.info("Upload refused (%s, %s); not audited outside an event loop", exc.category, exc.context)
