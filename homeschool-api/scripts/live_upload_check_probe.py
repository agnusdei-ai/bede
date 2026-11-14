#!/usr/bin/env python3
"""Check, against a live deployment, that uploaded pictures are checked before
Bede reads them (services/content_screen.py).

Run by hand from `.github/workflows/live-upload-check.yml` (workflow_dispatch
only). It spends a few model calls on the public demo, so it never runs on a
schedule.

**Synthetic pictures only.** It draws four harmless pictures with Pillow:

* a marked arithmetic worksheet       -> expected to pass and be read
* a video-game "GAME OVER" screen     -> expected: refused as not schoolwork
* a child's drawing of a tree         -> expected to reach the tutor
* the same game screen, in the chat   -> expected: the gentle lesson refusal

It never sends, and must never be changed to send, harmful imagery. The
self-harm and sexual-content paths are tested with mocked safety responses in
`tests/test_content_screen.py`, which is the only honest way to test them.

What a green run shows: the deployment answering at `--api` refuses an
off-topic picture before reading it and lets ordinary schoolwork through.
What it cannot show: which commit is deployed (read that from GitHub's
deployment record), or how the checker judges any other picture. The verdict
is a model's judgement, so an unexpected result is reported, not hidden.

Prints one JSON report to stdout and exits 0 only if every expectation held.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont

UA = "bede-live-upload-check/1"


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _png(img: Image.Image) -> str:
    out = io.BytesIO()
    img.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def worksheet() -> str:
    img = Image.new("RGB", (1000, 1300), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 50), "Week 3 Maths Check", fill="black", font=_font(48))
    d.text((60, 120), "Add. Show your answer.", fill="black", font=_font(30))
    rows = [("1.  7 + 5 =", "12", True), ("2.  9 + 4 =", "13", True), ("3.  6 + 8 =", "15", False)]
    y = 220
    for prompt, answer, right in rows:
        d.text((80, y), prompt, fill="black", font=_font(44))
        d.text((420, y), answer, fill=(30, 30, 160), font=_font(44))
        if right:  # a red tick
            d.line([(560, y + 25), (585, y + 50), (630, y - 5)], fill="red", width=6)
        else:  # a red cross and the correction
            d.line([(560, y), (610, y + 50)], fill="red", width=6)
            d.line([(610, y), (560, y + 50)], fill="red", width=6)
            d.text((650, y), "14", fill="red", font=_font(44))
        y += 140
    return _png(img)


def game_screen() -> str:
    img = Image.new("RGB", (1000, 700), (10, 10, 30))
    d = ImageDraw.Draw(img)
    for i in range(12):  # pixel blocks along the floor
        d.rectangle([i * 85, 600, i * 85 + 70, 660], fill=(40, 180, 60))
    d.rectangle([450, 520, 510, 600], fill=(230, 200, 40))  # a sprite
    d.text((260, 180), "GAME OVER", fill=(250, 60, 60), font=_font(110))
    d.text((340, 340), "SCORE 004200", fill="white", font=_font(50))
    d.text((360, 420), "PRESS START", fill=(200, 200, 255), font=_font(44))
    return _png(img)


def tree_drawing() -> str:
    img = Image.new("RGB", (900, 900), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([410, 520, 490, 820], fill=(120, 80, 40))  # trunk
    d.ellipse([250, 220, 650, 600], fill=(60, 160, 70))  # leaves
    d.ellipse([700, 60, 820, 180], fill=(250, 210, 60))  # sun
    d.line([(0, 820), (900, 820)], fill=(90, 140, 60), width=8)  # ground
    d.text((60, 840), "my oak tree", fill="black", font=_font(36))
    return _png(img)


def _call(api: str, path: str, body: dict | None, token: str | None = None, timeout: int = 180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api.rstrip("/") + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def _detail(text: str) -> str:
    try:
        detail = json.loads(text).get("detail")
    except ValueError:
        return text[:300]
    return detail if isinstance(detail, str) else json.dumps(detail)[:300]


def _chat_text(sse: str) -> str:
    parts = []
    for line in sse.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            item = json.loads(line[5:].strip())
        except ValueError:
            continue
        if item.get("type") == "text":
            parts.append(item.get("content", ""))
    return "".join(parts).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True, help="the deployment's API origin")
    args = ap.parse_args()

    report: dict = {"api": args.api, "checks": [], "ok": True}

    def record(name: str, ok: bool, observed: str) -> None:
        report["checks"].append({"name": name, "ok": ok, "observed": observed[:400]})
        report["ok"] = report["ok"] and ok

    status, text = _call(args.api, "/auth/demo-code", {"student_name": "Synthetic", "grade": "3"})
    if status != 200:
        record("demo session", False, f"{status} {text[:200]}")
        print(json.dumps(report, indent=2))
        return 1
    code = json.loads(text)["code"]
    status, text = _call(args.api, "/auth/login", {"role": "demo_code", "credential": code})
    if status != 200:
        record("demo login", False, f"{status} {text[:200]}")
        print(json.dumps(report, indent=2))
        return 1
    token = json.loads(text)["access_token"]

    def read(image: str):
        body = {"subject": "mathematics", "pages": [{"data": image}], "route": "cloud", "cloud_consent": True}
        return _call(args.api, "/practice/demo/read", body, token)

    status, text = read(worksheet())
    sections = len(json.loads(text).get("assessment", {}).get("sections", [])) if status in (200, 201) else 0
    record("worksheet passes the check and is read", status in (200, 201) and sections > 0,
           f"{status} sections={sections}" if status in (200, 201) else f"{status} {_detail(text)}")

    status, text = read(game_screen())
    detail = _detail(text)
    record("off-topic upload refused before reading", status == 422 and "schoolwork" in detail.lower(),
           f"{status} {detail}")

    def chat(image: str):
        body = {
            "session_config": {"student_name": "Synthetic", "grade": "3", "grade_stage": "core_mastery"},
            "current_subject": "nature_study",
            "conversation_history": [],
            "child_message": "Look at my picture!",
            "drawing_image": image,
        }
        return _call(args.api, "/tutor/chat", body, token)

    status, sse = chat(tree_drawing())
    said = _chat_text(sse)
    refused = any(m in said for m in ("part of your lesson", "can't look at that picture",
                                      "can't use that picture", "couldn't check"))
    record("lesson drawing reaches the tutor", status == 200 and bool(said) and not refused, f"{status} {said}")

    time.sleep(2)
    status, sse = chat(game_screen())
    said = _chat_text(sse)
    record("off-topic lesson picture gets the gentle refusal", status == 200 and "part of your lesson" in said,
           f"{status} {said}")

    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
