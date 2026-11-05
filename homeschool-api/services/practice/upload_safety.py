"""
File validation and hardening for everything a parent uploads to Practice
Coach, before any byte reaches a model. This is hardening, not a guarantee that
a file is free of malware.

* Type is decided from the bytes alone (magic numbers); a filename or declared
  content type is never consulted (the API does not even receive one).
* HEIC/HEIF is recognized by its `ftyp` brand but rejected before native decoding
  whenever the linked libheif is older than 1.23.7. Only a patched native
  decoder is registered, after which the image receives the same checks and
  re-encoding as JPEG or PNG.
* Every image is FULLY DECODED with Pillow and RE-ENCODED to a fresh PNG: the
  header is checked for pixel count before any pixel is decoded, Pillow's own
  decompression-bomb guard is set to the same cap and promoted to an error,
  `verify()` is followed by a real reload, EXIF rotation is applied and then
  every piece of metadata is dropped with the original container, so a
  polyglot's appended payload does not survive.
* A PDF is checked with pypdf first: refused outright if it is encrypted or
  carries any active-content or attachment marker (JavaScript, Launch,
  embedded files, open actions, forms, rich media, submit/import actions),
  across the whole object graph including object streams and hex-escaped
  names. Every image is held to the photo pixel cap and every compressed
  stream is inflated against a fixed limit before anything renders. Each page
  is then RENDERED with pdfium (the PDF engine Chrome ships) at no more than
  3,000 px a side, with annotations drawn and form fields not, so scanned
  layers, typed text and drawn marks all survive; the rendered page is what is
  validated (a blank result is refused) and re-encoded like a photo. pdfium is
  not thread-safe, so rendering is serialised behind one lock.
* Limits: bytes per file and per request, pixels and side length, decoded
  memory (pixels x channels), PDF object count, a per-file processing time,
  and a semaphore bounding how many decode jobs run at once. There is no
  limit on how many pages a parent uploads: pages are rebuilt and read
  READ_GROUP_SIZE at a time (`page_groups`), and each group's images are
  dropped before the next is built, so memory does not grow with page count.
* Everything happens in memory (io.BytesIO). No temporary file is created, so
  there is nothing to clean up on success, error, timeout or cancellation; a
  test pins that. Decoding runs in a worker thread of the API process: that is
  NOT process isolation, and the process keeps the container's network and
  filesystem. The container is read_only with cap_drop ALL.
* Optional: PRACTICE_SCANNER_URL points at a LOCAL clamd (tcp:// or unix://).
  When set, every upload is streamed to it first and an unreachable scanner
  REFUSES the upload (fail closed). When unset nothing is scanned and nothing
  claims otherwise. No external scanning service is ever contacted.

Raw bytes, extracted content and filenames are never logged here.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import re
import struct
import threading
import warnings
import zlib

import pillow_heif
import pypdfium2 as pdfium
from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

from core.config import settings
from core.scanner_url import ScannerUrlRefused, parse_scanner_url

# One file. Big enough for a long scanned PDF; a whole upload may be up to
# 1 GB (checked in the browser, uploadParts.ts) and is sent in parts.
MAX_PAGE_BYTES = 25 * 1024 * 1024
# Pages sent to the reader in one call. This is not a limit on how many pages
# a parent may upload: any number is read, one group after another.
READ_GROUP_SIZE = 6
# One request's files together. A browser sends a long upload as several
# requests (see PracticeCoach.tsx), so this bounds memory, not page count.
MAX_REQUEST_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 30_000_000   # decoded memory is at most pixels x 4 bytes
MAX_SIDE = 12_000
MAX_OUTPUT_SIDE = 3_000   # pages are downscaled to this before re-encoding
MAX_PDF_OBJECTS = 20_000
SCAN_TIMEOUT_SECONDS = 30
PROCESS_TIMEOUT_SECONDS = 25
QUEUE_TIMEOUT_SECONDS = 10
MAX_CONCURRENT_JOBS = 2

# Pillow's own bomb guard: warns above this, errors above twice it. Warnings are
# promoted to errors where we open images, so the cap is a hard one.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# pillow-heif 1.8.1 bundles libheif 1.23.6. Upstream libheif 1.23.7
# (2026-10-26) patches high-severity untrusted-image vulnerabilities.
# Enforce the linked native library version, not merely the Python wheel pin.
def _safe_heif_decoder() -> bool:
    try:
        parts = tuple(int(part) for part in pillow_heif.libheif_version().split(".")[:3])
        return len(parts) == 3 and parts >= (1, 23, 7)
    except (AttributeError, TypeError, ValueError):
        return False


HEIF_DECODER_QUALIFIED = _safe_heif_decoder()
if HEIF_DECODER_QUALIFIED:
    pillow_heif.register_heif_opener()

# MPO (a JPEG carrying extra pictures, saved by Samsung and other Android
# cameras) is opened by Pillow's JPEG reader; only its first picture is used.
# WEBP and AVIF are decoded by Pillow itself, not by the HEIF plugin, so they
# are not held back by the libheif version gate.
_FORMATS = ("PNG", "JPEG", "WEBP", "AVIF", "HEIF")
HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heif"})
AVIF_BRANDS = frozenset({b"avif", b"avis"})


def _ftyp_brands(raw: bytes) -> tuple[bytes, frozenset[bytes]]:
    """The major brand and the compatible brands of an ISO-BMFF `ftyp` box."""
    if raw[4:8] != b"ftyp" or len(raw) < 16:
        return b"", frozenset()
    size = min(struct.unpack(">I", raw[:4])[0], len(raw), 256)
    compatible = frozenset(raw[i:i + 4] for i in range(16, size - 3, 4))
    return raw[8:12], compatible


class PhotoRejected(ValueError):
    pass


class ScannerUnavailable(Exception):
    pass


class UploadBusy(Exception):
    pass


# ── Images ────────────────────────────────────────────────────────────────────

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _check_size(w: int, h: int) -> None:
    if w < 1 or h < 1 or w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
        raise PhotoRejected("A page's dimensions are too large; please retake it at a lower resolution.")


def reencode_image(raw: bytes, expect: str) -> bytes:
    """Fully decode `raw` (PNG, JPEG, WebP, AVIF or HEIF) and return a brand-new PNG."""
    bad = PhotoRejected("A page is not a valid JPEG, PNG, WebP, AVIF or HEIC image.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(raw), formats=_FORMATS)
            if probe.format != expect and not (expect == "JPEG" and probe.format == "MPO"):
                raise bad
            _check_size(*probe.size)  # from the header, before any pixel is decoded
            probe.verify()
            img = Image.open(io.BytesIO(raw), formats=_FORMATS)  # verify() leaves the first unusable
            if expect == "JPEG" and img.format == "JPEG":
                img.draft("RGB", (MAX_OUTPUT_SIDE, MAX_OUTPUT_SIDE))
            img.load()
            img = ImageOps.exif_transpose(img)  # apply the phone's rotation before metadata is dropped
            if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                img = flat
            elif img.mode not in ("L", "RGB"):
                img = img.convert("L" if img.mode in ("1", "I;16", "I") else "RGB")
            img.thumbnail((MAX_OUTPUT_SIDE, MAX_OUTPUT_SIDE))
            out = io.BytesIO()
            img.save(out, format="PNG")  # a new file: no info, no EXIF, nothing appended
            return out.getvalue()
    except PhotoRejected:
        raise
    except Exception as exc:  # Pillow errors, bombs, truncation: refuse, never half-read
        raise bad from exc


# ── PDF ───────────────────────────────────────────────────────────────────────

FORBIDDEN_PDF_NAMES = frozenset({
    "/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/EmbeddedFiles", "/OpenAction", "/AA",
    "/AcroForm", "/XFA", "/RichMedia", "/SubmitForm", "/ImportData", "/GoToE", "/Encrypt",
})
_RAW_NAME = re.compile(rb"/[A-Za-z#0-9]+")


def _unescape_name(token: bytes) -> str:
    return re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), token).decode("latin-1")


def _refuse_active_content(reader: PdfReader, raw: bytes) -> None:
    refuse = PhotoRejected("This PDF contains active content, attachments or a form and was not accepted. "
                           "Please scan the pages to a plain PDF or use photos.")
    if any(_unescape_name(t) in FORBIDDEN_PDF_NAMES for t in _RAW_NAME.findall(raw)):
        raise refuse
    numbers = {n for gen in reader.xref.values() for n in gen} | set(reader.xref_objStm)
    if len(numbers) > MAX_PDF_OBJECTS:
        raise PhotoRejected("This PDF is too complex to accept.")
    seen: set[int] = set()
    stack: list = [reader.trailer] + [IndirectObject(n, 0, reader) for n in numbers]
    while stack:
        obj = stack.pop()
        if isinstance(obj, IndirectObject):
            if obj.idnum in seen:
                continue
            seen.add(obj.idnum)
            try:
                obj = obj.get_object()
            except Exception as exc:
                # An unreadable object may hide an action or attachment. Never
                # skip it and then claim the whole PDF was checked safely.
                raise PhotoRejected(
                    "This PDF contains an unreadable object and cannot be checked safely. "
                    "Please scan the pages to a plain PDF or use photos."
                ) from exc
        if isinstance(obj, str) and obj in FORBIDDEN_PDF_NAMES:
            raise refuse
        if isinstance(obj, DictionaryObject):  # a stream is a dictionary; its data is never read here
            for key, value in obj.items():
                if key in FORBIDDEN_PDF_NAMES:
                    raise refuse
                stack.append(value)
        elif isinstance(obj, ArrayObject):
            stack.extend(obj)


def _bounded_flate_image(x, expected: int, height: int) -> bytes:
    """Reject oversized Flate image streams before pypdf can inflate them.

    A 25 MB PDF can contain a much larger compressed image stream. pypdf's
    get_data() inflates it in full, so checking the result afterward is too
    late. Bound zlib output to the declared 8-bit image size, plus at most
    one predictor byte per row for PNG predictors.
    """
    compressed = getattr(x, "_data", None)
    if not isinstance(compressed, bytes):
        raise PhotoRejected("This PDF image cannot be checked safely.")
    params = x.get("/DecodeParms")
    if isinstance(params, ArrayObject):
        if len(params) != 1:
            raise PhotoRejected("This PDF image uses unsupported decoding.")
        params = params[0]
    if isinstance(params, IndirectObject):
        params = params.get_object()
    predictor = 1
    if params:
        if not isinstance(params, DictionaryObject):
            raise PhotoRejected("This PDF image uses unsupported decoding.")
        # PDF FloatObject values (e.g. /Predictor 1.5) must not be
        # truncated by int(): malformed decoding metadata fails closed.
        # pypdf NumberObject is an int subclass; bool is not a PDF integer.
        values = (
            params.get("/Predictor", 1),
            params.get("/Columns", 1),
            params.get("/Colors", 1),
            params.get("/BitsPerComponent", 8),
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise PhotoRejected("This PDF image uses unsupported decoding.")
        predictor, columns, colors, bits = values
        if (
            predictor not in (1, 2, 10, 11, 12, 13, 14, 15)
            or columns < 1 or colors < 1 or bits != 8
            or columns * colors > expected
        ):
            raise PhotoRejected("This PDF image uses unsupported decoding.")
    limit = expected + (height if 10 <= predictor <= 15 else 0)
    try:
        inflater = zlib.decompressobj()
        decoded = inflater.decompress(compressed, limit + 1)
        if (
            len(decoded) > limit or inflater.unconsumed_tail
            or not inflater.eof or inflater.unused_data
        ):
            raise PhotoRejected("This PDF image expands beyond its allowed size.")
        decoded += inflater.flush(limit + 1 - len(decoded))
    except zlib.error as exc:
        raise PhotoRejected("This PDF image could not be decompressed safely.") from exc
    if len(decoded) > limit:
        raise PhotoRejected("This PDF image expands beyond its allowed size.")
    # Only supported, size-bounded predictors reach pypdf's row decoding.
    return decoded if predictor == 1 else x.get_data()


_JPEG_IN_FLATE_LIMIT = 2 * MAX_PAGE_BYTES  # a JPEG wrapped in Flate cannot be much larger than its file
_STREAM_INFLATE_LIMIT = 32 * 1024 * 1024    # any other compressed stream (page content, fonts)
_BLANK_PAGE = PhotoRejected("A page in this PDF came out blank. Please scan or photograph the paper again.")
# pdfium is not safe to call from two threads at once, and up to two uploads
# are decoded in parallel (MAX_CONCURRENT_JOBS), so all rendering is serialised.
_PDFIUM_LOCK = threading.Lock()


def _filters(x) -> list[str]:
    filt = x.get("/Filter")
    if filt is None:
        return []
    filt = filt.get_object() if isinstance(filt, IndirectObject) else filt
    return [str(f) for f in filt] if isinstance(filt, ArrayObject) else [str(filt)]


def _check_streams(reader: PdfReader) -> None:
    """Bound every image and every compressed stream before pdfium touches it.

    pdfium inflates whatever a page asks for, so a few megabytes of Flate can
    otherwise become gigabytes. Image dimensions are checked against the same
    pixel cap as photos, and every Flate stream is inflated here against a
    fixed limit first (images: their declared size).
    """
    numbers = {n for gen in reader.xref.values() for n in gen} | set(reader.xref_objStm)
    for n in numbers:
        obj = IndirectObject(n, 0, reader).get_object()
        if not isinstance(obj, StreamObject):
            continue
        filters = _filters(obj)
        if obj.get("/Subtype") == "/Image":
            w, h = int(obj.get("/Width", 0)), int(obj.get("/Height", 0))
            _check_size(w, h)
            if "/FlateDecode" not in filters:
                continue
            if filters == ["/FlateDecode"]:
                bits = 1 if obj.get("/ImageMask") else int(obj.get("/BitsPerComponent", 8))
                space = obj.get("/ColorSpace")
                comps = 3 if space == "/DeviceRGB" else 4 if space == "/DeviceCMYK" else 1
                row = (w * comps * bits + 7) // 8
                if bits == 8:
                    _bounded_flate_image(obj, row * h, h)
                else:
                    _bounded_inflate(obj, row * h + h)
            else:
                _bounded_inflate(obj, _JPEG_IN_FLATE_LIMIT)
        elif "/FlateDecode" in filters:
            _bounded_inflate(obj, _STREAM_INFLATE_LIMIT)


def _render_page(doc, index: int) -> bytes:
    """Render one page the way a PDF viewer shows it, then rebuild it as a PNG."""
    page = doc[index]
    try:
        pw, ph = page.get_size()
        if not (0 < pw < 100_000 and 0 < ph < 100_000):
            raise PhotoRejected("A page in this PDF has an impossible size.")
        scale = MAX_OUTPUT_SIDE / max(pw, ph)
        _check_size(max(1, round(pw * scale)), max(1, round(ph * scale)))
        bitmap = page.render(scale=scale, draw_annots=True, may_draw_forms=False)
        try:
            img = bitmap.to_pil().convert("RGB")  # convert() copies, so the native buffer can go
        finally:
            bitmap.close()
    finally:
        page.close()
    low, high = zip(*img.getextrema())
    if max(high) - min(low) < 8:
        raise _BLANK_PAGE
    out = io.BytesIO()
    img.save(out, format="PNG")
    return reencode_image(out.getvalue(), "PNG")


def _bounded_inflate(x, limit: int) -> bytes:
    """Inflate a Flate stream, refusing it once the output passes `limit` bytes."""
    compressed = getattr(x, "_data", None)
    if not isinstance(compressed, bytes):
        raise PhotoRejected("This PDF image cannot be checked safely.")
    try:
        inflater = zlib.decompressobj()
        decoded = inflater.decompress(compressed, limit + 1)
        if len(decoded) > limit or inflater.unconsumed_tail:
            raise PhotoRejected("This PDF image expands beyond its allowed size.")
        decoded += inflater.flush(limit + 1 - len(decoded))
    except zlib.error as exc:
        raise PhotoRejected("This PDF image could not be decompressed safely.") from exc
    if len(decoded) > limit:
        raise PhotoRejected("This PDF image expands beyond its allowed size.")
    return decoded


def check_pdf(raw: bytes) -> int:
    """Run every structural check on a PDF and return its page count.

    Nothing is rendered here, so a whole upload is checked before any of it
    is read; pages are rendered later, a group at a time (`render_pdf_pages`).
    """
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or "/Encrypt" in reader.trailer:
            raise PhotoRejected("Password-protected PDFs are not accepted.")
        _refuse_active_content(reader, raw)
        count = len(reader.pages)
        if count < 1:
            raise PhotoRejected("This PDF has no pages.")
        _check_streams(reader)
        return count
    except PhotoRejected:
        raise
    except Exception as exc:  # malformed structure: refuse, never half-read
        raise PhotoRejected("This PDF could not be read safely.") from exc


def render_pdf_pages(raw: bytes, start: int, stop: int, count: int) -> list[bytes]:
    """Render pages [start, stop) of a PDF already passed by `check_pdf`.

    The page is rendered as a viewer would show it, so scanned layers, typed
    text, drawn marks and annotations all survive. What is validated is the
    rendered page, not how many images it happens to be built from.
    """
    try:
        with _PDFIUM_LOCK:
            doc = pdfium.PdfDocument(raw)
            try:
                if len(doc) != count:
                    raise PhotoRejected("This PDF could not be read safely.")
                return [_render_page(doc, i) for i in range(start, stop)]
            finally:
                doc.close()
    except PhotoRejected:
        raise
    except Exception as exc:  # a render failure: refuse, never half-read
        raise PhotoRejected("This PDF could not be read safely.") from exc


def pages_from_pdf(raw: bytes) -> list[bytes]:
    """Check a PDF and render every page to a fresh PNG."""
    count = check_pdf(raw)
    return render_pdf_pages(raw, 0, count, count)


# ── Entry points ──────────────────────────────────────────────────────────────

def _image_format(raw: bytes) -> str:
    """The Pillow format of a photo, from its bytes alone; refuses anything else."""
    if raw.startswith(_PNG_SIG):
        return "PNG"
    if raw.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    major, compatible = _ftyp_brands(raw)
    if major in AVIF_BRANDS or (major in HEIF_BRANDS and compatible & AVIF_BRANDS):
        return "AVIF"
    if major in HEIF_BRANDS:
        if not HEIF_DECODER_QUALIFIED:
            raise PhotoRejected("HEIC photos cannot be read. Use JPEG, PNG, or PDF. "
                                "(On an iPhone, Bede's upload button sends a JPEG automatically.)")
        return "HEIF"
    raise PhotoRejected("Pages must be JPEG, PNG, WebP, AVIF or HEIC photos, or a scanned PDF.")


def sanitize_upload(raw: bytes) -> list[tuple[str, bytes]]:
    """One uploaded file -> rebuilt (media_type, bytes) pages."""
    if len(raw) > MAX_PAGE_BYTES:
        raise PhotoRejected("A file is larger than 25 MB; please split it or retake it at a lower resolution.")
    if raw.startswith(b"%PDF-"):
        return [("image/png", p) for p in pages_from_pdf(raw)]
    return [("image/png", reencode_image(raw, _image_format(raw)))]


async def _scan(raw: bytes) -> None:
    try:
        target = parse_scanner_url(settings.practice_scanner_url)  # defence in depth: also checked at boot
    except ScannerUrlRefused as exc:
        raise ScannerUnavailable("The upload scanner address is not a local one, so no upload was sent to it.") from exc
    if target is None:
        return

    async def talk() -> bytes:
        if target[0] == "unix":
            reader, writer = await asyncio.open_unix_connection(target[1])
        else:
            reader, writer = await asyncio.open_connection(target[1], target[2])
        try:
            writer.write(b"zINSTREAM\0")
            for start in range(0, len(raw), 64 * 1024):
                part = raw[start:start + 64 * 1024]
                writer.write(struct.pack(">I", len(part)) + part)
            writer.write(struct.pack(">I", 0))
            await writer.drain()
            return await reader.read(1024)
        finally:
            writer.close()

    try:
        reply = await asyncio.wait_for(talk(), SCAN_TIMEOUT_SECONDS)
    except Exception as exc:  # unreachable, misconfigured or slow: fail CLOSED
        raise ScannerUnavailable("The upload scanner is configured but did not answer.") from exc
    text = reply.strip(b"\0\n ").decode("latin-1")
    if text.endswith("FOUND"):
        raise PhotoRejected("This file was flagged by the upload scanner and was not accepted.")
    if not text.endswith("OK"):
        raise ScannerUnavailable("The upload scanner gave an unexpected answer.")


_slots: asyncio.Semaphore | None = None


async def _bounded(fn, *args):
    """Run a decode job in a worker thread, at most MAX_CONCURRENT_JOBS at once.

    The slot is released when the THREAD finishes, not when the caller gives up,
    so a timed-out or cancelled request cannot let jobs pile up behind it.
    """
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    try:
        await asyncio.wait_for(_slots.acquire(), QUEUE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise UploadBusy("Pages are being checked for other uploads right now; please try again in a moment.") from exc
    slots = _slots
    job = asyncio.ensure_future(asyncio.to_thread(fn, *args))

    def _done(finished):
        slots.release()
        if not finished.cancelled():
            finished.exception()  # mark retrieved; the awaiting caller already saw it

    job.add_done_callback(_done)
    try:
        return await asyncio.wait_for(asyncio.shield(job), PROCESS_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise PhotoRejected("Checking the pages took too long; please use smaller photos.") from exc


def _decode(item: str) -> bytes:
    try:
        raw = base64.b64decode(item, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PhotoRejected("A file is not valid base64 data.") from exc
    if len(raw) > MAX_PAGE_BYTES:
        raise PhotoRejected("A file is larger than 25 MB; please split it or retake it at a lower resolution.")
    return raw


async def page_groups(data_b64: list[str], size: int = READ_GROUP_SIZE, on_total=None):
    """Base64 uploads -> groups of at most `size` rebuilt pages, in upload order.

    Every file is decoded, scanned, typed and (for a PDF) structurally checked
    before the first group is built, so a bad file anywhere refuses the upload
    before any page is read. Pages are then rebuilt one group at a time, and a
    group's images are released once the caller moves to the next.
    """
    if not data_b64:
        raise PhotoRejected("Upload at least one page.")
    files: list[tuple[bytes, int]] = []  # (raw, pdf page count or 0 for a photo)
    total = 0
    for item in data_b64:
        raw = _decode(item)
        total += len(raw)
        if total > MAX_REQUEST_BYTES:
            raise PhotoRejected("These files are too large to send together; please send them in two parts.")
        await _scan(raw)
        if raw.startswith(b"%PDF-"):
            files.append((raw, await _bounded(check_pdf, raw)))
        else:
            _image_format(raw)
            files.append((raw, 0))

    if on_total is not None:
        on_total(sum(count or 1 for _, count in files))
    group: list[tuple[str, str]] = []
    for raw, count in files:
        if count == 0:
            (media, clean), = await _bounded(sanitize_upload, raw)
            group.append((media, base64.b64encode(clean).decode()))
        else:
            start = 0
            while start < count:
                stop = min(count, start + size - len(group))
                for clean in await _bounded(render_pdf_pages, raw, start, stop, count):
                    group.append(("image/png", base64.b64encode(clean).decode()))
                start = stop
                if len(group) == size:
                    yield group
                    group = []
        if len(group) == size:
            yield group
            group = []
    if group:
        yield group


async def prepare_pages(data_b64: list[str]) -> list[tuple[str, str]]:
    """Every rebuilt page of an upload at once. Callers reading many pages use
    `page_groups` instead, which never holds more than one group."""
    return [page async for group in page_groups(data_b64) for page in group]
