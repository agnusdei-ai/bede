#!/usr/bin/env python3
"""Pilot workflow check for small and private-endpoint language models.

Run by hand, never in CI or pytest. It needs a model server you already run
(Ollama or any OpenAI-compatible server) and downloads nothing. Where
scripts/spanish_local_model_probe.py asks "does the model tutor in Spanish",
this asks the questions the English pilot depends on:

  * tutor_tool_call     - Bede's real tutor prompt and real tool list: does the
                          model make a valid call to a tool Bede has?
  * quiz_draft          - the REAL teacher quiz drafter (services/practice/
                          generate.generate, local_only=True): draft, the
                          in-code answer checks, and the independent
                          cross-check. A model that cannot return the JSON
                          shape fails here, as it would for a teacher.
  * quiz_read_text      - the REAL quiz reader on a typed quiz.
  * quiz_read_picture   - the same reader on a rendered picture of a quiz page.
                          A model with no vision answers an error; that is
                          reported as NO_VISION, which is a finding about the
                          model (photo upload would not work on it), not a
                          failure of Bede.

Endpoints. The pilot is local-only, with room for a private network model
server (an OpenAI-compatible endpoint on the school's own network). So the
endpoint must be a loopback address, or, with --allow-private, a private
address (10/8, 172.16/12, 192.168/16, link-local, or a .local/.lan/.internal
host name). A public host is always refused, and the run refuses to start
while a paid provider key is set, so nothing here can reach a cloud service.

These are machine checks: PASS still needs a person to read the report.
A model that is not served, an endpoint that does not answer, or an error is
NOT_RUN or ERROR, never a pass.

Usage (from homeschool-api/):

    python3 scripts/slm_pilot_probe.py --models granite3.3:2b ministral-3:3b
    python3 scripts/slm_pilot_probe.py --url http://10.0.0.5:8000/v1 \
        --allow-private --models my-private-model

Writes docs/local-model-probes/slm-pilot-<UTC>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import ipaddress
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
API_ROOT = HERE.parent
REPO_ROOT = API_ROOT.parent
sys.path.insert(0, str(API_ROOT))

DEFAULT_URL = "http://127.0.0.1:11434/v1"
PAID_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY")
_PRIVATE_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa")

QUIZ_TEXT = (
    "Fractions quiz\n"
    "1. Which fraction is larger? (a) 1/2  (b) 1/4  (c) 1/8\n"
    "2. True or false: 3/4 is greater than 1/2.\n"
    "3. What is 1/2 + 1/4? Write your answer as a fraction.\n"
)


def endpoint_allowed(url: str, allow_private: bool) -> tuple[bool, str]:
    """Is this endpoint one the pilot permits? Pure, so it is unit-tested."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return False, "not an http(s) URL"
    if host in ("localhost", "::1") or host.startswith("127."):
        return True, "loopback"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if allow_private and host.endswith(_PRIVATE_SUFFIXES):
            return True, "private host name"
        return False, "a public or unrecognized host name"
    if allow_private and (ip.is_private or ip.is_link_local) and not ip.is_loopback:
        return True, "private address"
    if ip.is_loopback:
        return True, "loopback"
    return False, "a private address needs --allow-private" if ip.is_private else "a public address"


def valid_tool_call(calls: list[dict], tool: str, schemas: dict[str, dict]) -> bool:
    schema = schemas.get(tool)
    for call in calls:
        args = call.get("input")
        if call.get("name") != tool or schema is None or not isinstance(args, dict):
            continue
        required = schema.get("input_schema", {}).get("required", [])
        if all(args.get(k) not in (None, "", [], {}) for k in required):
            return True
    return False


def render_quiz_page() -> str | None:
    """A PNG of the typed quiz, base64, or None when Pillow is missing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    image = Image.new("RGB", (900, 360), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=26)
    except Exception:
        font = ImageFont.load_default()
    y = 20
    for line in QUIZ_TEXT.strip().splitlines():
        draw.text((24, y), line, fill="black", font=font)
        y += 48
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _case(entry: dict, case_id: str, started: float, **fields) -> None:
    entry["cases"].append({"id": case_id, "seconds": round(time.monotonic() - started, 2), **fields})
    print(f"  {entry['model']} {case_id}: {fields.get('status')}", flush=True)


async def run(url: str, models: list[str], allow_private: bool, out: Path) -> int:
    ok, why = endpoint_allowed(url, allow_private)
    if not ok:
        raise SystemExit(f"Refusing to run: {why}.")
    if any(os.environ.get(k) for k in PAID_KEYS):
        raise SystemExit("Refusing to run: unset the paid provider keys (" + ", ".join(PAID_KEYS) + ").")
    os.environ["LOCAL_LLM_BASE_URL"] = url
    os.environ["BEDE_FORCE_ADAPTER"] = "local"
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://probe:probe@127.0.0.1/unused")

    from core.config import settings
    from models.practice import ExtractQuizRequest, GenerateQuizRequest, PhotoPage
    from models.schemas import GradeStage, SessionConfig, Subject
    from services import ai_service
    from services.adapters.openai_compatible_adapter import OpenAICompatibleClient
    from services.practice import extract, generate, teacher_quiz

    schemas = {t["name"]: t for t in ai_service.TUTOR_TOOLS}
    page = render_quiz_page()
    report: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": url, "endpoint_kind": why,
        "note": "Machine checks only. A PASS needs a person to read the report.",
        "models": [],
    }
    probe = OpenAICompatibleClient(base_url=url, api_key="not-needed", model="")
    try:
        installed = [m.id for m in (await probe._openai.models.list()).data]
    except Exception:
        installed = []
    report["served_models"] = installed

    for model in models:
        entry: dict = {"model": model, "cases": []}
        report["models"].append(entry)
        if model not in installed:
            entry["status"] = "NOT_RUN"
            entry["reason"] = "model is not served at this endpoint"
            print(f"{model}: NOT_RUN (not served)", flush=True)
            continue
        settings.local_llm_model = model
        client = OpenAICompatibleClient(base_url=url, api_key="not-needed", model=model)

        # 1. Tutor tool call, with Bede's real prompt and tools.
        started = time.monotonic()
        try:
            config = SessionConfig(student_name="Ana", grade="4", grade_stage=GradeStage.core_mastery,
                                   subjects=[Subject.mathematics])
            system = [
                {"type": "text", "text": ai_service._build_static_prompt(config, "en")},
                {"type": "text", "text": await ai_service._build_subject_prompt(
                    config, Subject.mathematics, locale="en", local_date=datetime.now().date())},
            ]
            message = await client.messages.create(
                model=model, system=system, max_tokens=400, temperature=0, tools=ai_service.TUTOR_TOOLS,
                tool_choice={"type": "tool", "name": "offer_socratic_hint"},
                messages=[{"role": "user", "content": "I got 36 divided by 4 wrong again. Give me a hint please."}])
            calls = [{"name": b.name, "input": b.input} for b in message.content
                     if getattr(b, "type", "") == "tool_use"]
            good = valid_tool_call(calls, "offer_socratic_hint", schemas)
            _case(entry, "tutor_tool_call", started, status="PASS" if good else "FAIL", tool_calls=calls)
        except Exception as exc:
            _case(entry, "tutor_tool_call", started, status="ERROR", error=f"{type(exc).__name__}: {str(exc)[:300]}")

        # 2. The real quiz drafter.
        started = time.monotonic()
        try:
            req = GenerateQuizRequest(subject="mathematics", grade="3", question_count=5,
                                      focus="multiplication facts for 6, 7, 8 and 9")
            quiz, meta = await generate.generate(req, local_only=True)
            n = len(quiz.questions)
            _case(entry, "quiz_draft", started, status="PASS" if n >= 3 else "FAIL",
                  questions=n, requested=5, meta={k: meta[k] for k in list(meta)[:8]})
        except (generate.QuizFailed, generate.QuizRefused) as exc:
            _case(entry, "quiz_draft", started, status="FAIL", error=str(exc)[:300])
        except Exception as exc:
            _case(entry, "quiz_draft", started, status="ERROR", error=f"{type(exc).__name__}: {str(exc)[:300]}")

        # 3. The real quiz reader on typed text.
        started = time.monotonic()
        try:
            quiz = await teacher_quiz.extract_quiz(
                ExtractQuizRequest(subject="mathematics", grade="4", source_text=QUIZ_TEXT))
            n = len(quiz.questions)
            _case(entry, "quiz_read_text", started, status="PASS" if n == 3 else "FAIL", questions=n, expected=3)
        except Exception as exc:
            _case(entry, "quiz_read_text", started, status="ERROR", error=f"{type(exc).__name__}: {str(exc)[:300]}")

        # 4. The same reader on a picture of the page.
        started = time.monotonic()
        if page is None:
            _case(entry, "quiz_read_picture", started, status="NOT_RUN", reason="Pillow is not installed")
        else:
            try:
                quiz = await teacher_quiz.extract_quiz(ExtractQuizRequest(
                    subject="mathematics", grade="4", pages=[PhotoPage(data=page)], upload_consent=True))
                n = len(quiz.questions)
                _case(entry, "quiz_read_picture", started, status="PASS" if n == 3 else "FAIL",
                      questions=n, expected=3)
            except (extract.ReadingUnavailable, generate.QuizRefused) as exc:
                _case(entry, "quiz_read_picture", started, status="NO_VISION", error=str(exc)[:300])
            except Exception as exc:
                text = f"{type(exc).__name__}: {str(exc)[:300]}"
                vision = any(w in text.lower() for w in ("image", "vision", "multimodal"))
                _case(entry, "quiz_read_picture", started, status="NO_VISION" if vision else "ERROR", error=text)

        statuses = {c["status"] for c in entry["cases"]}
        entry["status"] = "PASS_NEEDS_HUMAN_REVIEW" if statuses == {"PASS"} else (
            "PARTIAL" if "PASS" in statuses else "FAIL")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Report:", out, flush=True)
    return 0 if all(m.get("status") == "PASS_NEEDS_HUMAN_REVIEW" for m in report["models"]) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=os.environ.get("BEDE_OLLAMA_OPENAI_URL", DEFAULT_URL))
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--allow-private", action="store_true",
                        help="accept a private-network endpoint (never a public one)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "docs" / "local-model-probes" / f"slm-pilot-{stamp}.json")
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.models, args.allow_private, args.out))


if __name__ == "__main__":
    sys.exit(main())
