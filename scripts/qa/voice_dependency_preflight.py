#!/usr/bin/env python3
"""Offline, fail-closed dependency preflight for issue #726.

This checks the *installed* Python environment. It never downloads packages,
changes a lockfile, or asserts Mac hardware or voice-enrollment qualification.
Run after a clean hash-locked candidate install, not against a developer venv
with additional, untracked distributions.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata as metadata
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def fixed_setuptools(version: str | None) -> bool:
    """Accept stable releases at or above the advisory's 84.1.0 floor."""
    if not version or not re.fullmatch(r"\d+(?:\.\d+){1,2}", version):
        return False
    parts = [int(part) for part in version.split(".")]
    return tuple((parts + [0] * (3 - len(parts)))[:3]) >= (84, 1, 0)


def required_vad_distributions(requirements: list[str]) -> set[str]:
    """Read distribution names only; do not guess which import a fork provides."""
    names = set()
    for requirement in requirements:
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
        if match:
            name = normalize(match.group(1))
            if name in {"webrtcvad", "webrtcvad-wheels"}:
                names.add(name)
    return names


def assess(versions: dict[str, str], resemblyzer_requirements: list[str],
           module_providers: list[str]) -> list[dict[str, str]]:
    """Pure metadata assessment; importing and loading the model are separate."""
    versions = {normalize(k): v for k, v in versions.items()}
    providers = {p for p in ("webrtcvad", "webrtcvad-wheels") if p in versions}
    declared = required_vad_distributions(resemblyzer_requirements)
    imported_from = {normalize(p) for p in module_providers}
    checks = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "result": "PASS" if passed else "FAIL",
                       "detail": detail})

    add("setuptools_fixed", fixed_setuptools(versions.get("setuptools")),
        "Installed setuptools must be a stable release >=84.1.0 (GHSA-xmj3-9gf7-h52w).")
    add("resemblyzer_installed", "resemblyzer" in versions,
        "Resemblyzer must be installed in the candidate environment.")
    add("single_vad_distribution", len(providers) == 1,
        "Exactly one VAD distribution may be installed; overlapping providers are unsafe.")
    add("module_provenance", len(providers) == 1 and imported_from == providers,
        "The installed distribution supplying the webrtcvad module must match the sole VAD provider.")
    add("resemblyzer_metadata_compatible", len(providers) == 1 and declared <= providers,
        "Resemblyzer's declared VAD dependencies must be satisfied by the actual distribution; "
        "webrtcvad-wheels does not satisfy a hard webrtcvad distribution requirement.")
    return checks


def installed_versions() -> dict[str, str]:
    result = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            key = normalize(name)
            if key in {"setuptools", "resemblyzer", "webrtcvad", "webrtcvad-wheels"}:
                result[key] = dist.version
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write JSON evidence to this path")
    parser.add_argument("--load-encoder", action="store_true",
                        help="Also instantiate the GE2E model (may be slow)")
    args = parser.parse_args()

    versions = installed_versions()
    try:
        requirements = metadata.requires("resemblyzer") or []
    except metadata.PackageNotFoundError:
        requirements = []
    providers = metadata.packages_distributions().get("webrtcvad", [])
    checks = assess(versions, requirements, providers)

    def add(name: str, result: str, detail: str) -> None:
        checks.append({"check": name, "result": result, "detail": detail})

    # Even a valid-looking distribution name cannot prove a working import.
    try:
        vad = importlib.import_module("webrtcvad")
        vad.Vad(1)
        from resemblyzer import VoiceEncoder
        add("voice_import", "PASS", "VAD and VoiceEncoder imports succeeded.")
        if args.load_encoder:
            VoiceEncoder()
            add("encoder_model_load", "PASS", "GE2E model instantiated.")
        else:
            add("encoder_model_load", "NOT_RUN", "Pass --load-encoder for model-load evidence.")
    except Exception as exc:
        add("voice_import", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}")
        add("encoder_model_load", "NOT_RUN", "Import failed before model load.")

    failed = any(item["result"] == "FAIL" for item in checks)
    report = {
        "schema": 1,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "installed_versions": versions,
        "module_providers": providers,
        "checks": checks,
        "result": "FAIL" if failed else "PREFLIGHT_PASS_NOT_VOICE_ENROLLMENT_OR_MAC_QUALIFICATION",
        "limitations": [
            "Does not validate PyPI artifact hashes or lockfile freshness.",
            "Does not exercise voice enrollment, verification, revocation, or fallback.",
            "Does not prove physical Mac, school environment, or real learner-data readiness.",
        ],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
