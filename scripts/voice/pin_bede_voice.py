#!/usr/bin/env python3
"""Pin Bede's voice: record the SHA-256 of the exact files the voice image
will ship (voice-service/bede-voice.json), and show their model card.

Run on a machine that can reach huggingface.co, from the repo root:
  python3 scripts/voice/pin_bede_voice.py            # print hashes and the card
  python3 scripts/voice/pin_bede_voice.py --write    # also write the hashes

It downloads the three files named in bede-voice.json (model, config, model
card) into memory only, prints each SHA-256 and the full MODEL_CARD, and with
--write stores the hashes. It never writes license fields: a person reads the
card printed here and records "license", "training_lineage" and
"redistribution" in bede-voice.json by hand
(docs/DECISIONS.md entry 46). homeschool-api/tests/test_local_voice.py fails
while any hash is pinned and those fields are empty.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[2] / "voice-service" / "bede-voice.json"


def main(argv: list[str]) -> int:
    manifest = json.loads(MANIFEST.read_text())
    card = b""
    for name, spec in manifest["files"].items():
        with urllib.request.urlopen(spec["url"], timeout=120) as resp:
            data = resp.read()
        spec["sha256"] = hashlib.sha256(data).hexdigest()
        print(f"{name}: {spec['path']} {len(data)} bytes sha256={spec['sha256']}")
        if name == "model_card":
            card = data
    print("\n----- MODEL_CARD -----\n" + card.decode("utf-8", "replace") + "\n----------------------")
    if "--write" in argv:
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"\nWrote the hashes to {MANIFEST}. Now record license, training_lineage and "
              "redistribution there from the card above.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
