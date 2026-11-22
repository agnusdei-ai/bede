#!/usr/bin/env python3
"""Spanish tutoring check for the local models the installers pull.

Run by hand or by .github/workflows/local-model-pull-probe.yml (the one CI
job the owner allowed to download models, 2026-11-21); never in pytest. It
needs the models downloaded and a running Ollama. docs/DECISIONS.md
entry 43 records why these models are the defaults and what this check
has and has not shown.

What it does: for each model, it builds Bede's REAL tutoring prompt for a
Spanish (es) session (`_build_static_prompt` + `_build_subject_prompt`,
the constitution included) and Bede's REAL tool list (`TUTOR_TOOLS`), and
sends a short set of Spanish child messages through Bede's own
OpenAI-compatible adapter (`services/adapters/openai_compatible_adapter.py`)
to Ollama's OpenAI-compatible endpoint. One case forces a tool call. For
each answer it records three things:

  * stays_in_spanish   - the reply reads as Spanish (Spanish function words
                         outnumber English ones), including any tool text.
  * valid_tool_call    - for the tool case: a tool Bede actually has, with
                         every required field present and non-empty.
  * no_english_mixed   - no English function words appear at all.

These are word-list checks, so a PASS still needs a person to read the
transcript, and the report says so. A model that is not installed, an
endpoint that does not answer, or an error is reported as NOT_RUN or ERROR,
never as a pass. The bar is the same for every model, the small ones
included.

Usage (from homeschool-api/, with Ollama running on this computer):

    ollama pull granite3.3:2b        # and the other models you want checked
    python3 scripts/spanish_local_model_probe.py
    python3 scripts/spanish_local_model_probe.py --models ministral-3:3b granite3.3:8b

Only a loopback endpoint is accepted, and the run refuses to start while a
paid provider key is set, so nothing here can reach a cloud service.
Writes a JSON report (default: docs/local-model-probes/spanish-<UTC>.json).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
API_ROOT = HERE.parent
REPO_ROOT = API_ROOT.parent
sys.path.insert(0, str(API_ROOT))

DEFAULT_URL = "http://127.0.0.1:11434/v1"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PAID_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY")

# The default lineup the installers pull (packaging/unix/install.sh's
# ollama_model_for_tier, default family). tests/test_local_model_default.py
# checks this list against the installers, so it cannot drift.
DEFAULT_LINEUP = (
    "mistral-small3.2:24b",
    "ministral-3:14b",
    "granite3.3:8b",
    "ministral-3:3b",
    "granite3.3:2b",
)

# Short Spanish tutoring prompts. Each names the subject and grade so the
# real subject prompt is built for it. `force_tool` makes the model call
# that tool, which is how "makes a valid tool call" is tested on every model.
CASES = (
    {
        "id": "math-socratic",
        "subject": "mathematics",
        "grade": "3",
        "message": "No entiendo cuánto es 7 por 8. ¿Me ayudas?",
        "force_tool": None,
    },
    {
        "id": "nature-observation",
        "subject": "nature_study",
        "grade": "2",
        "message": "Hoy vi una oruga verde en una hoja del jardín.",
        "force_tool": None,
    },
    {
        "id": "history-narration",
        "subject": "history",
        "grade": "5",
        "message": "Ya terminé de leer sobre los romanos y sus caminos.",
        "force_tool": None,
    },
    {
        "id": "math-hint-tool",
        "subject": "mathematics",
        "grade": "4",
        "message": "Me equivoqué otra vez con 36 dividido entre 4. Dame una pista, por favor.",
        "force_tool": "offer_socratic_hint",
    },
)

# Common function words. Lower-cased whole-word matches only. English words
# that are also Spanish words ("a", "no", "me", "con"...) are left out of the
# English list on purpose.
_ES_WORDS = frozenset(
    "el la los las un una unos unas de del que y en es por para con qué cómo "
    "cuánto cuántos dónde por qué muy pero tu tú su sus mi nos lo le se al "
    "este esta eso esto también puedes crees piensas vamos hay".split()
)
_EN_WORDS = frozenset(
    "the and you what is are this that with your how why where let's lets "
    "great think about would could can it's have do does was were".split()
)
_WORD = re.compile(r"[a-záéíóúüñ']+", re.IGNORECASE)


def language_counts(text: str) -> tuple[int, int, list[str]]:
    words = [w.lower() for w in _WORD.findall(text or "")]
    es = sum(1 for w in words if w in _ES_WORDS)
    en_found = [w for w in words if w in _EN_WORDS]
    return es, len(en_found), sorted(set(en_found))


def judge(text: str, tool_calls: list[dict], force_tool: str | None,
          tool_schemas: dict[str, dict]) -> dict:
    """Apply the three checks to one answer. Pure, so it is unit-testable."""
    tool_text = " ".join(
        str(v) for call in tool_calls for v in (call.get("input") or {}).values()
        if isinstance(v, str)
    )
    combined = f"{text} {tool_text}".strip()
    es, en, en_words = language_counts(combined)
    result = {
        "stays_in_spanish": bool(combined) and es > en,
        "no_english_mixed": bool(combined) and en == 0,
        "english_words_found": en_words,
        "spanish_word_count": es,
    }
    if force_tool:
        def filled(value) -> bool:
            if isinstance(value, str):
                return bool(value.strip())
            return value not in (None, [], {})

        valid = False
        for call in tool_calls:
            schema = tool_schemas.get(call.get("name"))
            args = call.get("input")
            if call.get("name") != force_tool or schema is None or not isinstance(args, dict):
                continue
            required = schema.get("input_schema", {}).get("required", [])
            if all(filled(args.get(k)) for k in required):
                valid = True
        result["valid_tool_call"] = valid
    else:
        result["valid_tool_call"] = None  # not asked for in this case
    checks = [result["stays_in_spanish"], result["no_english_mixed"]]
    if force_tool:
        checks.append(result["valid_tool_call"])
    result["status"] = "PASS_NEEDS_HUMAN_REVIEW" if all(checks) else "FAIL"
    return result


def _require_loopback(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK:
        raise SystemExit("Refusing to run: only a loopback http endpoint is allowed.")
    if any(os.environ.get(k) for k in PAID_KEYS):
        raise SystemExit("Refusing to run: unset the paid provider keys ("
                         + ", ".join(PAID_KEYS) + ") for this check.")


async def _installed_models(client) -> list[str]:
    try:
        listing = await client._openai.models.list()
        return [m.id for m in listing.data]
    except Exception:
        return []


async def run(url: str, models: list[str], out: Path) -> int:
    _require_loopback(url)
    # The adapter router reads settings at import; point it at the probe's
    # own endpoint so nothing else is ever configured.
    os.environ["LOCAL_LLM_BASE_URL"] = url
    os.environ["BEDE_FORCE_ADAPTER"] = "local"
    # The settings module needs a database URL to import; this check never
    # opens a database connection, so a placeholder is enough.
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://probe:probe@127.0.0.1/unused")

    from models.schemas import GradeStage, SessionConfig, Subject
    from services import ai_service
    from services.adapters.openai_compatible_adapter import OpenAICompatibleClient

    tools = ai_service.TUTOR_TOOLS
    schemas = {t["name"]: t for t in tools}
    stage_for = {"2": GradeStage.foundations, "3": GradeStage.core_mastery,
                 "4": GradeStage.core_mastery, "5": GradeStage.core_mastery}

    report: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": url,
        "locale": "es",
        "prompt": "real _build_static_prompt + _build_subject_prompt, locale es",
        "tools": "real TUTOR_TOOLS",
        "note": "Word-list checks only. A PASS needs a person to read the transcript.",
        "models": [],
    }
    probe_client = OpenAICompatibleClient(base_url=url, api_key="not-needed", model="")
    installed = await _installed_models(probe_client)
    report["installed_models"] = installed

    for model in models:
        entry: dict = {"model": model, "cases": []}
        report["models"].append(entry)
        if model not in installed:
            entry["status"] = "NOT_RUN"
            entry["reason"] = "model not installed in this Ollama (ollama pull " + model + ")"
            print(f"{model}: NOT_RUN (not installed)", flush=True)
            continue
        client = OpenAICompatibleClient(base_url=url, api_key="not-needed", model=model)
        for case in CASES:
            subject = Subject(case["subject"])
            config = SessionConfig(
                student_name="Ana", grade=case["grade"],
                grade_stage=stage_for[case["grade"]], subjects=[subject],
            )
            system = [
                {"type": "text", "text": ai_service._build_static_prompt(config, "es")},
                {"type": "text", "text": await ai_service._build_subject_prompt(
                    config, subject, locale="es", local_date=date.today())},
            ]
            kwargs = {
                "model": model, "system": system, "max_tokens": 400,
                "messages": [{"role": "user", "content": case["message"]}],
                "tools": tools, "temperature": 0,
            }
            if case["force_tool"]:
                kwargs["tool_choice"] = {"type": "tool", "name": case["force_tool"]}
            started = time.monotonic()
            try:
                message = await client.messages.create(**kwargs)
            except Exception as exc:
                entry["cases"].append({
                    "id": case["id"], "status": "ERROR",
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                })
                print(f"{model} {case['id']}: ERROR {type(exc).__name__}", flush=True)
                continue
            text = "".join(getattr(b, "text", "") for b in message.content
                           if getattr(b, "type", "") == "text")
            calls = [{"name": b.name, "input": b.input} for b in message.content
                     if getattr(b, "type", "") == "tool_use"]
            verdict = judge(text, calls, case["force_tool"], schemas)
            entry["cases"].append({
                "id": case["id"], "message": case["message"],
                "seconds": round(time.monotonic() - started, 2),
                "text": text[:1500], "tool_calls": calls, **verdict,
            })
            print(f"{model} {case['id']}: {verdict['status']}", flush=True)
        statuses = {c["status"] for c in entry["cases"]}
        entry["status"] = ("PASS_NEEDS_HUMAN_REVIEW"
                           if statuses == {"PASS_NEEDS_HUMAN_REVIEW"} else "FAIL")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Report:", out, flush=True)
    return 0 if all(m.get("status") == "PASS_NEEDS_HUMAN_REVIEW" for m in report["models"]) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=os.environ.get("BEDE_OLLAMA_OPENAI_URL", DEFAULT_URL))
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_LINEUP))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "docs" / "local-model-probes" / f"spanish-{stamp}.json")
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.models, args.out))


if __name__ == "__main__":
    sys.exit(main())
