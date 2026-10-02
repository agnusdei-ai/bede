"""
Tests for pulling narration text out of a file a child exported from a smart
pen/notebook app (e.g. inq — https://inq.shop) — see
services/document_extraction.py and routers/tutor.py's /tutor/extract-narration.
"""
import base64
import io

import pytest

from services import document_extraction
from services.document_extraction import (
    extract_narration_text,
    MAX_NARRATION_CHARS,
    MAX_PDF_PAGES,
    UnsupportedNarrationFileError,
)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _build_minimal_pdf(text: str) -> bytes:
    """Hand-crafted, minimal-but-valid single-page PDF with a real xref
    table (pypdf requires one to parse without warnings) — good enough to
    exercise extract_narration_text's PDF path without a heavyweight
    PDF-generation dependency like reportlab."""
    content = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 200 200] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_offset = out.tell()
    n = len(objects) + 1
    out.write(f"xref\n0 {n}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(b"trailer\n")
    out.write(f"<< /Size {n} /Root 1 0 R >>\n".encode())
    out.write(b"startxref\n")
    out.write(f"{xref_offset}\n".encode())
    out.write(b"%%EOF")
    return out.getvalue()


def test_extracts_plain_text_from_a_txt_file():
    text = extract_narration_text("narration.txt", _b64(b"Water freezes at zero degrees."))
    assert text == "Water freezes at zero degrees."


def test_extracts_text_from_a_pdf_file():
    pdf_bytes = _build_minimal_pdf("Hello narration")
    text = extract_narration_text("narration.pdf", _b64(pdf_bytes))
    assert "Hello narration" in text


def test_filename_extension_check_is_case_insensitive():
    text = extract_narration_text("Narration.TXT", _b64(b"Grade 4 nature walk notes"))
    assert text == "Grade 4 nature walk notes"


def test_rejects_an_unsupported_extension():
    with pytest.raises(UnsupportedNarrationFileError):
        extract_narration_text("narration.docx", _b64(b"whatever"))


def test_rejects_a_filename_with_no_extension():
    with pytest.raises(UnsupportedNarrationFileError):
        extract_narration_text("narration", _b64(b"whatever"))


def test_rejects_invalid_base64():
    with pytest.raises(UnsupportedNarrationFileError):
        extract_narration_text("narration.txt", "not-valid-base64!!!")


def test_rejects_a_pdf_with_no_extractable_text():
    # A blank-page PDF (no content stream) has nothing to extract.
    blank = _build_minimal_pdf("")
    with pytest.raises(UnsupportedNarrationFileError):
        extract_narration_text("narration.pdf", _b64(blank))


def test_truncates_to_the_child_message_length_cap():
    long_text = "a" * (MAX_NARRATION_CHARS + 500)
    text = extract_narration_text("narration.txt", _b64(long_text.encode()))
    assert len(text) == MAX_NARRATION_CHARS


# ───────────────────────────────────────────────────────────────────────────
# Bounding the page walk.
#
# /tutor/extract-narration is reachable by the public demo's anonymous role
# (`require_auth` admits it) with up to ~5.25 MB of attacker-chosen bytes, on
# a 512 MB instance this codebase has already recorded being OOM-killed at
# 642 MB. The two bounds in document_extraction.py stop DIFFERENT things, so
# they are tested separately — a single test passing against one of them
# would leave the other unguarded, which is the whole reason there are two.
# ───────────────────────────────────────────────────────────────────────────


def _build_multipage_pdf(page_texts: list[str]) -> bytes:
    """A real, valid PDF with one page per entry in `page_texts`.

    Pass "" for a page with no extractable text — that is the shape the
    character-based bound cannot see, so the tests need to be able to build it.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        None,  # filled in below, once the page object numbers are known
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for index, text in enumerate(page_texts):
        page_num = 4 + 2 * index
        content_num = page_num + 1
        kids.append(f"{page_num} 0 R")
        content = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 3 0 R >> >> "
            f"/MediaBox [0 0 200 200] /Contents {content_num} 0 R >>".encode()
        )
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"
        )
    objects[1] = (
        f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(page_texts)} >>".encode()
    )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_offset = out.tell()
    n = len(objects) + 1
    out.write(f"xref\n0 {n}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(b"trailer\n")
    out.write(f"<< /Size {n} /Root 1 0 R >>\n".encode())
    out.write(b"startxref\n")
    out.write(f"{xref_offset}\n".encode())
    out.write(b"%%EOF")
    return out.getvalue()


class _CountingPage:
    def __init__(self, text: str, counter: list[int]) -> None:
        self._text = text
        self._counter = counter

    def extract_text(self) -> str:
        self._counter[0] += 1
        return self._text


class _CountingReader:
    """Stands in for pypdf's reader so a test can state an exact page count.

    This fakes pypdf, not our loop — the loop under test is the real one, and
    the two tests below that use a REAL multi-page PDF cover the seam this
    cannot. A fake on its own would only prove our loop agrees with our own
    idea of pypdf.
    """

    def __init__(self, pages: list) -> None:
        self.pages = pages


def _count_pages_read(page_texts: list[str], monkeypatch) -> int:
    counter = [0]
    pages = [_CountingPage(t, counter) for t in page_texts]
    monkeypatch.setattr(
        document_extraction, "PdfReader", lambda _stream: _CountingReader(pages)
    )
    try:
        extract_narration_text("narration.pdf", _b64(b"ignored-by-the-fake"))
    except UnsupportedNarrationFileError:
        pass  # an all-blank file legitimately ends in "No text found"
    return counter[0]


def test_a_pdf_of_blank_pages_is_bounded_by_the_page_cap(monkeypatch):
    """The case the character bound CANNOT catch.

    `extract_text()` returns "" for a blank or image-only page, so the
    accumulated length never grows and the early stop never fires. Without
    MAX_PDF_PAGES this walks every page a file cares to declare.
    """
    touched = _count_pages_read([""] * 5000, monkeypatch)
    assert touched == MAX_PDF_PAGES, (
        f"walked {touched} blank pages; MAX_PDF_PAGES is {MAX_PDF_PAGES}. An "
        "attacker-supplied PDF of empty pages is the cheap denial-of-service "
        "on this endpoint."
    )


def test_a_text_bearing_pdf_stops_as_soon_as_there_is_enough_text(monkeypatch):
    """The ordinary large upload: stop at the output cap, not at page 50.

    This bound is not a second arbitrary number — it falls out of
    MAX_NARRATION_CHARS, which already governs what any of this can return.
    """
    per_page = "x" * 500
    touched = _count_pages_read([per_page] * 5000, monkeypatch)
    expected = MAX_NARRATION_CHARS // (len(per_page) + 1) + 1
    assert touched == expected, f"walked {touched} pages, expected {expected}"
    assert touched < MAX_PDF_PAGES, (
        "the character bound must bite first for a file that actually has "
        "text, otherwise it is doing no work"
    )


def test_the_page_cap_is_applied_to_a_real_pdf_not_just_a_fake():
    """The invocation, against real pypdf — the seam the fake cannot cover.

    A sentinel sits on the page just past the cap. If the cap holds, that page
    is never read and the file reads as having no text at all; if the slice is
    removed, the sentinel comes back. Asserting only that this raises would NOT
    have been a guard — an unbounded walk over blank pages raises the very same
    error, so the test would have passed with the bound deleted.
    """
    pages = [""] * MAX_PDF_PAGES + ["NeverReachMe"]
    pdf_bytes = _build_multipage_pdf(pages)
    with pytest.raises(UnsupportedNarrationFileError):
        extract_narration_text("narration.pdf", _b64(pdf_bytes))


def test_a_real_multipage_narration_still_reads_across_its_pages():
    """The bounds must not break the thing they protect.

    A child's export legitimately spans a few pages, and every one of them
    inside the output cap must still arrive.
    """
    pdf_bytes = _build_multipage_pdf(["First part", "Second part", "Third part"])
    text = extract_narration_text("narration.pdf", _b64(pdf_bytes))
    for fragment in ("First part", "Second part", "Third part"):
        assert fragment in text
