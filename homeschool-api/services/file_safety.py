"""One gate for every file a person hands Bede.

Bede takes files in five places, and each goes through this module (or, for
Practice Coach, the module it builds on, services/practice/upload_safety.py)
before anything else reads it:

* **Practice Coach, quiz and teacher-quiz pages** (photos and PDFs):
  `upload_safety.page_groups`, which checks, scans and rebuilds every page.
* **A lesson photo or a drawing from the writing pad** (routers/tutor.py):
  `lesson_picture` below.
* **A narration file** (a .txt or .pdf a child exports from a smart-pen app,
  `/tutor/extract-narration`): `narration_file` below, before the text is
  pulled out (services/document_extraction.py keeps its own PDF checks).
* **Voice recordings** (`/voice/*`): `audio` below.

What every file gets, in this order:

1. **Its type from its bytes alone.** A name or a declared type is never
   trusted: a file called ``answer.wav`` that is not a WAV is refused.
2. **A virus scan, when the household runs one.** ``PRACTICE_SCANNER_URL``
   (the name predates this module; it covers every file now) points at a
   LOCAL clamd. When it is set every file is scanned first and an unreachable
   scanner refuses the file (fail closed); a file it recognises is refused,
   recorded as ``AuditEvent.FILE_FLAGGED``, and the parent is emailed at once.
   When it is not set nothing is scanned, and nothing here claims a file is
   free of viruses.
3. **A rebuild, for pictures.** A photo or drawing is fully decoded and
   re-encoded to a fresh PNG (upload_safety.reencode_image): metadata, any
   appended payload and anything not pixels is dropped, so what reaches the
   model is a picture Bede drew itself from the pixels.

This is hardening plus optional detection, never a promise that a file is
virus-free. Nothing here stores, logs or forwards a file or its name.
"""
from __future__ import annotations

import base64
import binascii

from services.practice import upload_safety
from services.practice.upload_safety import (
    PhotoRejected as FileRejected,
    ScannerFlagged,
    ScannerUnavailable,
    UploadBusy,
)

__all__ = [
    "FileRejected", "ScannerFlagged", "ScannerUnavailable", "UploadBusy",
    "lesson_picture", "narration_file", "audio", "scanning_on",
]

# A lesson photo or drawing (TutorRequest.drawing_image is capped at 8 MB of
# base64, about 6 MB of picture).
MAX_PICTURE_BYTES = 6_000_000


def scanning_on() -> bool:
    """Whether a virus scanner is set up for this deployment."""
    return bool((upload_safety.settings.practice_scanner_url or "").strip())


async def scan(raw: bytes) -> None:
    """Scan one file when a scanner is set up; a no-op otherwise."""
    await upload_safety._scan(raw)


async def lesson_picture(image_b64: str) -> str:
    """A lesson photo or drawing, checked, scanned and rebuilt: the base64 PNG
    that may go on to the content check and the tutor. Raises FileRejected
    (including ScannerFlagged), ScannerUnavailable or UploadBusy."""
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FileRejected("The picture did not arrive intact; please try again.") from exc
    if len(raw) > MAX_PICTURE_BYTES:
        raise FileRejected("The picture is too large.")
    if raw.startswith(b"%PDF-"):
        raise FileRejected("A lesson picture must be a photo or a drawing, not a PDF.")
    kind = upload_safety._image_format(raw)
    await scan(raw)
    clean = await upload_safety._bounded(upload_safety.reencode_image, raw, kind)
    return base64.b64encode(clean).decode()


async def narration_file(raw: bytes, ext: str) -> None:
    """Checks a narration file's bytes match its kind and scans it. The text
    itself is pulled out afterwards by services/document_extraction.py."""
    if ext == "pdf" and not raw.startswith(b"%PDF-"):
        raise FileRejected("That file is not a PDF.")
    if ext == "txt":
        if raw.startswith((b"%PDF-", b"MZ", b"\x7fELF", b"PK\x03\x04")) or b"\x00" in raw[:4096]:
            raise FileRejected("That file is not plain text.")
    await scan(raw)


def audio_kind(raw: bytes) -> str | None:
    """The audio format, from the bytes alone, or None."""
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        return "wav"
    if raw[:4] == b"OggS":
        return "ogg"
    if raw[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if raw[:3] == b"ID3" or (len(raw) > 1 and raw[0] == 0xFF and raw[1] & 0xE0 == 0xE0):
        return "mp3"
    if raw[4:8] == b"ftyp":
        return "mp4"
    return None


# Leading bytes of files that are never sound: a program, an archive, a
# document. Raw sound samples (below) have no header of their own, so these
# are what a streamed piece of a recording must not start with.
NOT_SOUND = (b"MZ", b"\x7fELF", b"PK\x03\x04", b"%PDF-", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe",
             b"\xfe\xed\xfa", b"#!", b"<", b"Rar!", b"7z\xbc\xaf", b"\x1f\x8b", b"BZh", b"\xfd7zXZ")


def _looks_like_text(raw: bytes) -> bool:
    """True when the start is all readable text. Sound samples never are:
    quiet speech and silence are full of small values (bytes 0 to 8)."""
    head = raw[:512]
    return len(head) >= 8 and all(32 <= b < 127 or b in (9, 10, 13) for b in head)


async def audio(raw: bytes, *, raw_samples: bool = False) -> None:
    """Checks a voice recording is audio by its bytes and scans it.

    ``raw_samples`` is for a streamed piece of a recording
    (``/voice/stream/{id}/chunk``): the app sends the sound samples alone,
    16-bit, with no file header (services/streaming_transcription.py wraps
    them), so such a piece is accepted when it is a whole number of samples
    and does not start like another kind of file. Everything else must be a
    recognised audio file."""
    if audio_kind(raw) is None:
        if not raw_samples or len(raw) % 2 or raw.startswith(NOT_SOUND) or _looks_like_text(raw):
            raise FileRejected("Only audio recordings are accepted.")
    await scan(raw)
