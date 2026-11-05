"""A scanned quiz page built the way an office scanner's compact PDF is.

It follows the layout of a real teacher-supplied answer-key scan (a Canon
"compact PDF") without reproducing its content, which belongs to its
publisher and is kept out of this public repository:

* a US Letter page (612 x 792 pt) whose content stream starts with the
  scanner's own comment, ``% CANON_PFINF_TYPE2_TEXTOFF``;
* a full-page 8-bit grayscale background, JPEG compressed and then wrapped
  in Flate (``[/FlateDecode /DCTDecode]``);
* a 1-bit CCITT Group 4 image mask painted in white (``1.000 g``), which
  cleans the paper behind the ink;
* a second 1-bit CCITT Group 4 image mask painted in near-black
  (``0.137 g``) carrying the printed text, boxes and the circled answer.

The text drawn here is neutral: question numbers and arithmetic only.
"""
from __future__ import annotations

import io
import zlib

from PIL import Image, ImageChops, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

PAGE = (612, 792)
# Where each layer sits on the page, in points: (width, height, x, y).
BACKGROUND_BOX = (612.0, 792.0, 0.0, 0.0)
WHITE_MASK_BOX = (510.72, 732.48, 38.40, 12.48)
INK_MASK_BOX = (447.36, 561.60, 69.12, 101.76)
INK_GRAY = 0.137


def _g4(img: Image.Image) -> bytes:
    """The raw CCITT Group 4 strip of a 1-bit image, as a PDF stores it."""
    # libtiff writes a mode-"1" image as min-is-black, whose runs are the
    # opposite of a PDF CCITT filter's default (BlackIs1 false), so invert.
    flipped = ImageChops.invert(img.convert("L")).convert("1")
    out = io.BytesIO()
    flipped.save(out, format="TIFF", compression="group4", tiffinfo={278: img.height})  # one strip
    tiff = out.getvalue()
    tiff_img = Image.open(io.BytesIO(tiff))
    offsets = tiff_img.tag_v2[273]
    counts = tiff_img.tag_v2[279]
    assert len(offsets) == 1, "expected a single strip"
    return tiff[offsets[0]:offsets[0] + counts[0]]


def _mask(writer, img: Image.Image):
    stream = DecodedStreamObject()
    stream._data = _g4(img)
    for key, value in {
        "/Type": NameObject("/XObject"), "/Subtype": NameObject("/Image"),
        "/Width": NumberObject(img.width), "/Height": NumberObject(img.height),
        "/BitsPerComponent": NumberObject(1), "/ImageMask": BooleanObject(True),
        "/Filter": NameObject("/CCITTFaxDecode"),
        "/DecodeParms": DictionaryObject({NameObject("/K"): NumberObject(-1),
                                          NameObject("/Columns"): NumberObject(img.width)}),
    }.items():
        stream[NameObject(key)] = value
    return writer._add_object(stream)


def _background(writer):
    paper = Image.new("L", (425, 550), 236)
    ImageDraw.Draw(paper).rectangle((0, 0, 424, 40), fill=120)  # a printed header band
    jpeg = io.BytesIO()
    paper.save(jpeg, format="JPEG", quality=70)
    stream = DecodedStreamObject()
    stream._data = zlib.compress(jpeg.getvalue())
    for key, value in {
        "/Type": NameObject("/XObject"), "/Subtype": NameObject("/Image"),
        "/Width": NumberObject(paper.width), "/Height": NumberObject(paper.height),
        "/BitsPerComponent": NumberObject(8), "/ColorSpace": NameObject("/DeviceGray"),
        "/Filter": ArrayObject([NameObject("/FlateDecode"), NameObject("/DCTDecode")]),
    }.items():
        stream[NameObject(key)] = value
    return writer._add_object(stream)


def _ink() -> Image.Image:
    """Printed ink: question numbers, answer boxes and one circled answer.

    In a CCITT image a 0 bit is black, and in an image mask a 0 sample is
    painted, so dark strokes on a white field are drawn as 0 here.
    """
    w, h = 746, 936
    ink = Image.new("1", (w, h), 1)
    draw = ImageDraw.Draw(ink)
    for row in range(8):
        y = 30 + row * 110
        draw.ellipse((20, y, 70, y + 50), fill=0)                 # the question-number disc
        draw.rectangle((120, y, 300, y + 60), outline=0, width=6)  # an answer box
        draw.line((20, y + 90, w - 20, y + 90), fill=0, width=3)   # the rule under the row
    draw.ellipse((420, 140, 560, 260), outline=0, width=8)         # a circled answer
    return ink


def build() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(*PAGE)
    white = Image.new("1", (851, 1221), 0)  # every sample painted: a white cleaning layer
    xobjects = {
        NameObject("/Obj4"): _background(writer),
        NameObject("/Obj5"): _mask(writer, white),
        NameObject("/Obj6"): _mask(writer, _ink()),
    }
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject(xobjects),
        NameObject("/ProcSet"): ArrayObject([NameObject(n) for n in ("/PDF", "/Text", "/ImageB", "/ImageC", "/ImageI")]),
    })
    bw, bh, bx, by = BACKGROUND_BOX
    ww, wh, wx, wy = WHITE_MASK_BOX
    iw, ih, ix, iy = INK_MASK_BOX
    content = (
        "% CANON_PFINF_TYPE2_TEXTOFF\n"
        f"q\n{bw:.2f} 0 0 {bh:.2f} {bx:.2f} {by:.2f} cm\n/Obj4 Do\nQ\n"
        f"q\n1.000 g\n{ww:.3f} 0 0 {wh:.2f} {wx:.2f} {wy:.2f} cm\n/Obj5 Do\nQ\n"
        f"q\n{INK_GRAY:.3f} g\n{iw:.2f} 0 0 {ih:.2f} {ix:.2f} {iy:.2f} cm\n/Obj6 Do\nQ\n"
    ).encode()
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def ink_point_on_page(x_frac_in_ink: float, y_frac_in_ink: float) -> tuple[float, float]:
    """Map a point inside the ink layer to a fraction of the page, top-left origin."""
    iw, ih, ix, iy = INK_MASK_BOX
    x = (ix + x_frac_in_ink * iw) / PAGE[0]
    y = 1 - (iy + (1 - y_frac_in_ink) * ih) / PAGE[1]
    return x, y


__all__ = ["build", "ink_point_on_page", "INK_GRAY"]
