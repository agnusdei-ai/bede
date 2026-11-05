"""Unclear pages are read rather than refused (docs/PRACTICE_COACH.md).

Two layers, each tested on its own and through the real reading path:

* a reply that is wrapped in prose, cut off part-way, or carries one bad
  field keeps every question that can be read, and anything repaired is
  marked for the parent to check;
* a group that still cannot be read is sharpened
  (upload_safety.enhance_for_reading) and read once more.

What must NOT loosen: a reply carrying a field the worksheet has no place for
(a name, a school, a date), at any level, is still refused whole.
"""
import base64
import copy
import io
import json

import pytest
from PIL import Image

from services.practice import extract, upload_safety
from tests.test_practice_coach import GOLDEN, StubClient, _Reply, _req, _routing


class SeqClient:
    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.texts.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Reply(item)


def _good() -> dict:
    return copy.deepcopy(GOLDEN["assessment"])


def _count(a) -> int:
    return sum(len(s.items) for s in a.sections)


# ── Repairing a reply ─────────────────────────────────────────────────────────

def test_a_reply_wrapped_in_prose_is_read():
    text = "Here is the worksheet you asked for:\n" + json.dumps(_good()) + "\nLet me know if you need more."
    assert _count(extract.parse_reading(text, "latin")) == _count(extract.parse_reading(json.dumps(_good()), "latin"))


def test_a_reply_cut_off_part_way_keeps_the_questions_already_read():
    full = json.dumps(_good())
    whole = _count(extract.parse_reading(full, "latin"))
    cut = full[: int(len(full) * 0.6)]
    with pytest.raises(json.JSONDecodeError):
        json.loads(cut)
    kept = extract.parse_reading(cut, "latin")
    assert 0 < _count(kept) < whole


def test_closing_a_cut_reply_respects_quotes_and_escapes():
    raw = '{"a": "brace } and \\" quote", "b": [{"c": 1}, {"d": "unfinished'
    assert json.loads(extract._close_json(raw)) == {"a": 'brace } and " quote', "b": [{"c": 1}]}


def test_one_bad_field_is_repaired_and_shown_to_the_parent_not_the_whole_reading_lost():
    data = _good()
    bad = data["sections"][0]["items"][0]
    bad.update(teacher_mark="maybe", confidence=7, diagram={"kind": "not-a-kind"}, stimulus=None)
    reading = extract.parse_reading(json.dumps(data), "latin")
    assert _count(reading) == _count(extract.parse_reading(json.dumps(_good()), "latin"))
    first = reading.sections[0].items[0]
    assert first.teacher_mark == "unmarked"
    assert first.diagram is None
    assert first.needs_parent()  # a repaired reading always waits for the parent


def test_an_item_with_no_question_text_still_gets_a_place():
    data = _good()
    data["sections"][0]["items"][0]["prompt"] = ""
    reading = extract.parse_reading(json.dumps(data), "latin")
    first = reading.sections[0].items[0]
    assert first.prompt and first.needs_parent()


@pytest.mark.parametrize("where", ["top", "section", "item"])
def test_a_name_anywhere_is_still_refused_whole(where):
    data = _good()
    target = {"top": data, "section": data["sections"][0], "item": data["sections"][0]["items"][0]}[where]
    target["student_name"] = "Someone"
    with pytest.raises(extract.ReadingFailed):
        extract.parse_reading(json.dumps(data), "latin")


def test_a_reply_with_nothing_readable_is_refused_with_a_way_forward():
    with pytest.raises(extract.ReadingFailed) as caught:
        extract.parse_reading("I'm sorry, I can't read this image.", "latin")
    message = str(caught.value)
    assert "clearer photos" not in message
    assert "right way up" in message


# ── Sharpening for a second look ──────────────────────────────────────────────

def _faint_page(size=(400, 300)) -> bytes:
    img = Image.new("RGB", size, (150, 150, 150))
    for x in range(40, 360):
        for y in range(140, 150):
            img.putpixel((x, y), (120, 120, 120))  # faint grey ink
    for x in range(40, 80):
        for y in range(40, 80):
            img.putpixel((x, y), (170, 120, 120))  # a faint red mark
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def test_sharpening_enlarges_a_small_page_and_stretches_faint_contrast():
    before = Image.open(io.BytesIO(_faint_page())).convert("L")
    after_png = upload_safety.enhance_for_reading(_faint_page())
    after = Image.open(io.BytesIO(after_png))
    assert max(after.size) == upload_safety.ENHANCE_LONG_SIDE
    lo, hi = before.getextrema()
    lo2, hi2 = after.convert("L").getextrema()
    assert (hi2 - lo2) > 2 * (hi - lo)


def test_sharpening_keeps_a_red_mark_red():
    after = Image.open(io.BytesIO(upload_safety.enhance_for_reading(_faint_page()))).convert("RGB")
    scale = after.size[0] / 400
    r, g, b = after.getpixel((int(60 * scale), int(60 * scale)))
    assert r > g + 20 and r > b + 20


def test_sharpening_never_passes_the_page_size_cap():
    big = Image.new("RGB", (upload_safety.MAX_OUTPUT_SIDE, 2000), (200, 200, 200))
    out = io.BytesIO()
    big.save(out, "PNG")
    after = Image.open(io.BytesIO(upload_safety.enhance_for_reading(out.getvalue())))
    assert max(after.size) <= upload_safety.MAX_OUTPUT_SIDE


# ── Through the real reading path ─────────────────────────────────────────────

def _images(call) -> list[str]:
    return [b["source"]["data"] for b in call["messages"][0]["content"] if b["type"] == "image"]


@pytest.mark.asyncio
async def test_a_page_that_cannot_be_read_gets_a_sharpened_second_look(monkeypatch):
    local = SeqClient("I can't make this out.", json.dumps(_good()))
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    reading = await extract.read_pages(_req())
    assert _count(reading) > 0
    assert len(local.calls) == 2
    assert _images(local.calls[0]) != _images(local.calls[1])  # the second look sends the sharpened copy
    assert "sharpened" in local.calls[1]["messages"][0]["content"][-1]["text"]
    assert "blurry" in local.calls[0]["system"]  # the reader is told to read unclear pages anyway


@pytest.mark.asyncio
async def test_the_second_look_is_charged_on_the_demo(monkeypatch):
    local = SeqClient("no", json.dumps(_good()))
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    charged = []

    async def charge():
        charged.append(1)

    await extract.read_pages(_req(), before_call=charge)
    assert len(charged) == 2 == len(local.calls)


@pytest.mark.asyncio
async def test_a_clear_reply_is_read_once(monkeypatch):
    local = StubClient(json.dumps(_good()))
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    await extract.read_pages(_req())
    assert len(local.calls) == 1


@pytest.mark.asyncio
async def test_a_provider_error_is_not_retried_as_an_unclear_page(monkeypatch):
    local = SeqClient(RuntimeError("down"), json.dumps(_good()))
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    with pytest.raises(extract.ReadingFailed) as caught:
        await extract.read_pages(_req())
    assert len(local.calls) == 1
    assert "right now" in str(caught.value)


@pytest.mark.asyncio
async def test_two_unreadable_replies_end_in_a_way_forward_not_a_third_call(monkeypatch):
    local = SeqClient("no", "still no", json.dumps(_good()))
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    with pytest.raises(extract.ReadingFailed) as caught:
        await extract.read_pages(_req())
    assert len(local.calls) == 2
    assert "right way up" in str(caught.value)


@pytest.mark.asyncio
async def test_a_name_in_the_second_look_is_still_refused(monkeypatch):
    bad = {**_good(), "student_name": "Someone"}
    local = SeqClient("no", json.dumps(bad))
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    with pytest.raises(extract.ReadingFailed):
        await extract.read_pages(_req())


def test_the_sharpened_pages_are_built_only_from_the_rebuilt_page():
    """enhance_group takes the (media, base64) pages page_groups produced and
    nothing else, so no original upload byte or metadata can reach it."""
    import inspect

    params = list(inspect.signature(upload_safety.enhance_group).parameters)
    assert params == ["group"]
    page = ("image/png", base64.b64encode(_faint_page()).decode())
    import asyncio
    out = asyncio.run(upload_safety.enhance_group([page]))
    assert out[0][0] == "image/png" and Image.open(io.BytesIO(base64.b64decode(out[0][1]))).format == "PNG"
