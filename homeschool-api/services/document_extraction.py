"""
Plain-text extraction from a narration file a child exported from a smart
pen/notebook app (e.g. inq — https://inq.shop — whose on-device AI already
transcribes handwriting to text/PDF). There's no public inq API/webhook to
integrate against, so the only real integration surface is the file the
family already has: they export it from the app and upload it into a Bede
session (see routers/tutor.py's /tutor/extract-narration), same as any other
attachment. Supports .txt and .pdf only — the two export formats such apps
commonly offer for a transcript.
"""
import base64
import io

from pypdf import PdfReader

# Mirrors TutorRequest.child_message's max_length (models/schemas.py) — the
# extracted text is sent into the normal chat turn alongside/instead of
# whatever the child typed, so it needs to fit that same field rather than
# growing a second, parallel plumbing path through ai_service.py.
MAX_NARRATION_CHARS = 2000

# A narration is a child telling one passage back in their own words, and
# MAX_NARRATION_CHARS above already caps the result at roughly one page of
# text. Parsing more pages than that can ever consume is work done to be
# thrown away, and `routers/tutor.py`'s /tutor/extract-narration is reachable
# by the public demo's anonymous role (`require_auth` admits it) with up to
# ~5.25 MB of attacker-chosen bytes, on a 512 MB Render instance this
# codebase has already recorded being OOM-killed at 642 MB. So the page walk
# is bounded twice, because the two bounds stop different things:
#
#   * Stopping once there is enough text handles the ordinary large upload —
#     it falls out of the output cap rather than being a second arbitrary
#     number, so a real family's export is never truncated differently than
#     it already was.
#   * MAX_PDF_PAGES handles the case the early stop CANNOT: a PDF whose pages
#     yield no text at all. `extract_text()` returns "" for a blank or
#     image-only page, so the accumulated length never grows, the early stop
#     never fires, and a file declaring tens of thousands of empty pages
#     walks every one of them. That is the cheap denial-of-service here, and
#     it is invisible to a bound expressed only in characters.
#
# Not bounded here: a decompression bomb inside a SINGLE page's content
# stream, which is pypdf's own to limit and which neither of these reaches.
MAX_PDF_PAGES = 50


class UnsupportedNarrationFileError(ValueError):
    """Raised for unsafe, unreadable or unsupported narration files."""


# Reject active PDF features before extracting any student-supplied text. This
# structural preflight does not claim to replace a malware-scanning engine.
MAX_PDF_BYTES = 5 * 1024 * 1024
_BLOCKED_PDF_NAMES = (
    b"/JavaScript", b"/JS", b"/OpenAction", b"/AA", b"/Launch",
    b"/EmbeddedFiles", b"/Filespec", b"/RichMedia", b"/XFA",
    b"/AcroForm", b"/SubmitForm", b"/GoToR", b"/URI",
)


def preflight_pdf(raw: bytes) -> PdfReader:
    """Fail closed on malformed, encrypted or active-content PDFs."""
    import re

    if len(raw) > MAX_PDF_BYTES:
        raise UnsupportedNarrationFileError("PDF exceeds the 5 MB limit")
    if not raw.startswith(b"%PDF-"):
        raise UnsupportedNarrationFileError("Invalid PDF file signature")

    # Match PDF name tokens (including #XX escaped names), not free text.
    # Decode name escapes before checking so /Java#53cript cannot evade it.
    names = re.findall(rb"/(?:[A-Za-z0-9#]+)", raw)
    for name in names:
        decoded = re.sub(
            rb"#[0-9A-Fa-f]{2}",
            lambda match: bytes([int(match.group()[1:], 16)]),
            name,
        )
        if decoded in _BLOCKED_PDF_NAMES:
            raise UnsupportedNarrationFileError("PDF contains disallowed active features")

    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise UnsupportedNarrationFileError("Password-protected PDFs are not supported")
        # Reject documents with oversized page trees before text extraction.
        if len(reader.pages) > MAX_PDF_PAGES:
            raise UnsupportedNarrationFileError("PDF has too many pages")
        return reader
    except UnsupportedNarrationFileError:
        raise
    except Exception as exc:
        raise UnsupportedNarrationFileError("PDF failed security validation") from exc



def extract_narration_text(filename: str, content_base64: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("txt", "pdf"):
        raise UnsupportedNarrationFileError("Only .txt or .pdf files are supported")

    try:
        raw = base64.b64decode(content_base64, validate=True)
    except Exception as e:
        raise UnsupportedNarrationFileError("Could not read that file") from e

    if ext == "txt":
        text = raw.decode("utf-8", errors="ignore")
    else:
        try:
            reader = preflight_pdf(raw)
            parts: list[str] = []
            length = 0
            for page in reader.pages[:MAX_PDF_PAGES]:
                extracted = page.extract_text() or ""
                parts.append(extracted)
                length += len(extracted) + 1  # the "\n" join adds one
                if length >= MAX_NARRATION_CHARS:
                    break
            text = "\n".join(parts)
        except Exception as e:
            raise UnsupportedNarrationFileError("Could not read that PDF") from e

    text = text.strip()
    if not text:
        raise UnsupportedNarrationFileError("No text found in that file")
    return text[:MAX_NARRATION_CHARS]
