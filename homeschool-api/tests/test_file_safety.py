"""Every file a person hands Bede goes through one gate (services/file_safety.py):
its kind from its bytes, a virus scan when the household runs one (fail
closed), and, for a picture, a rebuild from its pixels. These tests pin each
entry point (a lesson photo or drawing, a narration file, a voice recording)
through the real route, and that a file the scanner flags is refused,
recorded and alerted on at once, while a child only ever sees a calm line.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from core import audit
from core.audit import AuditEvent
from routers import tutor as tutor_router
from routers import voice as voice_router
from services import content_screen, file_safety
from services.practice import upload_safety
from test_practice_upload_safety import _clamd

EICAR_REPLY = b"stream: Eicar-Test-Signature FOUND\0"
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64


def jpeg_with_tail() -> bytes:
    """A real JPEG carrying EXIF and a payload appended after the image."""
    out = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "SampleCameraMaker"
    Image.new("RGB", (16, 12), (200, 30, 30)).save(out, format="JPEG", exif=exif)
    return out.getvalue() + b"PK\x03\x04hidden-archive-payload"


@pytest.fixture
def logged(monkeypatch):
    events: list = []
    monkeypatch.setattr(audit, "log_event_nowait", lambda event, **kw: events.append((event, kw)))
    return events


@pytest.fixture
def no_scanner(monkeypatch):
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", "")


async def scanner(monkeypatch, reply: bytes):
    seen: list = []
    server, port = await _clamd(reply, seen)
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", f"tcp://127.0.0.1:{port}")
    return server, seen


# ── A lesson photo or drawing ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_lesson_picture_is_rebuilt_from_its_pixels(no_scanner):
    raw = jpeg_with_tail()
    clean = base64.b64decode(await file_safety.lesson_picture(base64.b64encode(raw).decode()))
    assert clean.startswith(b"\x89PNG")
    assert b"SampleCameraMaker" not in clean and b"hidden-archive-payload" not in clean
    assert Image.open(io.BytesIO(clean)).size == (16, 12)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    b"%PDF-1.7 not a picture", b"MZ\x90\x00 a program", b"\x7fELF a program",
    b"PK\x03\x04 an archive", b"plain text pretending", b"",
])
async def test_anything_but_a_photo_or_drawing_is_refused(no_scanner, raw):
    with pytest.raises(file_safety.FileRejected):
        await file_safety.lesson_picture(base64.b64encode(raw).decode())


@pytest.mark.asyncio
async def test_a_picture_the_scanner_flags_is_refused_recorded_and_alerted(monkeypatch, logged):
    server, seen = await scanner(monkeypatch, EICAR_REPLY)
    raw = jpeg_with_tail()
    with pytest.raises(file_safety.ScannerFlagged):
        await file_safety.lesson_picture(base64.b64encode(raw).decode())
    server.close()
    # The scanner sees the bytes as sent, before anything decodes them.
    assert seen == [b"zINSTREAM\0", len(raw)]
    assert logged == [(AuditEvent.FILE_FLAGGED, {"success": False, "detail": "signature=Eicar-Test-Signature"})]


@pytest.mark.asyncio
async def test_a_configured_scanner_that_does_not_answer_refuses(monkeypatch):
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", "tcp://127.0.0.1:1")
    with pytest.raises(file_safety.ScannerUnavailable):
        await file_safety.lesson_picture(base64.b64encode(jpeg_with_tail()).decode())


@pytest.mark.asyncio
async def test_the_chat_tells_the_child_a_calm_line_and_the_tutor_never_sees_a_flagged_picture(monkeypatch, logged):
    server, _ = await scanner(monkeypatch, EICAR_REPLY)
    reached: list = []

    async def screen(*a, **k):
        reached.append("screen")

    monkeypatch.setattr(content_screen, "screen_images", screen)
    text = await _chat_text(monkeypatch, base64.b64encode(jpeg_with_tail()).decode(), reached)
    server.close()
    assert text == tutor_router._FILE_REFUSED["en"]
    assert reached == []
    assert [e for e, _ in logged] == [AuditEvent.FILE_FLAGGED]


@pytest.mark.asyncio
async def test_the_chat_passes_on_only_the_rebuilt_picture(monkeypatch, no_scanner):
    screened: list = []

    async def screen(_client, images, _context):
        screened.extend(images)

    monkeypatch.setattr(content_screen, "screen_images", screen)
    reached: list = []
    await _chat_text(monkeypatch, base64.b64encode(jpeg_with_tail()).decode(), reached)
    (media, data), = screened
    assert media == "image/png" and base64.b64decode(data).startswith(b"\x89PNG")
    assert reached == [data]


async def _chat_text(monkeypatch, image_b64: str, reached: list) -> str:
    from test_content_screen import _request, _turn

    async def stream(**kw):
        reached.append(kw["drawing_image"])
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(tutor_router, "stream_tutor_response", stream)
    response = await tutor_router.chat(_turn(image_b64), _request(), auth={"role": "parent"}, db=None)
    chunks = [json.loads(c) async for c in response.body_iterator]
    return "".join(c.get("content", "") for c in chunks if c["type"] == "text")


# ── A narration file ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("ext,raw", [
    ("pdf", b"MZ\x90 a program called .pdf"),
    ("txt", b"MZ\x90\x00 a program called .txt"),
    ("txt", b"PK\x03\x04 an archive called .txt"),
    ("txt", b"text\x00with nulls"),
])
async def test_a_narration_file_that_is_not_its_kind_is_refused(no_scanner, ext, raw):
    with pytest.raises(file_safety.FileRejected):
        await file_safety.narration_file(raw, ext)


@pytest.mark.asyncio
async def test_the_narration_route_scans_before_reading(monkeypatch, logged):
    from models.schemas import NarrationUploadRequest

    server, seen = await scanner(monkeypatch, EICAR_REPLY)
    req = NarrationUploadRequest(filename="story.txt",
                                 content_base64=base64.b64encode(b"Once there was a fox.").decode())
    with pytest.raises(HTTPException) as exc:
        await tutor_router.extract_narration(req, auth={"role": "child"})
    server.close()
    assert exc.value.status_code == 400 and seen[0] == b"zINSTREAM\0"
    assert [e for e, _ in logged] == [AuditEvent.FILE_FLAGGED]


# ── A voice recording ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_recording_is_judged_by_its_bytes_never_its_name(no_scanner):
    await file_safety.audio(WAV)
    for disguised in (b"MZ\x90\x00 a program", b"<html>not sound</html>", b"just some text here"):
        with pytest.raises(file_safety.FileRejected):
            await file_safety.audio(disguised)


@pytest.mark.asyncio
async def test_a_streamed_piece_may_be_raw_samples_but_never_another_kind_of_file(no_scanner):
    await file_safety.audio(b"\x00\x01" * 64, raw_samples=True)
    for bad in (b"\x7fELF" + b"\x00" * 12, b"PK\x03\x04" + b"\x00" * 12, b"\x00\x01\x02", b"plain text here!"):
        with pytest.raises(file_safety.FileRejected):
            await file_safety.audio(bad, raw_samples=True)
    with pytest.raises(file_safety.FileRejected):
        await file_safety.audio(b"\x00\x01" * 64)


@pytest.mark.asyncio
async def test_the_voice_route_refuses_a_renamed_file_and_a_flagged_one(monkeypatch, logged, no_scanner):
    with pytest.raises(HTTPException) as exc:
        await voice_router._validate_audio(b"text dressed as a recording", "answer.wav")
    assert exc.value.status_code == 415
    server, _ = await scanner(monkeypatch, EICAR_REPLY)
    with pytest.raises(HTTPException) as exc:
        await voice_router.transcribe(None, audio=UploadFile(io.BytesIO(WAV), filename="answer.wav"),
                                      language="en", auth={"role": "child"})
    server.close()
    assert exc.value.status_code == 415
    assert [e for e, _ in logged] == [AuditEvent.FILE_FLAGGED]


# ── The alert ────────────────────────────────────────────────────────────────

def test_one_flagged_file_is_enough_to_alert_and_it_is_pooled_across_addresses():
    assert audit._ANOMALY_RULES[AuditEvent.FILE_FLAGGED] == (1, 1)
    assert AuditEvent.FILE_FLAGGED in audit._GLOBAL_ANOMALY_EVENTS
    audit._anomaly_windows.clear()
    audit._anomaly_last_alert.clear()
    assert audit._check_anomaly(AuditEvent.FILE_FLAGGED, "unknown") is not None


def test_the_alert_email_names_no_file_and_says_what_bede_did():
    from services.email_service import build_file_flagged_alert_html

    html = build_file_flagged_alert_html()
    assert "refused" in html and "kept no copy" in html and "virus check" in html


def test_every_upload_route_goes_through_the_gate():
    """The invocation half: each route that takes a file calls file_safety."""
    import inspect

    tutor_src = inspect.getsource(tutor_router)
    assert "file_safety.lesson_picture" in tutor_src and "file_safety.narration_file" in tutor_src
    voice_src = inspect.getsource(voice_router)
    assert voice_src.count("await _validate_audio(") == 4
    assert "file_safety.audio" in voice_src
    assert asyncio.iscoroutinefunction(voice_router._validate_audio)
