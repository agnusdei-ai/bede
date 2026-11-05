"""
Practice Coach upload validation and hardening (services/practice/upload_safety.py).

Every guard here was verified by breaking the code it guards; see the PR body.
This is hardening, not a claim that a file is malware-free.
"""
import asyncio
import base64
import io
import json
import struct
import tempfile
import threading
import zlib
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import BooleanObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject

from models.practice import PhotoPage, ReadPhotosRequest
from services.practice import extract, upload_safety
from services.practice.upload_safety import PhotoRejected

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "services/practice/packs/latin/golden/latin_quiz_1.expected.json")
    .read_text(encoding="utf-8")
)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def png_bytes(color=(10, 120, 40), size=(16, 16), **save) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG", **save)
    return out.getvalue()


def jpeg_bytes(color=(10, 40, 160), exif: bytes | None = None) -> bytes:
    out = io.BytesIO()
    img = Image.new("RGB", (16, 16), color)
    if exif:
        img.save(out, format="JPEG", exif=exif)
    else:
        img.save(out, format="JPEG")
    return out.getvalue()


def _image_xobject(writer, kind: str, w=16, h=16):
    stream = DecodedStreamObject()
    if kind == "jpeg":
        stream.set_data(jpeg_bytes())
        stream[NameObject("/Filter")] = NameObject("/DCTDecode")
        stream._data = jpeg_bytes()
    else:
        stream.set_data(bytes([90, 140, 200]) * (w * h))
    for k, v in {"/Type": NameObject("/XObject"), "/Subtype": NameObject("/Image"),
                 "/Width": NumberObject(w), "/Height": NumberObject(h),
                 "/ColorSpace": NameObject("/DeviceRGB"), "/BitsPerComponent": NumberObject(8)}.items():
        stream[NameObject(k)] = v
    return writer._add_object(stream)


PLAIN_SCAN = b"q 100 0 0 100 0 0 cm /Im0 Do Q"


def _content(writer, data: bytes):
    stream = DecodedStreamObject()
    stream.set_data(data)
    return writer._add_object(stream)


def make_pdf(kinds=("jpeg", "raw"), mutate=None, content: bytes = PLAIN_SCAN, second_image=False, annots=(), form=False) -> bytes:
    writer = PdfWriter()
    for kind in kinds:
        page = writer.add_blank_page(100, 100)
        if kind != "blank":
            xobjects = {NameObject("/Im0"): _image_xobject(writer, kind)}
            if second_image:
                xobjects[NameObject("/Im1")] = _image_xobject(writer, "raw")
            if form:
                from pypdf.generic import ArrayObject
                inner = DecodedStreamObject()
                inner.set_data(b"BT (note) Tj ET")
                for k, v in {"/Type": NameObject("/XObject"), "/Subtype": NameObject("/Form"),
                             "/BBox": ArrayObject([NumberObject(0), NumberObject(0), NumberObject(50), NumberObject(50)])}.items():
                    inner[NameObject(k)] = v
                xobjects[NameObject("/Fm0")] = writer._add_object(inner)
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/XObject"): DictionaryObject(xobjects),
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica")})})})
            page[NameObject("/Contents")] = _content(writer, content)
            if annots:
                from pypdf.generic import ArrayObject
                page[NameObject("/Annots")] = ArrayObject([
                    writer._add_object(DictionaryObject({
                        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject(sub),
                        **({NameObject("/Rect"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(9), NumberObject(9)])})}))
                    for sub in annots])
    if mutate:
        mutate(writer)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def prep(*raws: bytes):
    return await upload_safety.prepare_pages([b64(r) for r in raws])


def decoded(pages):
    return [Image.open(io.BytesIO(base64.b64decode(d))) for _, d in pages]


# ── PDFs ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_valid_two_page_pdf_yields_two_png_pages():
    pages = await prep(make_pdf())
    assert [m for m, _ in pages] == ["image/png", "image/png"]
    assert all(img.format == "PNG" for img in decoded(pages))


@pytest.mark.asyncio
@pytest.mark.parametrize("name,mutate", [
    ("javascript", lambda w: w.add_js("app.alert(1);")),
    ("embedded file", lambda w: w.add_attachment("x.txt", b"payload")),
    ("open action", lambda w: w._root_object.update({NameObject("/OpenAction"): DictionaryObject(
        {NameObject("/S"): NameObject("/Launch")})})),
    ("acroform", lambda w: w._root_object.update({NameObject("/AcroForm"): DictionaryObject()})),
    ("encrypted", lambda w: w.encrypt("secret")),
    ("encrypted, openable with an empty password", lambda w: w.encrypt("", owner_password="owner")),
])
async def test_active_content_encryption_and_attachments_are_rejected(name, mutate):
    with pytest.raises(PhotoRejected):
        await prep(make_pdf(("jpeg",), mutate))


@pytest.mark.asyncio
async def test_a_hex_escaped_name_does_not_hide_active_content():
    raw = make_pdf(("jpeg",), lambda w: w.add_js("app.alert(1);"))
    assert b"/JavaScript" in raw
    with pytest.raises(PhotoRejected):
        await prep(raw.replace(b"/JavaScript", b"/J#61vaScript"))


@pytest.mark.asyncio
async def test_active_content_inside_an_object_stream_is_found_by_the_graph_walk():
    """The raw-byte scan cannot see inside a compressed object stream; the walk can."""
    raw = make_pdf(("jpeg",), lambda w: w.add_js("app.alert(1);"))
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    with pytest.raises(PhotoRejected):
        upload_safety._refuse_active_content(reader, b"%PDF- nothing readable in the bytes")


def test_unreadable_pdf_indirect_object_fails_closed(monkeypatch):
    """A damaged indirect object cannot be silently skipped during PDF safety review."""
    from pypdf import PdfReader
    from pypdf.generic import IndirectObject

    raw = make_pdf(("jpeg",))
    reader = PdfReader(io.BytesIO(raw))

    def unreadable(_self):
        raise ValueError("synthetic unreadable indirect object")

    monkeypatch.setattr(IndirectObject, "get_object", unreadable)
    with pytest.raises(PhotoRejected, match="unreadable object"):
        upload_safety._refuse_active_content(reader, raw)


def _flate_scan(writer, data: bytes) -> None:
    """Encode the existing synthetic 16x16 RGB scan as Flate in a real PDF."""
    image = writer.pages[0]["/Resources"]["/XObject"]["/Im0"].get_object()
    image[NameObject("/Filter")] = NameObject("/FlateDecode")
    image._data = zlib.compress(data)


@pytest.mark.asyncio
async def test_flate_scan_bounded_before_pypdf_decoding(monkeypatch):
    """A tiny compressed over-expansion must fail before unbounded get_data()."""
    from pypdf.generic import EncodedStreamObject

    expected = bytes([90, 140, 200]) * (16 * 16)
    valid = make_pdf(("raw",), lambda writer: _flate_scan(writer, expected))
    too_large = make_pdf(("raw",), lambda writer: _flate_scan(writer, expected + b"X"))

    original = EncodedStreamObject.get_data

    def guarded_get_data(stream):
        if stream.get("/Subtype") == "/Image":
            raise AssertionError("pypdf must not inflate a Flate image unchecked")
        return original(stream)

    monkeypatch.setattr(EncodedStreamObject, "get_data", guarded_get_data)
    pages = await prep(valid)
    assert len(pages) == 1 and decoded(pages)[0].format == "PNG"
    with pytest.raises(PhotoRejected, match="expands beyond"):
        await prep(too_large)


@pytest.mark.asyncio
@pytest.mark.parametrize("key,value", [
    ("/Predictor", FloatObject(1.5)),
    ("/Columns", FloatObject(16.5)),
    ("/Colors", FloatObject(3.5)),
    ("/BitsPerComponent", FloatObject(8.5)),
    ("/Predictor", BooleanObject(True)),
])
async def test_flate_scan_refuses_non_integral_decode_params(key, value):
    """Do not silently truncate malformed PDF predictor metadata."""
    expected = bytes([90, 140, 200]) * (16 * 16)

    def mutate(writer):
        _flate_scan(writer, expected)
        image = writer.pages[0]["/Resources"]["/XObject"]["/Im0"].get_object()
        image[NameObject("/DecodeParms")] = DictionaryObject({
            NameObject("/Predictor"): NumberObject(1),
            NameObject("/Columns"): NumberObject(16),
            NameObject("/Colors"): NumberObject(3),
            NameObject("/BitsPerComponent"): NumberObject(8),
        })
        image["/DecodeParms"][NameObject(key)] = value

    with pytest.raises(PhotoRejected, match="unsupported decoding"):
        await prep(make_pdf(("raw",), mutate))


@pytest.mark.asyncio
@pytest.mark.parametrize("predictor", [12, 15])
async def test_flate_scan_png_predictor_bounded_and_decoded(predictor):
    """A valid PNG predictor remains supported under the decompression cap."""
    row = bytes([90, 140, 200]) * 16
    # PNG predictor rows carry one filter byte (0 = None).
    encoded = (bytes([0]) + row) * 16

    def mutate(writer):
        _flate_scan(writer, encoded)
        image = writer.pages[0]["/Resources"]["/XObject"]["/Im0"].get_object()
        image[NameObject("/DecodeParms")] = DictionaryObject({
            NameObject("/Predictor"): NumberObject(predictor),
            NameObject("/Columns"): NumberObject(16),
            NameObject("/Colors"): NumberObject(3),
            NameObject("/BitsPerComponent"): NumberObject(8),
        })

    pages = await prep(make_pdf(("raw",), mutate))
    assert len(pages) == 1
    assert decoded(pages)[0].getpixel((0, 0)) == (90, 140, 200)


@pytest.mark.asyncio
async def test_pdf_page_and_content_limits():
    with pytest.raises(PhotoRejected):
        await prep(make_pdf(("jpeg",) * 7))
    with pytest.raises(PhotoRejected):  # 4 + 3 pages across two files is still over six in total
        await prep(make_pdf(("jpeg",) * 4), make_pdf(("jpeg",) * 3))
    with pytest.raises(PhotoRejected):  # a text/vector page has no scanned image to take
        await prep(make_pdf(("blank",)))
    with pytest.raises(PhotoRejected):
        await prep(b"%PDF-1.7 truncated garbage")


# ── Images ────────────────────────────────────────────────────────────────────

def _chunks(png: bytes):
    pos, out = 8, []
    while pos < len(png):
        (n,) = struct.unpack(">I", png[pos:pos + 4])
        out.append(png[pos + 4:pos + 8])
        pos += 12 + n
    return out


@pytest.mark.asyncio
async def test_a_polyglot_is_re_encoded_and_its_payload_does_not_survive():
    payload = b"PK\x03\x04<script>alert(1)</script>MZ-EVIL-PAYLOAD"
    for raw in (png_bytes() + payload, jpeg_bytes() + payload):
        (_, data), = await prep(raw)
        out = base64.b64decode(data)
        assert b"EVIL-PAYLOAD" not in out and b"<script>" not in out and b"PK\x03\x04" not in out
        assert out != raw and Image.open(io.BytesIO(out)).format == "PNG"


@pytest.mark.asyncio
async def test_metadata_is_stripped_and_exif_rotation_is_applied_first():
    exif = Image.Exif()
    exif[0x010E] = "SECRET-DESCRIPTION"
    exif[0x0112] = 6  # rotate 90 degrees
    src = io.BytesIO()
    Image.new("RGB", (40, 10), (1, 2, 3)).save(src, format="JPEG", exif=exif.tobytes())
    png_text = io.BytesIO()
    Image.new("RGB", (8, 8)).save(png_text, format="PNG", pnginfo=_info("SECRET-TEXT"))
    pages = await prep(src.getvalue(), png_text.getvalue())
    for _, data in pages:
        out = base64.b64decode(data)
        assert b"SECRET" not in out and set(_chunks(out)) <= {b"IHDR", b"IDAT", b"IEND", b"PLTE", b"tRNS"}
    assert decoded(pages)[0].size == (10, 40)  # upright, and no orientation tag left to apply twice


def _info(text):
    from PIL.PngImagePlugin import PngInfo
    info = PngInfo()
    info.add_text("k", text)
    return info


def _fake_png_header(w, h) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * 64)) + chunk(b"IEND", b""))


@pytest.mark.asyncio
async def test_a_pixel_bomb_is_refused_from_its_header_without_decoding(monkeypatch):
    decoded_anything = []
    real_load = Image.Image.load
    monkeypatch.setattr(Image.Image, "load", lambda self, *a, **k: decoded_anything.append(1) or real_load(self, *a, **k))
    for w, h in ((20_000, 20_000), (6_000, 6_000), (40_000, 10)):
        with pytest.raises(PhotoRejected):
            await prep(_fake_png_header(w, h))
    assert decoded_anything == []
    assert upload_safety.MAX_PIXELS < 6_000 * 6_000


@pytest.mark.asyncio
async def test_a_truncated_or_corrupt_image_is_refused():
    good = png_bytes(size=(64, 64))
    with pytest.raises(PhotoRejected):
        await prep(good[:-30])
    with pytest.raises(PhotoRejected):
        await prep(good[:60] + bytes(b ^ 0xFF for b in good[60:90]) + good[90:])


@pytest.mark.asyncio
async def test_type_comes_from_the_bytes_not_from_what_the_caller_claims():
    with pytest.raises(PhotoRejected):  # JPEG bytes can never be passed off as PNG
        upload_safety.reencode_image(jpeg_bytes(), "PNG")
    with pytest.raises(PhotoRejected):
        await prep(b"GIF89a" + png_bytes())
    # a GIF or BMP that Pillow could read is still not in the allowed formats
    for fmt in ("GIF", "BMP"):
        out = io.BytesIO()
        Image.new("RGB", (4, 4)).save(out, format=fmt)
        with pytest.raises(PhotoRejected):
            await prep(out.getvalue())


# ── Scanner ───────────────────────────────────────────────────────────────────

async def _clamd(reply: bytes, seen: list):
    async def handle(reader, writer):
        seen.append(await reader.readuntil(b"\0"))
        total = 0
        while True:
            (n,) = struct.unpack(">I", await reader.readexactly(4))
            if n == 0:
                break
            total += n
            await reader.readexactly(n)
        seen.append(total)
        writer.write(reply)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_no_scanner_configured_means_no_scan_and_no_connection(monkeypatch):
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", "")
    async def boom(*a, **k):
        raise AssertionError("a scanner connection was attempted")
    monkeypatch.setattr(asyncio, "open_connection", boom)
    assert len(await prep(png_bytes())) == 1


@pytest.mark.asyncio
async def test_a_configured_scanner_sees_the_original_bytes_and_clean_passes(monkeypatch):
    seen: list = []
    server, port = await _clamd(b"stream: OK\0", seen)
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", f"tcp://127.0.0.1:{port}")
    raw = png_bytes()
    assert len(await prep(raw)) == 1
    server.close()
    assert seen == [b"zINSTREAM\0", len(raw)]


@pytest.mark.asyncio
async def test_a_scanner_verdict_of_found_rejects(monkeypatch):
    server, port = await _clamd(b"stream: Eicar-Test-Signature FOUND\0", [])
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", f"tcp://127.0.0.1:{port}")
    with pytest.raises(PhotoRejected):
        await prep(png_bytes())
    server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["tcp://127.0.0.1:1", "unix:///nonexistent/clamd.sock", "http://scanner.example", "tcp://x"])
async def test_a_configured_but_unreachable_scanner_fails_closed(monkeypatch, url):
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", url)
    with pytest.raises(upload_safety.ScannerUnavailable):
        await prep(png_bytes())


@pytest.mark.asyncio
async def test_an_unintelligible_scanner_answer_fails_closed(monkeypatch):
    server, port = await _clamd(b"garbage\0", [])
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", f"tcp://127.0.0.1:{port}")
    with pytest.raises(upload_safety.ScannerUnavailable):
        await prep(png_bytes())
    server.close()


# ── Bounded work, no temp artifacts, no logging ───────────────────────────────

@pytest.mark.asyncio
async def test_decode_jobs_are_bounded_and_the_slot_is_held_until_the_thread_ends(monkeypatch):
    lock, state = threading.Lock(), {"now": 0, "max": 0}
    gate = threading.Event()

    def slow(raw, room):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        gate.wait(5)
        with lock:
            state["now"] -= 1
        return [("image/png", png_bytes())]

    monkeypatch.setattr(upload_safety, "sanitize_upload", slow)
    monkeypatch.setattr(upload_safety, "_slots", None)
    monkeypatch.setattr(upload_safety, "QUEUE_TIMEOUT_SECONDS", 0.2)
    tasks = [asyncio.create_task(prep(png_bytes())) for _ in range(5)]
    await asyncio.sleep(0.6)
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert state["max"] <= upload_safety.MAX_CONCURRENT_JOBS
    assert sum(isinstance(r, upload_safety.UploadBusy) for r in results) == 3  # the rest were told to retry


@pytest.mark.asyncio
async def test_a_job_that_times_out_still_occupies_its_slot_until_the_thread_finishes(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(upload_safety, "sanitize_upload", lambda raw, room: gate.wait(5) or [])
    monkeypatch.setattr(upload_safety, "_slots", None)
    monkeypatch.setattr(upload_safety, "PROCESS_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(PhotoRejected):
        await prep(png_bytes())
    assert upload_safety._slots._value == upload_safety.MAX_CONCURRENT_JOBS - 1
    gate.set()
    await asyncio.sleep(0.2)
    assert upload_safety._slots._value == upload_safety.MAX_CONCURRENT_JOBS


@pytest.mark.asyncio
async def test_a_cancelled_request_releases_its_slot_when_the_thread_ends(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(upload_safety, "sanitize_upload", lambda raw, room: gate.wait(5) or [])
    monkeypatch.setattr(upload_safety, "_slots", None)
    task = asyncio.create_task(prep(png_bytes()))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gate.set()
    await asyncio.sleep(0.2)
    assert upload_safety._slots._value == upload_safety.MAX_CONCURRENT_JOBS


@pytest.mark.asyncio
async def test_no_temporary_file_is_ever_created(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a temporary file was requested")
    for fn in ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile", "TemporaryDirectory"):
        monkeypatch.setattr(tempfile, fn, refuse)
    before = set(Path(tempfile.gettempdir()).iterdir())
    await prep(png_bytes(), jpeg_bytes(), make_pdf())
    for bad in (b"junk", png_bytes()[:-9], make_pdf(("jpeg",), lambda w: w.encrypt("x"))):
        with pytest.raises(PhotoRejected):
            await prep(bad)
    assert set(Path(tempfile.gettempdir()).iterdir()) == before
    source = Path(upload_safety.__file__).read_text()
    assert "tempfile" not in source.replace("tempfile", "", 0) or "No temporary file" in source
    assert "open(" not in source.replace("Image.open(", "").replace("open_connection", "").replace("open_unix_connection", "")


@pytest.mark.asyncio
async def test_rejections_and_acceptances_log_nothing_that_comes_from_the_upload(caplog):
    marker = b"LEARNER-FILENAME-SECRET"
    caplog.set_level("DEBUG")
    for bad in (marker + b"junk", make_pdf(("jpeg",), lambda w: w.add_js(marker.decode()))):
        with pytest.raises(PhotoRejected):
            await prep(bad)
    await prep(png_bytes() + marker)  # accepted: the trailing bytes are dropped
    assert "LEARNER-FILENAME-SECRET" not in caplog.text and b64(marker)[:16] not in caplog.text


# ── HEIC / HEIF (iPhone) ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unpatched_native_heif_decoder_is_never_called(monkeypatch):
    monkeypatch.setattr(upload_safety, "HEIF_DECODER_QUALIFIED", False)
    def fail(*args):
        raise AssertionError("unsafe native decoder was invoked")
    monkeypatch.setattr(upload_safety, "reencode_image", fail)
    raw = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32
    with pytest.raises(PhotoRejected, match="Use JPEG, PNG, or PDF"):
        await prep(raw)


def test_heif_codec_version_gate_cannot_accept_1_23_6(monkeypatch):
    monkeypatch.setattr(upload_safety.pillow_heif, "libheif_version", lambda: "1.23.6")
    assert upload_safety._safe_heif_decoder() is False
    monkeypatch.setattr(upload_safety.pillow_heif, "libheif_version", lambda: "1.23.7")
    assert upload_safety._safe_heif_decoder() is True
    monkeypatch.setattr(upload_safety.pillow_heif, "libheif_version", lambda: "invalid")
    assert upload_safety._safe_heif_decoder() is False



def heic_bytes(color=(5, 60, 90), size=(16, 16), **save) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="HEIF", **save)
    return out.getvalue()


@pytest.mark.skipif(not upload_safety.HEIF_DECODER_QUALIFIED, reason="requires patched libheif >=1.23.7")
@pytest.mark.asyncio
async def test_a_heic_photo_is_decoded_and_re_encoded_to_a_fresh_png():
    raw = heic_bytes()
    assert raw[4:8] == b"ftyp" and raw[8:12] in upload_safety.HEIF_BRANDS
    (media, data), = await prep(raw)
    out = base64.b64decode(data)
    assert media == "image/png" and out.startswith(b"\x89PNG")
    assert Image.open(io.BytesIO(out)).size == (16, 16)


@pytest.mark.skipif(not upload_safety.HEIF_DECODER_QUALIFIED, reason="requires patched libheif >=1.23.7")
@pytest.mark.asyncio
async def test_heic_metadata_and_appended_payload_do_not_survive():
    exif = Image.Exif()
    exif[0x010E] = "SECRET-DESCRIPTION"
    raw = heic_bytes(exif=exif.tobytes()) + b"MZ-EVIL-PAYLOAD<script>"
    (_, data), = await prep(raw)
    out = base64.b64decode(data)
    assert b"SECRET" not in out and b"EVIL-PAYLOAD" not in out and set(_chunks(out)) <= {b"IHDR", b"IDAT", b"IEND"}


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40,                   # right brand, nothing behind it
    b"\x00\x00\x00\x18ftypheic",                                   # header only
    b"\x00\x00\x00\x18ftypavif" + b"\x00" * 40,                   # a brand we do not take
    b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 40,
    b"\x00\x00\x00\x18ftyp",                                       # no brand at all
])
async def test_a_malformed_or_unlisted_ftyp_is_refused(raw):
    with pytest.raises(PhotoRejected):
        await prep(raw)


@pytest.mark.skipif(not upload_safety.HEIF_DECODER_QUALIFIED, reason="requires patched libheif >=1.23.7")
@pytest.mark.asyncio
async def test_a_truncated_or_corrupted_heic_is_refused():
    good = heic_bytes(size=(64, 64))
    with pytest.raises(PhotoRejected):
        await prep(good[: len(good) // 2])
    with pytest.raises(PhotoRejected):
        await prep(good[:40] + bytes(b ^ 0xFF for b in good[40:120]) + good[120:])


@pytest.mark.skipif(not upload_safety.HEIF_DECODER_QUALIFIED, reason="requires patched libheif >=1.23.7")
@pytest.mark.asyncio
async def test_heic_is_held_to_the_same_pixel_cap(monkeypatch):
    monkeypatch.setattr(upload_safety, "MAX_PIXELS", 100)
    with pytest.raises(PhotoRejected):
        await prep(heic_bytes(size=(16, 16)))
    monkeypatch.setattr(upload_safety, "MAX_PIXELS", 10_000)
    assert len(await prep(heic_bytes(size=(16, 16)))) == 1


@pytest.mark.skipif(not upload_safety.HEIF_DECODER_QUALIFIED, reason="requires patched libheif >=1.23.7")
@pytest.mark.asyncio
async def test_heic_goes_through_the_scanner_and_the_size_cap(monkeypatch):
    seen: list = []
    server, port = await _clamd(b"stream: OK\0", seen)
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", f"tcp://127.0.0.1:{port}")
    raw = heic_bytes()
    await prep(raw)
    server.close()
    assert seen == [b"zINSTREAM\0", len(raw)]
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", "tcp://127.0.0.1:1")
    with pytest.raises(upload_safety.ScannerUnavailable):
        await prep(raw)
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", "")
    with pytest.raises(PhotoRejected):
        await prep(raw + b"0" * upload_safety.MAX_PAGE_BYTES)


# ── The real pipeline ─────────────────────────────────────────────────────────

class _Stub:
    def __init__(self):
        self.calls = []
        self.messages = self

    async def create(self, **kw):
        self.calls.append(kw)
        return type("R", (), {"content": [type("B", (), {"text": json.dumps(GOLDEN["assessment"])})()]})()


@pytest.mark.asyncio
async def test_a_two_page_pdf_reaches_the_reader_as_png_blocks_through_read_pages(monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(extract, "_choose_client", lambda req: stub)
    req = ReadPhotosRequest(subject="latin", pages=[PhotoPage(data=b64(make_pdf()))])
    assert (await extract.read_pages(req)).subject == "latin"
    blocks = stub.calls[0]["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["image", "image", "text"]
    for block in blocks[:2]:
        assert block["source"]["media_type"] == "image/png"
        assert base64.b64decode(block["source"]["data"]).startswith(b"\x89PNG")
    assert "2 page(s)" in blocks[2]["text"]


@pytest.mark.asyncio
async def test_nothing_is_parsed_or_scanned_until_consent_and_routing_are_settled(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("upload processing began before consent")
    monkeypatch.setattr(extract, "_choose_client", lambda req: (_ for _ in ()).throw(extract.ConsentRequired("openai")))
    monkeypatch.setattr(extract, "prepare_pages", refuse)
    with pytest.raises(extract.ConsentRequired):
        await extract.read_pages(ReadPhotosRequest(subject="latin", pages=[PhotoPage(data=b64(png_bytes()))]))


def test_the_read_route_is_parent_authenticated_and_maps_scanner_failures_to_503():
    import inspect
    from core.deps import require_parent
    from routers import practice as router_module
    sig = inspect.signature(router_module.read_assessment)
    assert sig.parameters["auth"].default.dependency is require_parent
    source = inspect.getsource(router_module.read_assessment)
    assert "ScannerUnavailable" in source and "503" in source


# ── PDF pages are rendered, not taken apart ───────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("name,kwargs", [
    ("visible text over the scan", {"content": PLAIN_SCAN + b" BT /F1 12 Tf 10 10 Td (Good!) Tj ET"}),
    ("visible text, TJ form", {"content": PLAIN_SCAN + b" BT /F1 12 Tf 10 10 Td [(Go) 20 (od)] TJ ET"}),
    ("a vector rectangle", {"content": PLAIN_SCAN + b" 1 0 0 RG 5 5 20 20 re S"}),
    ("an inline image", {"content": PLAIN_SCAN + b" BI /W 1 /H 1 /CS /G /BPC 8 ID \x00 EI"}),
    ("a form XObject drawn", {"content": PLAIN_SCAN + b" /Fm0 Do", "form": True}),
    ("two images drawn", {"content": PLAIN_SCAN + b" q 50 0 0 50 0 0 cm /Im1 Do Q", "second_image": True}),
    ("a FreeText annotation", {"annots": ("/FreeText",)}),
    ("a link and a stamp", {"annots": ("/Link", "/Stamp")}),
    ("an invisible OCR text layer", {"content": PLAIN_SCAN + b" BT /F1 12 Tf 3 Tr 10 10 Td (hello) Tj ET"}),
    ("a clipped placement", {"content": b"q 0 0 100 100 re W n 100 0 0 100 0 0 cm /Im0 Do Q"}),
])
async def test_any_page_that_renders_is_accepted_whatever_it_is_built_from(name, kwargs):
    (page,) = decoded(await prep(make_pdf(("jpeg",), **kwargs)))
    assert page.format == "PNG"


@pytest.mark.asyncio
async def test_a_mark_drawn_over_the_scan_survives_into_the_rendered_page():
    """The old extractor kept only the picture and dropped this red box."""
    content = PLAIN_SCAN + b" q 1 0 0 rg 60 60 30 30 re f Q"
    (page,) = decoded(await prep(make_pdf(("jpeg",), content=content)))
    rgb = page.convert("RGB")
    w, h = rgb.size
    r, g, b = rgb.getpixel((int(w * 0.75), int(h * 0.25)))  # PDF y=75 is near the top
    assert r > 200 and g < 60 and b < 60


@pytest.mark.asyncio
async def test_a_teachers_annotation_mark_is_drawn_into_the_rendered_page():
    """A comment or stamp a teacher added in a PDF reader is part of the marking."""
    from pypdf.generic import ArrayObject

    def stamp(writer):
        appearance = DecodedStreamObject()
        appearance.set_data(b"1 0 0 rg 0 0 30 30 re f")
        for k, v in {"/Type": NameObject("/XObject"), "/Subtype": NameObject("/Form"),
                     "/BBox": ArrayObject([NumberObject(0), NumberObject(0), NumberObject(30), NumberObject(30)])}.items():
            appearance[NameObject(k)] = v
        annot = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Square"),
            NameObject("/Rect"): ArrayObject([NumberObject(60), NumberObject(60), NumberObject(90), NumberObject(90)]),
            NameObject("/AP"): DictionaryObject({NameObject("/N"): writer._add_object(appearance)}),
        }))
        writer.pages[0][NameObject("/Annots")] = ArrayObject([annot])

    (page,) = decoded(await prep(make_pdf(("jpeg",), stamp)))
    rgb = page.convert("RGB")
    w, h = rgb.size
    r, g, b = rgb.getpixel((int(w * 0.75), int(h * 0.25)))
    assert r > 200 and g < 60 and b < 60


@pytest.mark.asyncio
async def test_a_typed_text_page_with_no_scan_is_read():
    writer = PdfWriter()
    page = writer.add_blank_page(200, 100)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                             NameObject("/Subtype"): NameObject("/Type1"),
                                             NameObject("/BaseFont"): NameObject("/Helvetica")})})})
    page[NameObject("/Contents")] = _content(writer, b"BT /F1 24 Tf 10 40 Td (1. 7 + 5 = 12) Tj ET")
    out = io.BytesIO()
    writer.write(out)
    (rendered,) = decoded(await prep(out.getvalue()))
    assert min(rendered.convert("L").getextrema()) < 80  # dark glyphs on the page


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"q Q", b"q 1 0 0 RG (unterminated Tj [[["])
async def test_a_page_that_renders_blank_is_refused(content):
    with pytest.raises(PhotoRejected, match="blank"):
        await prep(make_pdf(("jpeg",), content=content))


@pytest.mark.asyncio
async def test_an_image_larger_than_the_photo_cap_is_refused_before_rendering(monkeypatch):
    monkeypatch.setattr(upload_safety, "MAX_PIXELS", 100)
    with pytest.raises(PhotoRejected, match="too large"):
        await prep(make_pdf(("jpeg",)))


@pytest.mark.asyncio
async def test_a_compressed_content_stream_that_over_expands_is_refused_before_rendering(monkeypatch):
    monkeypatch.setattr(upload_safety, "_STREAM_INFLATE_LIMIT", 1000)

    def bomb(writer):
        content = writer.pages[0]["/Contents"].get_object()
        content[NameObject("/Filter")] = NameObject("/FlateDecode")
        content._data = zlib.compress(PLAIN_SCAN + b" " * 5000)

    def never_render(*a, **k):
        raise AssertionError("pdfium must not see an unchecked stream")

    monkeypatch.setattr(upload_safety, "_render_page", never_render)
    with pytest.raises(PhotoRejected, match="expands beyond"):
        await prep(make_pdf(("jpeg",), bomb))


def test_rendering_is_serialised_behind_one_lock():
    """pdfium is not thread-safe and two uploads may decode at once."""
    import inspect
    source = inspect.getsource(upload_safety.pages_from_pdf)
    assert "with _PDFIUM_LOCK" in source and "pdfium.PdfDocument" in source
    assert source.index("with _PDFIUM_LOCK") < source.index("pdfium.PdfDocument")

# ── Scanner locality ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("tcp://127.0.0.1:3310", ("tcp", "127.0.0.1", 3310)),
    ("tcp://127.4.5.6:1", ("tcp", "127.4.5.6", 1)),
    ("tcp://[::1]:3310", ("tcp", "::1", 3310)),
    ("tcp://localhost:3310", ("tcp", "127.0.0.1", 3310)),
    ("unix:///run/clamav/clamd.ctl", ("unix", "/run/clamav/clamd.ctl")),
    ("", None),
])
def test_local_scanner_urls_are_accepted(url, expected):
    from core.scanner_url import parse_scanner_url
    assert parse_scanner_url(url) == expected


@pytest.mark.parametrize("url", [
    "tcp://203.0.113.9:3310",            # remote IPv4
    "tcp://[2001:db8::1]:3310",          # remote IPv6
    "tcp://clamd.example.com:3310",      # a DNS name
    "tcp://clamd:3310",                  # a compose service name
    "tcp://0.0.0.0:3310",                # unspecified, not loopback
    "tcp://localhost.example.com:3310",  # looks local, is a name
    "tcp://127.0.0.1",                   # no port
    "tcp://127.0.0.1:0",
    "tcp://127.0.0.1:99999",
    "unix://relative/path",
    "http://127.0.0.1:3310",
])
def test_non_local_scanner_urls_are_refused_at_boot_and_in_use(url, monkeypatch):
    import core.config as config
    from core.scanner_url import ScannerUrlRefused, parse_scanner_url
    with pytest.raises(ScannerUrlRefused):
        parse_scanner_url(url)
    with pytest.raises(ValueError):
        config.Settings(practice_scanner_url=url)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "tcp://203.0.113.9:3310", "tcp://[2001:db8::1]:3310", "tcp://clamd.example.com:3310", "tcp://0.0.0.0:3310",
])
async def test_a_refused_scanner_url_opens_no_socket_and_sends_no_bytes(monkeypatch, url):
    opened = []

    async def spy(*a, **k):
        opened.append(a)
        raise AssertionError("a socket was opened")
    monkeypatch.setattr(asyncio, "open_connection", spy)
    monkeypatch.setattr(asyncio, "open_unix_connection", spy)
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", url)  # bypasses the boot check on purpose
    with pytest.raises(upload_safety.ScannerUnavailable):
        await prep(png_bytes())
    assert opened == []


@pytest.mark.asyncio
async def test_a_hostname_that_resolves_to_loopback_is_still_refused_without_resolving(monkeypatch):
    import socket
    resolved = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: resolved.append(a) or [])
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", "tcp://loopback.test:3310")
    with pytest.raises(upload_safety.ScannerUnavailable):
        await prep(png_bytes())
    assert resolved == []


@pytest.mark.asyncio
async def test_bracketed_ipv6_loopback_reaches_the_connection_call(monkeypatch):
    seen = []

    async def fake(host, port):
        seen.append((host, port))
        raise OSError("refused")
    monkeypatch.setattr(asyncio, "open_connection", fake)
    monkeypatch.setattr(upload_safety.settings, "practice_scanner_url", "tcp://[::1]:3310")
    with pytest.raises(upload_safety.ScannerUnavailable):
        await prep(png_bytes())
    assert seen == [("::1", 3310)]


# ── Android and other phone photo formats ─────────────────────────────────────

def _photo(fmt: str, **save) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (24, 16), (200, 30, 30)).save(out, format=fmt, **save)
    return out.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["WEBP", "AVIF"])
async def test_webp_and_avif_photos_are_decoded_and_re_encoded_to_png(fmt):
    (page,) = decoded(await prep(_photo(fmt)))
    assert page.format == "PNG" and page.size == (24, 16)


@pytest.mark.asyncio
async def test_a_multi_picture_jpeg_from_an_android_camera_is_accepted():
    """Samsung and other cameras save MPO: a JPEG carrying a second picture."""
    out = io.BytesIO()
    first = Image.new("RGB", (24, 16), (200, 30, 30))
    first.save(out, format="MPO", save_all=True, append_images=[Image.new("RGB", (24, 16), (0, 0, 0))])
    raw = out.getvalue()
    assert Image.open(io.BytesIO(raw)).format == "MPO"
    (page,) = decoded(await prep(raw))
    assert page.format == "PNG"
    assert page.convert("RGB").getpixel((5, 5))[0] > 150  # the first picture, not the second


def test_an_avif_inside_a_generic_heif_brand_is_routed_to_the_avif_decoder():
    raw = _photo("AVIF")
    size = struct.unpack(">I", raw[:4])[0]
    relabelled = raw[:8] + b"mif1" + raw[12:16] + b"avif" + raw[20:]
    assert upload_safety._ftyp_brands(relabelled)[0] == b"mif1"
    assert b"avif" in upload_safety._ftyp_brands(relabelled)[1]
    assert size >= 20
    (kind, data), = upload_safety.sanitize_upload(relabelled, 6)
    assert kind == "image/png"


@pytest.mark.asyncio
async def test_a_webp_header_on_other_bytes_is_refused():
    with pytest.raises(PhotoRejected):
        await prep(b"RIFF\x10\x00\x00\x00WEBPVP8 junkjunkjunk")


# ── Regression: a scanner's three-layer compact PDF ──────────────────────────

@pytest.mark.asyncio
async def test_a_three_layer_scanner_pdf_renders_with_background_cleaning_and_ink():
    """Built like the owner's scanned answer key (see practice_scanner_fixture),
    which the old one-image-per-page rule refused outright."""
    from tests import practice_scanner_fixture as fixture
    from pypdf import PdfReader

    raw = fixture.build()
    page = PdfReader(io.BytesIO(raw)).pages[0]
    assert page.get_contents().get_data().startswith(b"% CANON_PFINF_TYPE2_TEXTOFF")
    layers = [v.get_object() for v in page["/Resources"]["/XObject"].values()]
    assert [str(x.get("/Filter")) for x in layers] == [
        "['/FlateDecode', '/DCTDecode']", "/CCITTFaxDecode", "/CCITTFaxDecode"]
    assert [bool(x.get("/ImageMask")) for x in layers] == [False, True, True]

    (rendered,) = decoded(await prep(raw))
    gray = rendered.convert("L")
    w, h = gray.size

    def at(fx, fy):
        return gray.getpixel((min(w - 1, int(fx * w)), min(h - 1, int(fy * h))))

    assert at(*fixture.ink_point_on_page(45 / 746, 55 / 936)) < 80, "the ink layer was lost"
    assert at(*fixture.ink_point_on_page(0.9, 0.98)) > 240, "the white cleaning layer was lost"
    assert at(0.5, 0.02) < 160, "the background layer was lost"
