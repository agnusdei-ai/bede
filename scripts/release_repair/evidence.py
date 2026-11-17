"""Write the cycle's evidence: summary JSON and Markdown, manifest, SHA256SUMS.

Refuses to write anything that still carries a credential shape. READY is
rendered as 'ready for a release decision', never as approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from release_repair import sanitize


def markdown(summary: dict) -> str:
    lines = [f"## Release repair cycle `{summary.get('cycle_id')}`", "",
             f"- Candidate: `{summary.get('candidate_sha')}`",
             f"- Status: **{summary.get('status')}** · release status: **{summary.get('release_status')}**",
             "- Approved for distribution: **no** (the owner decides; this loop never approves)",
             f"- Acceptance: {summary['acceptance']['label']}" + (" **(TEST ONLY)**" if summary["acceptance"]["test_only"] else ""),
             "", "| Gate | Status |", "|---|---|"]
    lines += [f"| {g} | {st} |" for g, st in sorted(summary.get("gates", {}).items())]
    lines += ["", "| Blocker | Detail |", "|---|---|"]
    lines += [f"| {b['code']} | {b.get('failure') or b.get('task') or b.get('gate') or ''} |" for b in summary.get("blockers", [])] or ["| none | |"]
    lines += ["", "| Task | Failure | Status | Attempt | Reason |", "|---|---|---|---|---|"]
    lines += [f"| {k} | {t['failure_key']} | {t['status']} | {t['attempt']} | "
              f"{' + '.join(t.get('reasons') or []) or t.get('reason') or ''} |"
              for k, t in sorted(summary.get("tasks", {}).items())]
    return "\n".join(lines) + "\n"


def write(out: Path, summary: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    clean = sanitize.obj(summary)
    body = json.dumps(clean, indent=2, sort_keys=True)
    if sanitize.findings(body):
        raise ValueError("credential shape survived sanitizing; refusing to publish evidence")
    (out / "summary.json").write_text(body + "\n")
    (out / "summary.md").write_text(markdown(clean))
    manifest = {"schema": "bede-release-repair-evidence/1", "cycle_id": clean.get("cycle_id"),
                "candidate_sha": clean.get("candidate_sha"), "status": clean.get("status"),
                "release_status": clean.get("release_status"), "approved_for_distribution": False,
                "snapshot": clean.get("snapshot"), "decision_authority": "none: evidence only; the owner decides"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    sums = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in sorted(out.iterdir())
            if f.is_file() and f.name != "SHA256SUMS"]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return manifest
