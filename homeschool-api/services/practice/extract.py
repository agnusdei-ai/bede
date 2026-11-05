"""Read a photographed, graded worksheet into a `GradedAssessment`.

This reuses the image path the handwriting canvas already uses: the page goes
to the model as a base64 `{"type": "image", ...}` block (see
services/ai_service.py's "Multimodal turn"), which the OpenAI-compatible
adapter translates for OpenAI, Mistral and local servers. Nothing new is
added to the provider layer.

Where it is read (register entry 39, decision 1):

* **local** — the household's own model via `resolve_local_only()`, never
  falling back to a cloud provider. Used by default when a local model is
  configured.
* **cloud** — the household's configured provider, only when the parent
  consents for this upload. Refused before any call is made otherwise.

The photos exist only in this request. They are never written to the
database, a file, or a log, and the result carries no field that could hold
a name, school, teacher or date (models/practice.py).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging

from pydantic import ValidationError

from core.config import settings
from models.practice import (
    MAX_ITEMS_PER_SECTION,
    MAX_SECTIONS,
    MAX_WORD_BANK,
    AssessmentItem,
    AssessmentSection,
    GradedAssessment,
    ReadPhotosRequest,
)
from services.practice import diagrams
from services.practice.packs import get_pack, subject_name
from services.practice.upload_safety import (  # noqa: F401  re-exported for the router
    PhotoRejected,
    ScannerUnavailable,
    UploadBusy,
    enhance_group,
    page_groups,
    prepare_pages,
)

log = logging.getLogger(__name__)

READ_TIMEOUT_SECONDS = 120


class ConsentRequired(Exception):
    def __init__(self, provider: str | None):
        self.provider = provider
        super().__init__(provider or "none")


class ReadingUnavailable(Exception):
    pass


class ReadingFailed(Exception):
    pass


def _cloud_name(configured: list[str] | None = None) -> str | None:
    """The cloud provider a consent tick names: the first cloud adapter in
    the live order, honouring a parent's primary/secondary override
    (core/provider_state.py), so the tick names where the request really goes."""
    from core import provider_state
    from services.adapters import router

    configured = router.configured_adapters() if configured is None else configured
    order = provider_state.effective_order([a for a in router.preference_order() if a in configured])
    return next((a for a in order if a != "local"), None)


def _named_client(provider: str):
    """Pinned to the provider the parent agreed to: no failover to another."""
    from services.adapters import router

    try:
        return router.resolve_named(provider)
    except router.NamedAdapterUnavailableError as exc:
        raise ReadingUnavailable("No AI provider is configured for this.") from exc


def reading_route() -> dict:
    """What the parent is told before uploading: where pages would be read.

    `cloud_provider` is for photos and stays withheld while cloud reading is
    switched off, so the screen never offers a consent tick for a route the
    server will refuse. `draft_provider` is for a quiz drafted from typed
    text only (a topic or a pasted quiz, no photos): the same kind of text a
    tutoring turn already sends, so the photo switch does not govern it. It
    still needs the parent's tick for that provider by name.
    """
    from services.adapters import router

    configured = router.configured_adapters()
    cloud = _cloud_name(configured)
    return {
        "local_available": "local" in configured,
        "cloud_provider": cloud if settings.practice_cloud_reading_enabled else None,
        "draft_provider": cloud,
    }


def text_draft_client(req):
    """The client for a quiz drafted from typed text only, never photos.

    Local first. Otherwise the configured cloud provider, with the parent's
    consent for that provider by name, and pinned to it: no failover, since
    the consent named one provider. Photos never come through here.
    """
    from services.adapters import router

    if getattr(req, "pages", None):
        raise ValueError("text_draft_client is for drafts without photos")
    local = "local" in router.configured_adapters()
    chosen = req.route or ("local" if local else "cloud")
    if chosen == "local":
        if not local:
            raise ReadingUnavailable("No local model is configured on this install.")
        return router.resolve_local_only()
    cloud = _cloud_name()
    if not cloud:
        raise ReadingUnavailable("No AI provider is configured to draft quizzes.")
    if not req.cloud_consent:
        raise ConsentRequired(cloud)
    return _named_client(cloud)


def _choose_client(req: ReadPhotosRequest):
    from services.adapters import router

    route = reading_route()
    chosen = req.route or ("local" if route["local_available"] else "cloud")
    if chosen == "local":
        if not route["local_available"]:
            raise ReadingUnavailable("No local model is configured on this install.")
        return router.resolve_local_only()
    if not settings.practice_cloud_reading_enabled:
        raise ReadingUnavailable("Reading photos with a cloud AI provider is turned off on this install.")
    if not route["cloud_provider"]:
        raise ReadingUnavailable("No AI provider is configured to read photos.")
    if not req.cloud_consent:
        raise ConsentRequired(route["cloud_provider"])
    # Photos of a child's work go only to the provider the parent named.
    return _named_client(route["cloud_provider"])


_RULES = """You are reading a photographed, already-graded school worksheet so a parent can review it.
Return ONLY one JSON object, no prose, matching this shape:
{"subject": "<subject>", "sections": [{"label": str, "instructions": str,
  "required_format": "complete_sentence"|"single_word"|"color_fill"|"free"|"unknown",
  "word_bank": [str], "items": [{"number": int, "prompt": str, "stimulus": str|null, "diagram": object|null,
  "student_response": str|null, "teacher_mark": "correct"|"incorrect"|"partial"|"unmarked",
  "teacher_correction": str|null, "confidence": number 0-1, "ask_parent": str|null}]}]}
Rules:
- Photos may be blurry, dark, faint, tilted, upside down or partly cut off, and scans may be poor.
  Read everything you can see anyway. Never refuse, never apologise, and never reply with anything
  but the JSON object. For anything you cannot make out, give your best reading, lower "confidence"
  and say what is unclear in "ask_parent"; the parent checks it.
- Never transcribe a person's name, a school, a teacher, a class, or a date. There is no field for them.
- Copy the child's answers exactly as written. Do not correct them.
- Record the teacher's mark only if you can see one; otherwise "unmarked". Never invent a mark.
- If you cannot read something with confidence, give your best reading, lower "confidence",
  and say what is uncertain in "ask_parent".
- "stimulus" is a few plain words for a picture no diagram fits, naming the things in it (e.g. "dog running", "3 apples"). Bede draws those things from its list, so name them simply.
- "diagram" is null unless the question's picture can be given as one of these, with its exact numbers and words:
""" + diagrams.PROMPT_SCHEMA + """
  This is for any subject: an animal to name, a timeline, the water cycle, a table, a shape, things on a
  ruler, coins, a thermometer. Prefer a diagram whenever one fits, so the picture is drawn rather than
  described: when the answer choices are pictures, give a "pictures" diagram with one group per choice,
  labelled as the page labels them (A, B, C), using the nearest ICON. Count parts,
  dots, blocks and tick marks carefully; if you are unsure, lower "confidence" and say so in "ask_parent".
  Any other picture (a photograph, a map, a drawing none of these fits) goes in "stimulus" only."""


def _prompt(subject: str) -> str:
    pack = get_pack(subject)
    hints = pack.extract_hints if pack else ""
    name = subject_name(subject)
    return f"{_RULES}\n\nSubject: {name}\n\n{hints}".strip()


def _text_of(response) -> str:
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


_NOT_READ = "The pages could not be read; check each page is the right way up and fully in the photo, then try again."
# Every key the reading may carry. Anything else (a name, a school, a date)
# refuses the whole reading, so it is never stored.
_TOP_KEYS = set(GradedAssessment.model_fields)
_SECTION_KEYS = set(AssessmentSection.model_fields)
_ITEM_KEYS = set(AssessmentItem.model_fields)
_MARKS = {"correct", "incorrect", "partial", "unmarked"}
_FORMATS = {"complete_sentence", "single_word", "color_fill", "free", "unknown"}
# A repaired item is shown to the parent to check, like any unsure reading.
_REPAIRED_CONFIDENCE = 0.5


def _close_json(raw: str) -> str | None:
    """A reply cut off part-way, closed after its last complete value.

    Long or hard pages can end a reply mid-item. Everything up to the last
    complete object or list is kept and the open brackets are closed, so the
    questions that were read are not lost with the one that was not.
    """
    stack: list[str] = []
    in_string = escaped = False
    last_cut, last_stack = None, None
    for i, ch in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack:
                return None
            stack.pop()
            last_cut, last_stack = i + 1, list(stack)
    if last_cut is None:
        return None
    return raw[:last_cut] + "".join(reversed(last_stack))


def _load_object(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    start = raw.find("{")
    if start < 0:
        raise ValueError("no object")
    raw = raw[start:]
    for candidate in (raw, raw[: raw.rfind("}") + 1], _close_json(raw)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("no readable object")


def _has_unknown_keys(data: dict) -> bool:
    if set(data) - _TOP_KEYS:
        return True
    for section in data.get("sections") or []:
        if isinstance(section, dict):
            if set(section) - _SECTION_KEYS:
                return True
            for item in section.get("items") or []:
                if isinstance(item, dict) and set(item) - _ITEM_KEYS:
                    return True
    return False


def _text(value, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()[:limit]
    return text or None


def _repair_item(raw: dict, fallback_number: int) -> AssessmentItem | None:
    try:
        return AssessmentItem.model_validate(raw)
    except ValidationError:
        pass
    try:
        number = int(raw.get("number"))
    except (TypeError, ValueError):
        number = fallback_number
    try:
        confidence = float(raw.get("confidence", _REPAIRED_CONFIDENCE))
    except (TypeError, ValueError):
        confidence = _REPAIRED_CONFIDENCE
    stimulus = _text(raw.get("stimulus"), 200)
    fixed = {
        "number": min(500, max(1, number)),
        "prompt": _text(raw.get("prompt"), 300) or stimulus or f"Question {fallback_number}",
        "stimulus": stimulus,
        "diagram": raw.get("diagram"),
        "student_response": _text(raw.get("student_response"), 200),
        "teacher_mark": raw.get("teacher_mark") if raw.get("teacher_mark") in _MARKS else "unmarked",
        "teacher_correction": _text(raw.get("teacher_correction"), 200),
        "confidence": min(_REPAIRED_CONFIDENCE, max(0.0, confidence)),
        "ask_parent": _text(raw.get("ask_parent"), 200) or "Bede was not sure it read this question correctly.",
    }
    for attempt in (fixed, {**fixed, "diagram": None}):
        try:
            return AssessmentItem.model_validate(attempt)
        except ValidationError:
            continue
    return None


def _salvage(data: dict, subject: str) -> GradedAssessment | None:
    """Keep every question that can be read; mark repaired ones for the parent."""
    sections: list[AssessmentSection] = []
    for s_index, raw in enumerate(data.get("sections") or [], start=1):
        if not isinstance(raw, dict):
            continue
        items = [it for n, r in enumerate(raw.get("items") or [], start=1)
                 if isinstance(r, dict) and (it := _repair_item(r, n)) is not None]
        if not items:
            continue
        bank = [w for w in (_text(w, 40) for w in (raw.get("word_bank") or [])
                            if isinstance(w, (str, int, float))) if w]
        try:
            sections.append(AssessmentSection(
                label=_text(raw.get("label"), 60) or f"Part {s_index}",
                instructions=_text(raw.get("instructions"), 500) or "",
                required_format=raw.get("required_format") if raw.get("required_format") in _FORMATS else "unknown",
                word_bank=list(dict.fromkeys(bank))[:MAX_WORD_BANK],
                items=items[:MAX_ITEMS_PER_SECTION],
            ))
        except ValidationError:
            continue
    if not sections:
        return None
    return GradedAssessment(subject=subject, sections=sections[:MAX_SECTIONS])


def parse_reading(text: str, subject: str) -> GradedAssessment:
    """The reader's reply as a worksheet, repaired rather than thrown away.

    A reply wrapped in prose, cut off part-way, or with one bad field keeps
    every question that can be read; anything repaired is marked for the
    parent to check. A reply carrying a field the worksheet has no place for
    (a name, a school, a date) is still refused whole, so it is never stored.
    """
    try:
        data = _load_object(text)
    except ValueError as exc:
        raise ReadingFailed(_NOT_READ) from exc
    data["subject"] = subject
    if _has_unknown_keys(data):
        raise ReadingFailed(_NOT_READ)
    try:
        return GradedAssessment.model_validate(data)
    except ValidationError:
        pass
    repaired = _salvage(data, subject)
    if repaired is None:
        raise ReadingFailed(_NOT_READ)
    return repaired


def merge_readings(first: GradedAssessment, more: GradedAssessment) -> GradedAssessment:
    """One worksheet read in parts -> one assessment, in page order.

    A section that runs across a group boundary arrives as two halves with the
    same label; they are joined back into one, so the parent sees the
    worksheet's own sections rather than one per group of pages.
    """
    sections = [s.model_copy(deep=True) for s in first.sections]
    for section in more.sections:
        last = sections[-1] if sections else None
        if (last is not None and last.label == section.label
                and len(last.items) + len(section.items) <= MAX_ITEMS_PER_SECTION):
            last.items.extend(section.items)
            last.word_bank.extend(w for w in section.word_bank if w not in last.word_bank)
            if not last.instructions:
                last.instructions = section.instructions
        else:
            sections.append(section.model_copy(deep=True))
    if len(sections) > MAX_SECTIONS:
        raise ReadingFailed("This worksheet has more sections than can be shown at once; please send it in two parts.")
    return GradedAssessment(subject=first.subject, sections=sections)


_SECOND_LOOK = ("These pages were hard to read the first time, so they have been sharpened. "
                "Read every question you can see, give your best reading of anything unclear "
                "with a low confidence, and reply only with the JSON object.")


async def _ask_reader(client, subject: str, pages: list[tuple[str, str]], note: str) -> str:
    blocks = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": d}} for m, d in pages]
    blocks.append({"type": "text", "text": note})
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.tutor_model,
                max_tokens=8000,
                temperature=0,
                system=_prompt(subject),
                messages=[{"role": "user", "content": blocks}],
            ),
            timeout=READ_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise ReadingFailed("Reading the pages took too long; please try again.") from exc
    except Exception as exc:  # provider errors: never log the request, it holds the photos
        log.warning("Practice page reading failed: %s", type(exc).__name__)
        raise ReadingFailed("The pages could not be read right now; please try again.") from exc
    return _text_of(response)


async def _read_group(client, subject: str, pages: list[tuple[str, str]], first_page: int,
                      before_call=None) -> GradedAssessment:
    """One group of pages, read once and, if that fails, once more sharpened.

    The second look sends a contrast-stretched, enlarged, sharpened copy of
    the same pages (upload_safety.enhance_for_reading) with a note to read
    whatever can be seen. It is a second model call, so the demo charges it
    like any other (`before_call`).
    """
    last_page = first_page + len(pages) - 1
    where = f"page {first_page}" if first_page == last_page else f"pages {first_page} to {last_page}"
    note = f"These are {where} of one worksheet, in order."
    try:
        return parse_reading(await _ask_reader(client, subject, pages, note), subject)
    except ReadingFailed as first:
        if first.args and first.args[0] != _NOT_READ:
            raise  # a timeout or provider error: the same call again will not help
    log.info("Practice reading: second look at %s", where)
    if before_call is not None:
        await before_call()
    clearer = await enhance_group(pages)
    return parse_reading(await _ask_reader(client, subject, clearer, f"{note} {_SECOND_LOOK}"), subject)


async def read_pages(req: ReadPhotosRequest, before_call=None,
                     continues: GradedAssessment | None = None) -> GradedAssessment:
    return (await read_pages_counted(req, before_call, continues))[0]


async def read_pages_counted(req: ReadPhotosRequest, before_call=None,
                             continues: GradedAssessment | None = None,
                             report=None) -> tuple[GradedAssessment, int]:
    """Read every uploaded page, READ_GROUP_SIZE pages per model call.

    `before_call` runs before each call (the demo charges its message quota
    there, so a long upload costs what it really uses). `continues` is what an
    earlier part of the same upload already read; this part is added after it.
    """
    if get_pack(req.subject) is None:
        raise PhotoRejected(f"No practice pack for {req.subject!r} yet.")
    client = _choose_client(req)  # consent and routing are settled before anything is parsed
    result = continues
    next_page = req.first_page
    total = {"pages": 0}

    def on_total(n: int) -> None:
        total["pages"] = n
        if report:
            report("reading", 0, n)

    if report:
        report("checking", 0, None)
    async for pages in page_groups([p.data for p in req.pages], on_total=on_total):
        if before_call is not None:
            await before_call()
        part = await _read_group(client, req.subject, pages, next_page, before_call)
        next_page += len(pages)
        if report:
            report("reading", next_page - req.first_page, total["pages"])
        del pages  # this group's images are not needed once it is read
        result = part if result is None else merge_readings(result, part)
    return result, next_page - req.first_page
