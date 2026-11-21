#!/usr/bin/env python3
"""Build a sample Piper voice locally, with nothing downloaded.

It is a real ONNX model with the inputs and output Piper's library expects
(`input`, `input_lengths`, `scales` -> audio), plus a real `.onnx.json`
config using Piper's own default phoneme map. Instead of speech it emits a
steady tone, 256 samples per phoneme id, so a longer line makes longer
audio. That exercises the real path end to end (Piper's phonemizer and
espeak-ng data, onnxruntime, the WAV writer, voice-service/server.py, the
API's /tutor/speak, the browser's <audio>), and says nothing about how a
real voice sounds: that is the owner's acceptance on the pilot Mac, with a
real voice whose license is recorded (docs/DECISIONS.md entry 46).

`failing=True` builds a voice that loads normally and then fails on every
line (its output cannot be reshaped), which is how "Piper is set up but
fails" is checked without breaking anything else.

Needs `onnx` (to build the graph) and `piper-tts` (for its phoneme map).
Usage: make_sample_voice.py <out_dir> [locale] [--failing]
       -> <out_dir>/sample-<locale>.onnx (or failing-<locale>.onnx)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

SAMPLE_RATE = 22050
HOP = 256
ESPEAK = {"en": "en-us", "es": "es-419"}


def build(out_dir: Path, locale: str = "en", failing: bool = False) -> Path:
    import onnx
    from onnx import TensorProto, helper
    from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP

    tone = 440.0 if locale == "en" else 330.0
    nodes = [
        helper.make_node("Shape", ["input"], ["shape"]),
        helper.make_node("Gather", ["shape", "one"], ["n"], axis=0),
        helper.make_node("Mul", ["n", "hop"], ["t"]),
        helper.make_node("Range", ["zero", "t", "one"], ["idx"]),
        helper.make_node("Cast", ["idx"], ["idx_f"], to=TensorProto.FLOAT),
        helper.make_node("Mul", ["idx_f", "omega"], ["phase"]),
        helper.make_node("Sin", ["phase"], ["wave"]),
        helper.make_node("Mul", ["wave", "gain"], ["quiet"]),
        helper.make_node("Unsqueeze", ["quiet", "axes"], ["output"]) if not failing
        else helper.make_node("Reshape", ["quiet", "impossible"], ["output"]),
    ]
    init = [
        helper.make_tensor("zero", TensorProto.INT64, [], [0]),
        helper.make_tensor("one", TensorProto.INT64, [], [1]),
        helper.make_tensor("hop", TensorProto.INT64, [], [HOP]),
        helper.make_tensor("omega", TensorProto.FLOAT, [], [2 * math.pi * tone / SAMPLE_RATE]),
        helper.make_tensor("gain", TensorProto.FLOAT, [], [0.3]),
        helper.make_tensor("axes", TensorProto.INT64, [2], [0, 1]),
        helper.make_tensor("impossible", TensorProto.INT64, [3], [1, 1, 7]),
    ]
    graph = helper.make_graph(
        nodes, "bede-sample-voice",
        [helper.make_tensor_value_info("input", TensorProto.INT64, [1, None]),
         helper.make_tensor_value_info("input_lengths", TensorProto.INT64, [1]),
         helper.make_tensor_value_info("scales", TensorProto.FLOAT, [3])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1, None])],
        init,
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{'failing' if failing else 'sample'}-{locale}.onnx"
    onnx.save(model, str(path))
    config = {
        "audio": {"sample_rate": SAMPLE_RATE},
        "espeak": {"voice": ESPEAK[locale]},
        "phoneme_type": "espeak",
        "num_symbols": 256,
        "num_speakers": 1,
        "inference": {"noise_scale": 0.667, "length_scale": 1.0, "noise_w": 0.8},
        "phoneme_id_map": {k: list(v) for k, v in DEFAULT_PHONEME_ID_MAP.items()},
    }
    Path(f"{path}.json").write_text(json.dumps(config))
    return path


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--failing"]
    print(build(Path(args[0]), args[1] if len(args) > 1 else "en", failing="--failing" in sys.argv))
