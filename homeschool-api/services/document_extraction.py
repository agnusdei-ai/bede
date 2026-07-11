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


class UnsupportedNarrationFileError(ValueError):
    """Raised for an unreadable file, wrong extension, or one with no
    extractable text — routers/tutor.py surfaces this as a 400."""


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
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            raise UnsupportedNarrationFileError("Could not read that PDF") from e

    text = text.strip()
    if not text:
        raise UnsupportedNarrationFileError("No text found in that file")
    return text[:MAX_NARRATION_CHARS]
