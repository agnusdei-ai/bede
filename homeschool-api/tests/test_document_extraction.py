"""
Tests for pulling narration text out of a file a child exported from a smart
pen/notebook app (e.g. inq — https://inq.shop) — see
services/document_extraction.py and routers/tutor.py's /tutor/extract-narration.
"""
import base64
import io

import pytest

from services.document_extraction import (
    extract_narration_text,
    MAX_NARRATION_CHARS,
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
