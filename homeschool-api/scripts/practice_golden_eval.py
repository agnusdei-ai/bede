#!/usr/bin/env python3
"""Run by hand: read your own photos of a golden quiz and compare the reading
with its hand-typed fixture (docs/PRACTICE_COACH.md, "Golden tests").

The photos stay on your machine. They are never committed, because a golden
quiz is a real child's graded work. Run from homeschool-api/ with the same
environment the API uses, so the reading goes where the household's own
configuration sends it:

    python scripts/practice_golden_eval.py latin latin_quiz_1 page1.jpg page2.jpg [--cloud]

--cloud consents to the household's configured AI provider for this run;
without it only a local model is used. Exits non-zero on any mismatch.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.practice import GradedAssessment, PhotoPage, ReadPhotosRequest  # noqa: E402
from services.practice import extract  # noqa: E402
from services.practice.core_checks import normalize  # noqa: E402


def _items(a: GradedAssessment) -> dict:
    return {f"{s.label} #{i.number}": i for s in a.sections for i in s.items}


async def main(argv: list[str]) -> int:
    cloud = "--cloud" in argv
    args = [a for a in argv if a != "--cloud"]
    if len(args) < 3:
        print(__doc__)
        return 2
    pack, fixture, *photos = args
    root = Path(__file__).resolve().parents[1] / "services/practice/packs" / pack / "golden"
    expected = GradedAssessment.model_validate(
        json.loads((root / f"{fixture}.expected.json").read_text(encoding="utf-8"))["assessment"]
    )
    req = ReadPhotosRequest(
        subject=pack,
        pages=[PhotoPage(data=base64.b64encode(Path(p).read_bytes()).decode()) for p in photos],
        route="cloud" if cloud else "local",
        cloud_consent=cloud,
    )
    got = await extract.read_pages(req)

    failures = []
    want_items, got_items = _items(expected), _items(got)
    for ref, want in want_items.items():
        have = got_items.get(ref)
        if have is None:
            failures.append(f"{ref}: not read")
            continue
        if have.teacher_mark != want.teacher_mark:
            failures.append(f"{ref}: mark {have.teacher_mark!r}, expected {want.teacher_mark!r}")
        if want.needs_parent():
            if not have.needs_parent():
                failures.append(f"{ref}: read confidently, but the photo does not settle it")
        elif normalize(have.student_response) != normalize(want.student_response):
            failures.append(f"{ref}: read {have.student_response!r}, expected {want.student_response!r}")
    for line in failures:
        print("FAIL", line)
    print(f"{len(want_items) - len(failures)}/{len(want_items)} items matched")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
