#!/usr/bin/env python3
"""Measure real streaming first-token and end-to-end latency on local Ministral.

Diagnostic only. This program does not claim Bede's complete curriculum
prompt, per-turn safety classifier, 30-turn p95, or target Mac hardware.
Requires a locally running, genuinely loaded OpenAI-compatible model service.
"""
import concurrent.futures
import json
import os
import platform
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

URL = os.getenv("BEDE_LOCAL_INFERENCE_URL", "http://127.0.0.1:8080/v1")
MODEL = os.getenv("BEDE_LOCAL_MODEL", "ministral-8b-local")
OUT = Path(os.getenv("BEDE_LATENCY_EVIDENCE", "local-model-evidence/ministral-latency.json"))
url = urlsplit(URL)
if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}:
    raise SystemExit("Local inference only: refusing non-loopback endpoint")
for key in ("OPENAI_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY"):
    if os.environ.get(key):
        raise SystemExit("Paid model API credential present; aborting")

constitution = (Path(__file__).resolve().parents[2] / "docs/CONSTITUTION.md").read_text()
SYSTEM = ("You are Bede, a gentle Socratic tutor. Encourage an original student "
          "answer. Do not invent DIBELS or other learner records. "
          "Honor these Bede principles:\n" + constitution[:2400])
PROMPT = ("I am in fourth grade and cannot understand how multiplication "
          "groups work. Help me reason using 7 groups of 8 without simply "
          "telling me the product.")
CLASSIFIER = ("Classify this synthetic classroom message as safe or needs "
              "adult intervention. Reply SAFE or ESCALATE: " + PROMPT)


def percentile(data, pct):
    if len(data) < 30:
        return None
    items = sorted(data)
    return items[max(0, min(len(items) - 1, (len(items) * pct + 99) // 100 - 1))]


def one_stream(label, system, user):
    request = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": 88,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(
        URL.rstrip("/") + "/chat/completions",
        data=json.dumps(request).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    first = None
    chunk_count = 0
    chars = 0
    usage = None
    try:
        with urllib.request.urlopen(req, timeout=360) as resp:
            for raw in resp:
                if not raw.startswith(b"data:"):
                    continue
                data = raw[5:].strip()
                if data == b"[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("usage"):
                    usage = event["usage"]
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    body = delta.get("content") or ""
                    if body or delta.get("tool_calls"):
                        if first is None:
                            first = time.monotonic() - started
                        chars += len(body)
                        chunk_count += 1
        elapsed = time.monotonic() - started
        generated = (usage or {}).get("completion_tokens")
        return {
            "scenario": label, "status": "OK",
            "first_token_ms": round(first * 1000) if first is not None else None,
            "completion_ms": round(elapsed * 1000),
            "generated_tokens_reported": generated,
            "tokens_per_second": (
                round(generated / (elapsed - first), 2)
                if isinstance(generated, (int, float)) and first is not None
                and elapsed > first else None
            ),
            "text_chars_observed": chars, "stream_chunks": chunk_count,
        }
    except Exception as exc:
        return {"scenario": label, "status": "ERROR", "exception": type(exc).__name__,
                "message": str(exc)[:200],
                "completion_ms": round((time.monotonic() - started) * 1000)}


def main():
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": MODEL, "host": platform.platform(),
        "inference_location": "localhost",
        "qualification": "DIAGNOSTIC_NOT_QUALIFIED",
        "real_bede_prompt_used": False,
        "full_bede_moderation_used": False,
        "hardware_mac_validated": False,
        "model_context_configured": 3072,
        "sample_count_target": 30,
        "samples": [],
    }
    # Model is warmed by prior smoke step. Two serial "classifier + tutor"
    # pipelines quantify the latency cost of 2 model calls per turn.
    for turn in range(2):
        report["samples"].append(one_stream(f"turn{turn+1}_classifier",
                                            "Classify synthetic messages. Reply SAFE or ESCALATE.",
                                            CLASSIFIER))
        report["samples"].append(one_stream(f"turn{turn+1}_tutor", SYSTEM, PROMPT))
    # Submit two parallel requests to quantify queueing under local admission.
    # The CI llama.cpp server uses --parallel 1 on purpose; school concurrency
    # must be measured separately on an appropriate Mac.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(one_stream, f"two_learners_{i+1}",
                               SYSTEM, PROMPT) for i in range(2)]
        report["samples"].extend(f.result() for f in futures)
    successful = [s for s in report["samples"] if s["status"] == "OK"]
    first = [s["first_token_ms"] for s in successful if s.get("first_token_ms") is not None]
    total = [s["completion_ms"] for s in successful]
    report["summary"] = {
        "ok_count": len(successful),
        "error_count": len(report["samples"]) - len(successful),
        "measured_min_complete_ms": min(total) if total else None,
        "measured_max_complete_ms": max(total) if total else None,
        "measured_median_complete_ms": round(statistics.median(total)) if total else None,
        "observed_max_first_token_ms": max(first) if first else None,
        "p95_first_token_ms": percentile(first, 95),
        "p95_complete_ms": percentile(total, 95),
        "p95_applicable": len(successful) >= 30,
        "target_first_token_p95_ms": 10000,
        "target_complete_p95_ms": 45000,
    }
    if len(successful) != len(report["samples"]):
        report["qualification"] = "DIAGNOSTIC_FAILED"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    print("DIAGNOSTIC STREAMING PERFORMANCE:", json.dumps(report["summary"], indent=2), flush=True)
    print("REMAINING: real Bede prompt, >=30 turns, Mac, concurrency, safety/recovery", flush=True)
    return 0 if report["qualification"] != "DIAGNOSTIC_FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
