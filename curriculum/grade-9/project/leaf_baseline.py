"""Original Grade 9 teaching baseline; broad leaf forms, NOT species identification.

Standard library only. No network or personal information required.
Included CSV is fictional, with deliberate missing/noisy observations.
"""
import csv
import json
import sys

KNOWN = {"needle_like", "simple_broad", "compound_broad"}


def classify(blade, divided):
    """Return a broad-form label, abstaining on missing/inconsistent input."""
    if blade == "needle":
        return "needle_like" if divided is False or divided is None else "unknown"
    if blade != "flat" or type(divided) is not bool:
        return "unknown"
    if divided:
        return "compound_broad"
    return "simple_broad"


def parse_divided(value):
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "":
        return None
    raise ValueError("divided must be true, false, or blank")


def load_records(filename):
    with open(filename, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"id", "split", "blade", "divided", "reference", "note"}
        headers = reader.fieldnames or []
        if len(headers) != len(required) or set(headers) != required:
            raise ValueError("CSV headers must match the teaching schema exactly, without duplicates")
        records = []
        ids = set()
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV row ending at line {reader.line_num} must have exactly six fields")
            if not row["id"] or row["id"] in ids:
                raise ValueError("Every observation needs a unique nonempty id")
            ids.add(row["id"])
            if row["split"] not in {"development", "test"}:
                raise ValueError("split must be development or test")
            if row["blade"] not in {"needle", "flat", "unknown"}:
                raise ValueError("blade must be needle, flat, or unknown")
            if row["reference"] not in KNOWN | {"unknown"}:
                raise ValueError("Unrecognized reference label")
            row["divided"] = parse_divided(row["divided"])
            records.append(row)
        return records


def evaluate(records):
    counts = {"known_reference": 0, "correct": 0, "wrong": 0,
              "abstain": 0, "unknown_reference": 0}
    for row in records:
        if row["split"] != "test":
            continue
        prediction = classify(row["blade"], row["divided"])
        if row["reference"] == "unknown":
            counts["unknown_reference"] += 1
            continue
        counts["known_reference"] += 1
        if prediction == "unknown":
            counts["abstain"] += 1
        elif prediction == row["reference"]:
            counts["correct"] += 1
        else:
            counts["wrong"] += 1
    n = counts["known_reference"]
    covered = counts["correct"] + counts["wrong"]
    counts["accuracy_including_abstentions"] = counts["correct"] / n if n else None
    counts["coverage"] = covered / n if n else None
    counts["accuracy_when_covered"] = counts["correct"] / covered if covered else None
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 leaf_baseline.py observations.csv")
    try:
        print(json.dumps(evaluate(load_records(sys.argv[1])), indent=2))
    except (OSError, ValueError) as error:
        raise SystemExit(f"Cannot evaluate: {error}") from error

