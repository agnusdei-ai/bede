"""
File validation and hardening for everything a parent uploads to Practice
Coach, before any byte reaches a model. This is hardening, not a guarantee that
a file is free of malware.

* Type is decided from the bytes alone (magic numbers); a filename or declared
  content type is never consulted (the API does not even receive one).
* HEIC/HEIF (iPhone photos) is recognised by its `ftyp` brand and decoded by
  pillow-heif (native libheif) registered with Pillow, then goes through
  exactly the same checks and re-encode as a JPEG or PNG.
* Every image is FULLY DECODED with Pillow and RE-ENCODED to a fresh PNG: the
  header is checked for pixel count before any pixel is decoded, Pillow's own
  decompression-bomb guard is set to the same cap and promoted to an error,
  `verify()` is followed by a real reload, EXIF rotation is applied and then
  every piece of metadata is dropped with the original container, so a
  polyglot's appended payload does not survive.
* A PDF is never rendered. It is parsed with pypdf, refused outright if it is
  encrypted or carries any active-content or attachment marker (JavaScript,
  Launch, embedded files, open actions, forms, rich media, submit/import
  actions), checked across the whole object graph including object streams and
  against hex-escaped names; only the scanned page IMAGES inside it are taken
  out and then re-encoded exactly like an uploaded image. A PDF page that is
  text or vector drawing (no scanned image) is refused.
* Limits: bytes per file, total pages, pixels and side length, decoded memory
  (pixels x channels), PDF object count, a per-upload processing time, and a
  semaphore bounding how many decode jobs run at once.
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
import warnings

import pillow_heif
from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from core.config import settings
from core.scanner_url import ScannerUrlRefused, parse_scanner_url

MAX_PAGE_BYTES = 6 * 1024 * 1024
MAX_PAGES = 6
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

_FORMATS = ("PNG", "JPEG", "HEIF")
HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heif"})


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
    """Fully decode `raw` (a PNG, JPEG or HEIF) and return a brand-new PNG."""
    bad = PhotoRejected("A page is not a valid JPEG, PNG or HEIC image.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(raw), formats=_FORMATS)
            if probe.format != expect:
                raise bad
            _check_size(*probe.size)  # from the header, before any pixel is decoded
            probe.verify()
            img = Image.open(io.BytesIO(raw), formats=_FORMATS)  # verify() leaves the first unusable
            if expect == "JPEG":
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


def image_from_raw(w: int, h: int, channels: int, data: bytes) -> bytes:
    """8-bit gray/RGB pixels from a scanned PDF page -> PNG."""
    _check_size(w, h)
    if len(data) != w * h * channels:
        raise PhotoRejected("A scanned page inside the PDF is in a format that cannot be read.")
    out = io.BytesIO()
    Image.frombytes("L" if channels == 1 else "RGB", (w, h), data).save(out, format="PNG")
    return reencode_image(out.getvalue(), "PNG")


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
            except Exception:
                continue
        if isinstance(obj, str) and obj in FORBIDDEN_PDF_NAMES:
            raise refuse
        if isinstance(obj, DictionaryObject):  # a stream is a dictionary; its data is never read here
            for key, value in obj.items():
                if key in FORBIDDEN_PDF_NAMES:
                    raise refuse
                stack.append(value)
        elif isinstance(obj, ArrayObject):
            stack.extend(obj)


_MARKED_PAGE = PhotoRejected(
    "A page in this PDF has more on it than one scanned picture (typed or drawn marks, comments, notes or a second "
    "image), and anything beyond the picture would be lost. Please photograph or scan the marked-up paper itself, "
    "or print the PDF to an image."
)
_NOT_A_SCAN = PhotoRejected(
    "A page in this PDF is not a scanned photo (text and drawn pages cannot be read here). "
    "Please scan or photograph the paper instead."
)
# Operators that only set state, build or clip a path without painting it, or mark content.
_STATE_OPS = frozenset({
    b"q", b"Q", b"cm", b"gs", b"w", b"J", b"j", b"M", b"d", b"ri", b"i",
    b"g", b"G", b"rg", b"RG", b"k", b"K", b"cs", b"CS", b"sc", b"SC", b"scn", b"SCN",
    b"m", b"l", b"c", b"v", b"y", b"h", b"re", b"W", b"W*", b"n",
    b"BMC", b"BDC", b"EMC", b"MP", b"DP",
})
_TEXT_STATE_OPS = frozenset({b"BT", b"ET", b"Tf", b"Td", b"TD", b"Tm", b"T*", b"Tc", b"Tw", b"Tz", b"TL", b"Ts"})
_TEXT_SHOW_OPS = frozenset({b"Tj", b"TJ", b"'", b'"'})


def _placed_image(page):
    """The ONE image a page draws, after proving nothing else is drawn or annotated.

    Refuses visible text (an invisible OCR layer, text render mode 3, is fine),
    path painting, shadings, inline images, form XObjects, a second image, and
    any annotation other than a plain link. Any parse problem refuses too.
    """
    try:
        for annot in page.get("/Annots") or []:
            if annot.get_object().get("/Subtype") != "/Link":
                raise _MARKED_PAGE
        xobjects = page["/Resources"].get_object()["/XObject"].get_object()
        contents = page.get_contents()
        if contents is None:
            raise _NOT_A_SCAN
        images, render_mode, saved = [], 0, []
        for operands, op in contents.operations:
            if op == b"q":
                saved.append(render_mode)
            elif op == b"Q":
                render_mode = saved.pop() if saved else 0
            if op in _STATE_OPS or op in _TEXT_STATE_OPS:
                continue
            if op == b"Tr":
                render_mode = int(operands[0])
            elif op in _TEXT_SHOW_OPS:
                if render_mode != 3:
                    raise _MARKED_PAGE
            elif op == b"Do":
                target = xobjects[operands[0]].get_object()
                if target.get("/Subtype") != "/Image":
                    raise _MARKED_PAGE
                images.append(target)
            else:  # painting, shading, inline image, type-3 glyph ops, anything unknown
                raise _MARKED_PAGE
        if len(images) > 1:
            raise _MARKED_PAGE
        if not images:
            raise _NOT_A_SCAN
        return images[0]
    except PhotoRejected:
        raise
    except Exception as exc:  # fail closed on any parse problem
        raise _MARKED_PAGE from exc


def _page_image(page) -> bytes:
    x = _placed_image(page)
    w, h = int(x.get("/Width", 0)), int(x.get("/Height", 0))
    _check_size(w, h)
    filt = x.get("/Filter")
    if isinstance(filt, list) and len(filt) == 1:
        filt = filt[0]
    if filt == "/DCTDecode":
        return reencode_image(x.get_data(), "JPEG")
    space = x.get("/ColorSpace")
    if (filt in (None, "/FlateDecode") and space in ("/DeviceGray", "/DeviceRGB")
            and int(x.get("/BitsPerComponent", 0)) == 8 and "/Decode" not in x and not x.get("/ImageMask")):
        return image_from_raw(w, h, 1 if space == "/DeviceGray" else 3, x.get_data())
    raise PhotoRejected("A scanned page in this PDF uses an image format that cannot be read; "
                        "please export the pages as JPEG or PNG photos.")


def pages_from_pdf(raw: bytes, limit: int) -> list[bytes]:
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or "/Encrypt" in reader.trailer:
            raise PhotoRejected("Password-protected PDFs are not accepted.")
        _refuse_active_content(reader, raw)
        count = len(reader.pages)
        if count < 1 or count > limit:
            raise PhotoRejected(f"At most {MAX_PAGES} pages may be uploaded in total.")
        return [_page_image(p) for p in reader.pages]
    except PhotoRejected:
        raise
    except Exception as exc:  # malformed structure: refuse, never half-read
        raise PhotoRejected("This PDF could not be read safely.") from exc


# ── Entry points ──────────────────────────────────────────────────────────────

def sanitize_upload(raw: bytes, room: int) -> list[tuple[str, bytes]]:
    """One uploaded file -> rebuilt (media_type, bytes) pages; at most `room` of them."""
    if len(raw) > MAX_PAGE_BYTES:
        raise PhotoRejected("A file is larger than 6 MB; please retake it at a lower resolution.")
    if raw.startswith(_PNG_SIG):
        return [("image/png", reencode_image(raw, "PNG"))]
    if raw.startswith(b"\xff\xd8\xff"):
        return [("image/png", reencode_image(raw, "JPEG"))]
    if raw[4:8] == b"ftyp" and raw[8:12] in HEIF_BRANDS:
        if not HEIF_DECODER_QUALIFIED:
            raise PhotoRejected("HEIC photos are temporarily unavailable until the image decoder is patched. Please export a JPEG or PNG photo.")
        return [("image/png", reencode_image(raw, "HEIF"))]
    if raw.startswith(b"%PDF-"):
        return [("image/png", p) for p in pages_from_pdf(raw, room)]
    raise PhotoRejected("Pages must be JPEG, PNG or HEIC photos, or a scanned PDF.")


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


async def prepare_pages(data_b64: list[str]) -> list[tuple[str, str]]:
    """Base64 uploads -> [(media_type, base64)] of rebuilt images, ready for the reader."""
    pages: list[tuple[str, str]] = []
    for item in data_b64:
        try:
            raw = base64.b64decode(item, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PhotoRejected("A file is not valid base64 data.") from exc
        if len(raw) > MAX_PAGE_BYTES:
            raise PhotoRejected("A file is larger than 6 MB; please retake it at a lower resolution.")
        await _scan(raw)
        room = MAX_PAGES - len(pages)
        for media, clean in await _bounded(sanitize_upload, raw, room):
            pages.append((media, base64.b64encode(clean).decode()))
    if not pages or len(pages) > MAX_PAGES:
        raise PhotoRejected(f"Upload between 1 and {MAX_PAGES} pages in total.")
    return pages
