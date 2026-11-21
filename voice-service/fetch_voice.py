# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch Bede's voice into the image at build time, verified, or not at all.

Reads bede-voice.json. Downloads each file and keeps the set only if every
file's SHA-256 matches the pinned value. If any hash is not pinned yet, any
download fails, or any hash differs, every file is removed and the build
carries on with no voice: Bede is then text-first, never speaking from bytes
nobody verified. Exits 0 in every case, so a family's install never fails
because the voice could not be fetched; the reason is printed.

Usage (Dockerfile): python -I fetch_voice.py bede-voice.json /app/voices
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

TIMEOUT_SECONDS = 120


def fetch(manifest_path: str, out_dir: str, opener=urllib.request.urlopen) -> bool:
    manifest = json.loads(Path(manifest_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = manifest.get("files") or {}
    written: list[Path] = []

    def give_up(reason: str) -> bool:
        for path in written:
            path.unlink(missing_ok=True)
        print(f"bede-voice: no voice installed ({reason}); Bede will be text-first.")
        return False

    if not files or any(not str(f.get("sha256", "")).strip() for f in files.values()):
        return give_up("the voice's SHA-256 hashes are not pinned yet")
    for name, spec in files.items():
        target = out / Path(spec["path"]).name
        try:
            with opener(spec["url"], timeout=TIMEOUT_SECONDS) as resp:
                data = resp.read()
        except Exception as exc:  # noqa: BLE001 - any failure means no voice
            return give_up(f"could not download {name}: {type(exc).__name__}")
        digest = hashlib.sha256(data).hexdigest()
        if digest != spec["sha256"].strip().lower():
            return give_up(f"{name} did not match its pinned SHA-256")
        target.write_bytes(data)
        written.append(target)
    print(f"bede-voice: installed {manifest.get('name')} ({len(written)} files, hashes verified).")
    return True


if __name__ == "__main__":
    fetch(sys.argv[1], sys.argv[2])
    sys.exit(0)
