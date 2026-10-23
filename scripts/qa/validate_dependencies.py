#!/usr/bin/env python3
"""Zero-dependency manifest/lockfile integrity guard (not a CVE waiver)."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PACKAGES = ("homeschool-tutor", "demo", "license-server")


def validate(root: Path) -> list[str]:
    problems: list[str] = []
    for p in PACKAGES:
        manifest_path = root / p / "package.json"
        lock_path = root / p / "package-lock.json"
        try:
            manifest = json.loads(manifest_path.read_text())
            lock = json.loads(lock_path.read_text())
        except (OSError, ValueError) as exc:
            problems.append(f"{p}: missing or invalid manifest/lock: {exc}")
            continue
        top = lock.get("packages", {}).get("", {})
        if lock.get("lockfileVersion") != 3:
            problems.append(f"{p}: npm lockfileVersion must be 3")
        for key in ("name", "version", "dependencies", "devDependencies", "optionalDependencies"):
            if (manifest.get(key) or {}) != (top.get(key) or {}):
                problems.append(f"{p}: lockfile root {key} differs from package.json")
        if not manifest.get("engines", {}).get("node", "").startswith((">=22", ">=24")):
            problems.append(f"{p}: unsupported/unspecified Node runtime")
        if lock.get("name") != manifest.get("name"):
            problems.append(f"{p}: lockfile name mismatch")
    base = root / "homeschool-api"
    for name in ("requirements.lock.txt", "requirements-dev.lock.txt"):
        path = base / name
        try:
            lock = path.read_text()
        except OSError:
            problems.append("Missing Python hash lock: " + name)
            continue
        if not re.search(r"(?m)^[-\w.]+\[?[^\n]*==\d+", lock):
            problems.append(name + ": no pinned packages")
        if "--hash=sha256:" not in lock:
            problems.append(name + ": missing SHA256 hashes")
        if "Python 3.12" not in lock[:600]:
            problems.append(name + ": not generated for supported Python 3.12")
    return problems


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default=".")
    args = p.parse_args()
    errors = validate(Path(args.repo).resolve())
    if errors:
        for err in errors:
            print("QA dependency BLOCK: " + err)
        return 1
    print("QA dependency PASS: npm manifests/locks and Python hash-lock invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
