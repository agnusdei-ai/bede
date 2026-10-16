#!/usr/bin/env python3
"""Manifest, checksums and the credential scan for a qualification run.

  manifest.json — candidate SHA, run id, runner image, image digests (when
                  images were built), SHA-256 of every lockfile, per-suite
                  counts, teacher-login mode and any recorded deviation.
  SHA256SUMS    — over every file in the output directory, in the format
                  ``sha256sum -c`` reads.

The credential scan runs over every collected file FIRST and fails closed:
if any credential-shaped string, or any secret value this run generated, is
found, the offending files are quarantined and the step exits non-zero so
nothing containing it is uploaded.

G3 (the Mac package) is NOT built here. ``mac_package`` in the manifest
records only the placeholder input; the manifest says in so many words that
no physical Mac check ran.

    python scripts/qualification/package.py [--images images.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualconfig as cfg  # noqa: E402

SECRET_ENV_NAMES = ("SECRET_KEY", "MASTER_SECRET", "PARENT_PASSWORD", "CHILD_PIN",
                    "QUAL_APP_DB_PASSWORD", "LOCAL_LLM_API_KEY")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(out: Path, env: dict) -> list[dict]:
    patterns = [re.compile(p) for p in cfg.CREDENTIAL_PATTERNS]
    literals = [env[n] for n in SECRET_ENV_NAMES if len(env.get(n, "")) >= 8]
    findings = []
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        if path.name in ("SHA256SUMS",):
            continue
        text = path.read_text(errors="replace")
        for pat in patterns:
            if pat.search(text):
                findings.append({"file": str(path.relative_to(out)), "kind": f"pattern:{pat.pattern[:30]}"})
        for lit in literals:
            if lit in text:
                findings.append({"file": str(path.relative_to(out)), "kind": "generated-secret-literal"})
    return findings


def build_manifest(out: Path, env: dict, images: dict) -> dict:
    def load(name):
        p = out / name
        return json.loads(p.read_text()) if p.exists() else None

    matrix = load("matrix.json") or {}
    seed = load("seed.json") or {}
    pre = [load(f"preflight-{ph}.json") for ph in ("pre-start", "post-seed")]
    lockfiles = {}
    for rel in cfg.LOCKFILES:
        p = cfg.REPO / rel
        lockfiles[rel] = sha256(p) if p.exists() else None
    return {
        "schema": "bede-synthetic-qualification/1",
        "candidate_sha": env.get("QUAL_CANDIDATE_SHA", ""),
        "run_id": env.get("GITHUB_RUN_ID", env.get("QUAL_RUN_ID", "local")),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "workflow_ref": env.get("GITHUB_WORKFLOW_REF", ""),
        "runner_image": {"os": env.get("ImageOS", env.get("RUNNER_OS", "")),
                         "version": env.get("ImageVersion", "")},
        "image_digests": images,
        "lockfile_sha256": lockfiles,
        "teacher_auth_mode": seed.get("mode", env.get("QUAL_TEACHER_AUTH_MODE", cfg.TEACHER_AUTH_MODE)),
        "deviations": seed.get("deviations", []),
        "teacher_blocker": seed.get("teacher_blocker", ""),
        "suites": {
            "preflight": [{"phase": p["phase"], "ok": p["ok"],
                           "checks": len(p["checks"]),
                           "failed": sum(1 for c in p["checks"] if not c["ok"])} for p in pre if p],
            "seed_steps": {"total": len(seed.get("steps", [])),
                           "ok": sum(1 for s in seed.get("steps", []) if s.get("ok"))},
            "matrix": matrix.get("summary", {}),
        },
        "mac_package": {
            "requested": env.get("QUAL_MAC_PACKAGE", "none"),
            "built": False,
            "physical_mac_verification": "NOT RUN — human release-owner step; this workflow never performs or claims it",
        },
        "decision_authority": "none — evidence only; no gate, Engineering Complete or GO is implied",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="")
    a = ap.parse_args()
    out = cfg.OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    findings = scan(out, env)
    if findings:
        quarantine = out.parent / (out.name + "-quarantine")
        quarantine.mkdir(exist_ok=True)
        for f in {x["file"] for x in findings}:
            src = out / f
            if src.exists():
                src.rename(quarantine / src.name)
        (out / "credential-scan.json").write_text(json.dumps(
            {"ok": False, "findings": findings}, indent=2) + "\n")
        print(f"credential scan FAILED: {len(findings)} finding(s); files quarantined, not uploaded")
        for f in findings:
            print(f"  {f['file']}: {f['kind']}")
        return 1
    (out / "credential-scan.json").write_text(json.dumps({"ok": True, "findings": []}) + "\n")
    images = json.loads(Path(a.images).read_text()) if a.images and Path(a.images).exists() else {}
    manifest = build_manifest(out, env, images)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    lines = []
    for p in sorted(x for x in out.rglob("*") if x.is_file() and x.name != "SHA256SUMS"):
        lines.append(f"{sha256(p)}  {p.relative_to(out)}")
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    print(f"manifest + SHA256SUMS over {len(lines)} files; credential scan clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
