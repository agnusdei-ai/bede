"""Live latency probe for services/streaming_transcription.py, run against a
REAL running instance over real HTTP — not the mocked unit tests in
tests/test_streaming_transcription.py / tests/test_transcription.py, which
prove correctness but never measure timing against a real faster-whisper
model doing real inference.

This exists because docs/VOICE_SETUP.md's "Troubleshooting: 'Transcribing…'
sits for a while after releasing the mic" section documents a real,
previously-reported production symptom (concurrent voice-stream sessions on
one host thrashing CPU, each transcription pass fighting the others) and its
mitigation (services/transcription.py's asyncio.Semaphore, sized by
VOICE_TRANSCRIPTION_MAX_CONCURRENCY, default 1) — but states plainly: "This
sandbox has no access to the deployed instance's real CPU tier or live
request concurrency, so this could not be measured directly — only reasoned
about from the architecture." This script is what closes that gap, at least
for whatever CPU it's run on: it drives N concurrent simulated voice calls
against a live local instance, exactly matching the real client's own wire
behavior (services/api.ts / voiceApi.ts / useHybridVoiceInput.ts) — raw
16kHz mono int16 PCM deltas uploaded every CHUNK_UPLOAD_INTERVAL_MS (4000ms,
see that hook's own constant), not the legacy whole-buffer RIFF path — and
measures the one number that is actually visible to a child: how long the
"Transcribing…" spinner sits after release() before the final transcript
arrives (mirrors useHybridVoiceInput.ts's own `processingMs` client-side
metric).

Run against an already-running instance (this repo's own local-dev
convention — uvicorn main:app, TRANSCRIPTION_PROVIDER=local so a real
faster-whisper model actually runs, not a stub):

    cd homeschool-api && python3 scripts/voice_latency_probe.py \
        --base-url http://localhost:8000 --role child --credential 602656 \
        --concurrency 1 3 5 --hold-seconds 8

Prints per-call latencies and aggregates per concurrency level, and
cross-references services/streaming_transcription.py's own
`elapsed=`-tagged log lines for the same run if given --log-file, so a
compounding-latency signature (VOICE_SETUP.md's "6.9s, then 33.3s, then
never resolving" trace) would show up directly in this script's own output,
not just in server logs a human has to go find separately.

Not run in CI: it needs a live server process, a real local Whisper model
(the same sizeable model download/warm-up main.py's own startup lifespan
does), and takes real wall-clock time proportional to --hold-seconds ×
max(--concurrency). Run by hand when investigating a real latency report,
or as a regression check after touching services/streaming_transcription.py
/ services/transcription.py's concurrency handling.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_PCM_SAMPLE_RATE = 16000
_PCM_BYTES_PER_SAMPLE = 2
_CHUNK_UPLOAD_INTERVAL_S = 4.0  # matches CHUNK_UPLOAD_INTERVAL_MS in useHybridVoiceInput.ts


def _synthetic_pcm_delta(seconds: float) -> bytes:
    """A short burst of real int16 PCM audio — a quiet tone, not silence
    (some STT backends short-circuit true silence differently than real
    signal, and this probe measures the ordinary-speech code path). Content
    doesn't need to be intelligible: this measures pipeline latency, not
    transcription accuracy, and the real client's own audio is opaque to
    the server the same way — it just transcribes whatever bytes arrive."""
    import math

    n_samples = int(_PCM_SAMPLE_RATE * seconds)
    freq = 220.0
    samples = [
        int(3000 * math.sin(2 * math.pi * freq * (i / _PCM_SAMPLE_RATE)))
        for i in range(n_samples)
    ]
    return struct.pack(f"<{n_samples}h", *samples)


@dataclass
class CallResult:
    call_id: int
    start_latency_ms: float | None = None
    partial_arrivals_ms: list = field(default_factory=list)
    release_to_final_ms: float | None = None
    release_to_done_ms: float | None = None
    error: str | None = None


async def _consume_events(
    client: httpx.AsyncClient, base_url: str, session_id: str, token: str,
    release_time: dict, result: CallResult,
) -> None:
    """Reads the SSE stream exactly as services/api.ts's parseSSEStream does
    (line-buffered `data: {...}` frames), recording arrival time of each
    event relative to whenever release() (finish()) actually happened —
    release_time is a mutable dict written by the caller once finish() is
    sent, since the events reader and the chunk-upload loop run concurrently
    and the reader doesn't know the hold has ended until it sees it."""
    url = f"{base_url}/voice/stream/{session_id}/events"
    started = time.monotonic()
    try:
        async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}, timeout=60.0) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[len("data:"):].strip())
                now = time.monotonic()
                kind = payload.get("type")
                if kind == "partial":
                    result.partial_arrivals_ms.append(round((now - started) * 1000))
                elif kind == "final":
                    if "t" in release_time:
                        result.release_to_final_ms = round((now - release_time["t"]) * 1000)
                elif kind == "done":
                    if "t" in release_time:
                        result.release_to_done_ms = round((now - release_time["t"]) * 1000)
                    return
                elif kind == "error":
                    result.error = payload.get("message", "unknown stream error")
                    return
    except Exception as exc:  # noqa: BLE001 — probe script, report and move on
        if result.error is None:
            result.error = f"events stream failed: {exc}"


async def _simulate_one_call(
    client: httpx.AsyncClient, base_url: str, token: str, call_id: int, hold_seconds: float,
) -> CallResult:
    result = CallResult(call_id=call_id)

    t0 = time.monotonic()
    resp = await client.post(
        f"{base_url}/voice/stream/start", json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    result.start_latency_ms = round((time.monotonic() - t0) * 1000)
    session_id = resp.json()["session_id"]

    release_time: dict = {}
    events_task = asyncio.create_task(
        _consume_events(client, base_url, session_id, token, release_time, result)
    )

    # Mirrors useHybridVoiceInput.ts's chunk timer: upload a fresh delta
    # every CHUNK_UPLOAD_INTERVAL_S while the "hold" is active.
    elapsed = 0.0
    while elapsed < hold_seconds:
        chunk = _synthetic_pcm_delta(min(_CHUNK_UPLOAD_INTERVAL_S, hold_seconds - elapsed))
        try:
            r = await client.post(
                f"{base_url}/voice/stream/{session_id}/chunk",
                files={"audio": ("chunk.wav", chunk, "audio/wav")},
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            result.error = f"chunk upload failed: {exc}"
            break
        await asyncio.sleep(_CHUNK_UPLOAD_INTERVAL_S)
        elapsed += _CHUNK_UPLOAD_INTERVAL_S

    release_time["t"] = time.monotonic()
    try:
        r = await client.post(
            f"{base_url}/voice/stream/{session_id}/finish",
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        result.error = f"finish failed: {exc}"

    try:
        await asyncio.wait_for(events_task, timeout=90.0)
    except asyncio.TimeoutError:
        if result.error is None:
            result.error = "events stream never delivered final+done within 90s"

    return result


async def _run_level(base_url: str, token: str, concurrency: int, hold_seconds: float) -> list[CallResult]:
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[
            _simulate_one_call(client, base_url, token, call_id=i, hold_seconds=hold_seconds)
            for i in range(concurrency)
        ])
    return list(results)


def _login(base_url: str, role: str, credential: str) -> str:
    resp = httpx.post(f"{base_url}/auth/login", json={"role": role, "credential": credential}, timeout=15.0)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _report(concurrency: int, results: list[CallResult]) -> None:
    print(f"\n=== concurrency={concurrency} ===")
    finals = [r.release_to_final_ms for r in results if r.release_to_final_ms is not None]
    errors = [r for r in results if r.error]
    for r in results:
        status = f"error: {r.error}" if r.error else (
            f"start={r.start_latency_ms}ms  "
            f"partials={r.partial_arrivals_ms}  "
            f"release→final={r.release_to_final_ms}ms  "
            f"release→done={r.release_to_done_ms}ms"
        )
        print(f"  call {r.call_id}: {status}")
    if finals:
        print(
            f"  release→final across {len(finals)} calls: "
            f"min={min(finals)}ms  mean={round(statistics.mean(finals))}ms  max={max(finals)}ms"
        )
    if errors:
        print(f"  {len(errors)}/{len(results)} calls hit an error — see above")


async def _main_async(args: argparse.Namespace) -> None:
    token = _login(args.base_url, args.role, args.credential)
    for concurrency in args.concurrency:
        results = await _run_level(args.base_url, token, concurrency, args.hold_seconds)
        _report(concurrency, results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--role", choices=["parent", "child"], default="child")
    parser.add_argument("--credential", required=True, help="PARENT_PASSWORD or CHILD_PIN for the target instance")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--hold-seconds", type=float, default=8.0)
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
