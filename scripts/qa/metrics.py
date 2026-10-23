#!/usr/bin/env python3
"""Aggregate source-keyed QA evidence; never infer GitHub billing."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import statistics
from collections import Counter
from pathlib import Path

def fingerprint(text: str) -> str:
    clean = re.sub(r"\b[0-9a-f]{12,}\b", "<sha>", text.lower())
    clean = re.sub(r"\b\d+\b", "#", clean)
    clean = re.sub(r"(?m)^.*(api.key|password|secret|token).*$", "[masked]", clean)
    return hashlib.sha256(clean.encode()).hexdigest()[:12]

def aggregate(reports: list[dict]) -> dict:
    if not reports:
        return {"evaluated": 0, "first_pass_rate": None, "pass_rate": None,
                "failure_categories": {}, "recurrences": {}, "p50_runner_seconds": None,
                "p95_runner_seconds": None, "repair_cycles": 0}
    categories: Counter[str] = Counter()
    repeats: Counter[str] = Counter()
    first = passed = repaired = 0
    durations: list[float] = []
    for report in reports:
        results = report.get("results", [])
        failures = [x for x in results if x.get("exit_code") != 0]
        if not failures:
            first += 1
        if report.get("merge_status") == "ready for external CI and security gates":
            passed += 1
        for failure in failures:
            categories[failure.get("category", "unclassified")] += 1
            repeats[fingerprint(failure.get("diagnostic_excerpt", ""))] += 1
        repaired += sum(1 for x in results if x.get("attempt", 1) > 1)
        durations.append(float(report.get("runner_seconds", 0)))
    durations.sort()
    p95_index = max(0, (len(durations) * 95 + 99) // 100 - 1)
    return {"evaluated": len(reports),
            "first_pass_rate": round(first / len(reports), 4),
            "pass_rate": round(passed / len(reports), 4),
            "failure_categories": dict(categories),
            "recurrences": {k: v for k, v in repeats.items() if v > 1},
            "p50_runner_seconds": round(statistics.median(durations), 2),
            "p95_runner_seconds": round(durations[p95_index], 2),
            "repair_cycles": repaired, "github_billed_minutes": None}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("reports", nargs="+")
    p.add_argument("--output", default="-")
    args = p.parse_args()
    data = aggregate([json.loads(Path(path).read_text()) for path in args.reports])
    out = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.output == "-":
        print(out, end="")
    else:
        Path(args.output).write_text(out)

if __name__ == "__main__":
    main()
