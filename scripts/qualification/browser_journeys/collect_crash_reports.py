#!/usr/bin/env python3
"""Collect the native crash reports macOS wrote during this job, for diagnosis.

Playwright reports a WebKit "Page crashed" as an event with no backtrace. The
native report (.ips, or an older text .crash) is the only stack, so the macOS
rows of cross-platform-browser-journeys.yml run this after the journeys.

What it does and does not claim:
- Only reports newer than the job-start marker and named for a relevant process
  (WebKit, WebContent, Playwright, pw_run, JetsamEvent; case-insensitive) are
  considered. Reports are polled for a bounded window, since macOS can write
  one some seconds after the process ends.
- No matching report is INCONCLUSIVE. Report generation, timing, discovery and
  permissions are separate from the termination itself, and an Apple report can
  itself record an operating-system termination reason, so the mechanism is
  read from the report's exception and termination fields, never from whether
  a file exists.
- Crash reports may contain sensitive diagnostic information. The sample
  household reduces the risk but does not establish that a report holds no
  secrets, paths or sensitive application messages. So only a SANITIZED,
  bounded summary is printed and written to the evidence directory. This
  repository is public, so its job logs and artifacts are not a restricted
  location: the full reports are copied to a separate directory that is
  never uploaded, and they last only as long as the runner.

Outcome, one of:
  report_collected     a report parsed with process, exception or termination,
                       and a triggered thread
  collected_uncertain  a report was found but could not be parsed or attributed
  no_matching_report   searched; nothing matched in the window (cause unknown)
  collection_failed    the search could not be completed

Exit status: 0, or 2 if the collector itself failed (its record still says
why). The workflow step is continue-on-error, so neither changes a row.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

RELEVANT = re.compile(r"webkit|webcontent|playwright|pw_run|jetsamevent", re.I)
SUFFIXES = (".ips", ".crash")
MAX_FRAMES = 20
MAX_LINE = 200
MAX_PRINTED = 6000
NO_REPORT_TEXT = ("No matching native report was collected within the observation window. "
                  "The process-termination cause remains unknown.")

# ── sanitizing ───────────────────────────────────────────────────────────────
_SECRETS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 <redacted>"),
    (re.compile(r"(?i)\b(token|secret|password|passwd|api[_-]?key|authorization|cookie|session)(\s*[=:]\s*)\S+"), r"\1\2<redacted>"),
    (re.compile(r"eyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}"), "<redacted-jwt>"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "<redacted-hex>"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}"), "<redacted-b64>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<redacted-email>"),
]
# An absolute path becomes its last component only: no user, home or
# directory names leave the runner.
_PATH = re.compile(r"(?<![\w.:])/(?:[^\s\"'<>/]+/)+([^\s\"'<>/]*)")


def sanitize(value) -> str:
    text = str(value)
    text = _PATH.sub(lambda m: f"<path>/{m.group(1)}", text)
    for pat, rep in _SECRETS:
        text = pat.sub(rep, text)
    return text[:MAX_LINE]


# ── parsing ──────────────────────────────────────────────────────────────────
def _load_ips(raw: str) -> tuple[dict, dict] | None:
    head, _, rest = raw.partition("\n")
    try:
        header = json.loads(head)
        body = json.loads(rest) if rest.strip() else {}
    except ValueError:
        return None
    return (header if isinstance(header, dict) else {}), (body if isinstance(body, dict) else {})


def _frames_ips(body: dict) -> tuple[int | None, list[str]]:
    images = body.get("usedImages") or []
    threads = body.get("threads") or []
    idx = body.get("faultingThread")
    thread = next((t for t in threads if isinstance(t, dict) and t.get("triggered")), None)
    if thread is None and isinstance(idx, int) and 0 <= idx < len(threads):
        thread = threads[idx]
    if thread is None:
        return idx, []
    out = []
    for f in (thread.get("frames") or [])[:MAX_FRAMES]:
        img = images[f["imageIndex"]] if isinstance(f.get("imageIndex"), int) and f["imageIndex"] < len(images) else {}
        name = img.get("name") or Path(str(img.get("path", "?"))).name
        sym = f.get("symbol") or f"+{f.get('imageOffset', '?')}"
        out.append(sanitize(f"{name} {sym}"))
    return (threads.index(thread) if thread in threads else idx), out


def summarize(path: Path) -> dict:
    """A sanitized, bounded summary of one report. Never raw text."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    s: dict = {"file": sanitize(path.name), "parsed": False}
    if path.suffix == ".ips":
        loaded = _load_ips(raw)
        if loaded is None:
            return s
        header, body = loaded
        s["bug_type"] = sanitize(header.get("bug_type", ""))
        s["timestamp"] = sanitize(header.get("timestamp", ""))
        if "jetsam" in path.name.lower() or "largestProcess" in body:
            s["kind"] = "jetsam"
            s["largest_process"] = sanitize(body.get("largestProcess", ""))
            procs = [p for p in body.get("processes") or [] if isinstance(p, dict) and RELEVANT.search(str(p.get("name", "")))]
            s["relevant_processes"] = [{"name": sanitize(p.get("name", "")), "reason": sanitize(p.get("reason", ""))} for p in procs[:10]]
            s["parsed"] = bool(body)
            return s
        s["kind"] = "crash"
        s["process"] = sanitize(body.get("procName") or header.get("app_name") or header.get("name") or "")
        s["pid"] = body.get("pid")
        exc = body.get("exception") or {}
        s["exception"] = {k: sanitize(exc[k]) for k in ("type", "signal", "codes", "subtype") if k in exc}
        term = body.get("termination") or {}
        s["termination"] = {k: sanitize(term[k]) for k in ("namespace", "indicator", "code", "byProc") if k in term}
        if term.get("reasons"):
            s["termination"]["reasons"] = [sanitize(r) for r in term["reasons"][:5]]
        s["triggered_thread"], s["frames"] = _frames_ips(body)
        s["parsed"] = bool(s["process"]) and bool(s["exception"] or s["termination"]) and bool(s["frames"])
        return s
    # Older text .crash format.
    s["kind"] = "crash"
    fields = {}
    for key in ("Process", "Exception Type", "Exception Codes", "Termination Reason", "Crashed Thread"):
        m = re.search(rf"^{re.escape(key)}:\s*(.+)$", raw, re.M)
        if m:
            fields[key] = sanitize(m.group(1).strip())
    s["process"] = fields.get("Process", "")
    s["exception"] = {k: fields[k] for k in ("Exception Type", "Exception Codes") if k in fields}
    s["termination"] = {"reason": fields["Termination Reason"]} if "Termination Reason" in fields else {}
    s["triggered_thread"] = fields.get("Crashed Thread")
    m = re.search(r"^Thread \d+ Crashed:.*\n((?:\d+\s+.+\n?)+)", raw, re.M)
    s["frames"] = [sanitize(re.sub(r"\s+", " ", ln.strip())) for ln in (m.group(1).splitlines() if m else [])][:MAX_FRAMES]
    s["parsed"] = bool(s["process"]) and bool(s["exception"] or s["termination"]) and bool(s["frames"])
    return s


# ── collecting ───────────────────────────────────────────────────────────────
def scan(directory: Path, since: float) -> tuple[str, list[Path]]:
    """Status of one directory, separately from what it held."""
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return "missing", []
    except PermissionError:
        return "permission_denied", []
    except OSError as exc:
        return f"error: {sanitize(type(exc).__name__)}", []
    found = []
    for e in entries:
        try:
            if e.is_file() and e.name.lower().endswith(SUFFIXES) and RELEVANT.search(e.name) and e.stat().st_mtime > since:
                found.append(Path(e.path))
        except OSError:
            continue
    return "searched", found


def collect(marker: Path, dirs: list[tuple[str, Path]], raw_dest: Path, wait: float, interval: float = 2.0) -> dict:
    record: dict = {"window_seconds": wait, "directories": {}, "reports": []}
    if not marker.exists():
        record.update(outcome="collection_failed", note="no job-start marker; nothing can be attributed to this job")
        return record
    since = marker.stat().st_mtime
    deadline = time.monotonic() + wait
    seen: dict[tuple[str, str], Path] = {}
    while True:
        before = len(seen)
        for label, d in dirs:
            status, paths = scan(d, since)
            record["directories"][label] = status
            for p in paths:
                seen.setdefault((label, p.name), p)
        # Once something has appeared, stop after the first pass that adds
        # nothing new; otherwise keep looking until the window closes.
        if (seen and len(seen) == before) or time.monotonic() >= deadline:
            break
        time.sleep(interval)
    for (label, name), p in sorted(seen.items()):
        # Keyed by source directory so identically named reports never collide.
        target = raw_dest / label / name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            summary = summarize(target)
        except OSError as exc:
            summary = {"file": sanitize(name), "parsed": False, "error": sanitize(type(exc).__name__)}
        summary["source"] = label
        record["reports"].append(summary)
    statuses = set(record["directories"].values())
    if record["reports"]:
        record["outcome"] = "report_collected" if any(r.get("parsed") and r.get("kind") == "crash" for r in record["reports"]) else "collected_uncertain"
    elif statuses and statuses <= {"missing", "permission_denied"} or any(s.startswith("error") for s in statuses):
        record["outcome"] = "collection_failed"
    else:
        record["outcome"] = "no_matching_report"
        record["note"] = NO_REPORT_TEXT
    return record


def render(record: dict) -> str:
    lines = [f"crash reports: outcome={record['outcome']} window={record['window_seconds']}s"]
    for label, status in record["directories"].items():
        lines.append(f"  directory {label}: {status}")
    if record.get("note"):
        lines.append(f"  {record['note']}")
    for r in record["reports"]:
        lines.append(f"--- {r.get('source')}/{r.get('file')} kind={r.get('kind')} parsed={r.get('parsed')}")
        for k in ("process", "pid", "timestamp", "exception", "termination", "triggered_thread", "largest_process", "relevant_processes"):
            if r.get(k) not in (None, "", {}, []):
                lines.append(f"  {k}: {json.dumps(r[k]) if not isinstance(r[k], str) else r[k]}")
        for f in r.get("frames") or []:
            lines.append(f"    {f}")
    lines.append("Sanitized summary only. Attribution to a journey (which WebKit page) is a person's reading, by time and process.")
    return "\n".join(lines)[:MAX_PRINTED]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--marker", required=True, type=Path)
    ap.add_argument("--summary-dir", required=True, type=Path, help="uploaded: sanitized summary only")
    ap.add_argument("--raw-dir", required=True, type=Path, help="never uploaded: full copies")
    ap.add_argument("--wait", type=float, default=30.0)
    ap.add_argument("--dir", action="append", default=[], help="label=path")
    a = ap.parse_args(argv)
    try:
        dirs = [(lbl, Path(p).expanduser()) for lbl, _, p in (d.partition("=") for d in a.dir)]
        record = collect(a.marker, dirs, a.raw_dir, a.wait)
        status = 0
    except Exception as exc:  # the record must survive any collector failure
        record = {"outcome": "collection_failed", "window_seconds": a.wait, "directories": {}, "reports": [],
                  "note": f"collector error: {sanitize(type(exc).__name__)}"}
        status = 2
    try:
        a.summary_dir.mkdir(parents=True, exist_ok=True)
        (a.summary_dir / "crash-report-summary.json").write_text(json.dumps(record, indent=1))
    except OSError as exc:
        print(f"crash reports: could not write the summary: {sanitize(type(exc).__name__)}")
        status = 2
    print(render(record))
    return status


if __name__ == "__main__":
    sys.exit(main())
