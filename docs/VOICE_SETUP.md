# Setting up Bede's spoken voice

Bede's voice output is entirely optional and entirely self-hosted — there's no
cloud API, no per-user key, and no cost. If you skip this setup, the tablet's
browser speaks Bede's lines instead using its own built-in voice. Everything
below just upgrades that to a dedicated, consistent voice running on your own
server via [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), a small
(~80MB quantized) open-source TTS model.

## 1. Download the model files

Get both files from the
[kokoro-onnx releases page](https://github.com/thewh1teagle/kokoro-onnx/releases)
(look for the `model-files-v1.0` release):

- `kokoro-v1.0.onnx`
- `voices-v1.0.bin`

Place both in `homeschool-api/models/kokoro/` (or wherever you set
`KOKORO_MODEL_DIR` in `.env`).

## 2. Pick Bede's voice

Kokoro ships several dozen named voices across languages and genders. Bede's
voice must stay warm, elderly, and male — never gender-ambiguous or female —
so only a handful of English male voices are worth trying at all.

Run the evaluation script once the model files are in place:

```bash
cd homeschool-api
python scripts/evaluate_bede_voice.py
```

This synthesizes the same sample line with a shortlist of candidate voices,
saves each as a WAV file under `homeschool-api/scripts/voice_samples/`, and
prints a rough pitch-based ranking (lower pitch tends to read as older/deeper
— a starting hint, not a verdict). **Listen to the files yourself** — that's
the actual test — then set your pick in `.env`:

```bash
KOKORO_VOICE=bm_george   # or whichever candidate actually sounded right
```

The full, current voice list lives in Kokoro-82M's
[VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) if
you want to try one outside the script's shortlist.

## 3. Check real-time performance

Kokoro is CPU-friendly, but "friendly" isn't the same as "fast enough" on
every host — that depends on your actual hardware. Watch the time between a
response finishing and Bede's voice starting during a real session. If it's
consistently sluggish (multiple seconds of dead air), your host is probably
too weak to run this in real time — that's fine, just leave the model files
out (or delete `KOKORO_MODEL_DIR`) and the browser's own voice takes over
automatically, with no other changes needed.

## Restarting after changes

```bash
make restart
```
