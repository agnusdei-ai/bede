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
from models.practice import GradedAssessment, ReadPhotosRequest
from services.practice.packs import get_pack
from services.practice.upload_safety import (  # noqa: F401  re-exported for the router
    PhotoRejected,
    ScannerUnavailable,
    UploadBusy,
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


def reading_route() -> dict:
    """What the parent is told before uploading: where pages would be read."""
    from services.adapters import router

    configured = router.configured_adapters()
    cloud = next((a for a in router.preference_order() if a in configured and a != "local"), None)
    return {
        "local_available": "local" in configured,
        # Withheld while cloud reading is switched off, so the screen never
        # offers a consent tick for a route the server will refuse.
        "cloud_provider": cloud if settings.practice_cloud_reading_enabled else None,
    }


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
    from services.ai_service import _client  # the same client tutoring turns use
    return _client


_RULES = """You are reading a photographed, already-graded school worksheet so a parent can review it.
Return ONLY one JSON object, no prose, matching this shape:
{"subject": "<subject>", "sections": [{"label": str, "instructions": str,
  "required_format": "complete_sentence"|"single_word"|"color_fill"|"free"|"unknown",
  "word_bank": [str], "items": [{"number": int, "prompt": str, "stimulus": str|null,
  "student_response": str|null, "teacher_mark": "correct"|"incorrect"|"partial"|"unmarked",
  "teacher_correction": str|null, "confidence": number 0-1, "ask_parent": str|null}]}]}
Rules:
- Never transcribe a person's name, a school, a teacher, a class, or a date. There is no field for them.
- Copy the child's answers exactly as written. Do not correct them.
- Record the teacher's mark only if you can see one; otherwise "unmarked". Never invent a mark.
- If you cannot read something with confidence, give your best reading, lower "confidence",
  and say what is uncertain in "ask_parent".
- "stimulus" describes a picture briefly in plain English (e.g. "picture: dog running")."""


def _prompt(subject: str) -> str:
    pack = get_pack(subject)
    hints = pack.extract_hints if pack else ""
    return f"{_RULES}\n\nSubject: {subject}\n\n{hints}".strip()


def _text_of(response) -> str:
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


def parse_reading(text: str, subject: str) -> GradedAssessment:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        data["subject"] = subject
        return GradedAssessment.model_validate(data)
    except (ValueError, ValidationError) as exc:
        raise ReadingFailed("The pages could not be read into a worksheet; try clearer photos.") from exc


async def read_pages(req: ReadPhotosRequest) -> GradedAssessment:
    if get_pack(req.subject) is None:
        raise PhotoRejected(f"No practice pack for {req.subject!r} yet.")
    client = _choose_client(req)  # consent and routing are settled before anything is parsed
    pages = await prepare_pages([p.data for p in req.pages])
    blocks = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": d}} for m, d in pages]
    blocks.append({"type": "text", "text": f"These are {len(pages)} page(s) of one worksheet, in order."})
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.tutor_model,
                max_tokens=4000,
                temperature=0,
                system=_prompt(req.subject),
                messages=[{"role": "user", "content": blocks}],
            ),
            timeout=READ_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise ReadingFailed("Reading the pages took too long; please try again.") from exc
    except Exception as exc:  # provider errors: never log the request, it holds the photos
        log.warning("Practice page reading failed: %s", type(exc).__name__)
        raise ReadingFailed("The pages could not be read right now; please try again.") from exc
    return parse_reading(_text_of(response), req.subject)
