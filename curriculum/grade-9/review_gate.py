"""Offline evidence/freshness gate; never grants rights or promotes content."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SUBJECTS = {
    "humanities": {"02-resources.md", "03-scope-and-sequence.md",
                   "04-starter-lessons.md", "05-assessments.md"},
    "algebra": {"01-program-and-delivery.md", "03-scope-and-sequence.md",
                "04-starter-lessons.md", "05-assessments.md"},
    "latin": {"02-resources.md", "03-scope-and-sequence.md",
              "04-starter-lessons.md", "05-assessments.md"},
    "biology-safety": {"04-starter-lessons.md", "06-biology-labs.md"},
    "computing": {"04-starter-lessons.md", "05-assessments.md",
                  "07-computing-project.md", "project/leaf_baseline.py",
                  "project/test_leaf_baseline.py", "project/observations.csv"},
}
STATUSES = {"agent-reviewed", "changes required", "blocked by specific defect"}
for subject in ("humanities", "algebra", "biology-safety"):
    SUBJECTS[subject].add("resources/REPLACEMENT-REGISTER.md")
SUBJECTS["biology-safety"].add("resources/biology-reference-notes.md")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_file(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("Evidence path must be a relative file")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or out-of-scope evidence: {name}")
    return path


def inspect(records, root=ROOT):
    """Returns structural errors separately from substantive review blockers."""
    errors, blockers = [], []
    if not isinstance(records, list):
        return ["Reviews must be a list"], []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            errors.append("Review must be an object")
            continue
        subject = record.get("subject")
        if not isinstance(subject, str) or subject not in SUBJECTS or subject in seen:
            errors.append(f"Unknown or duplicate subject: {subject}")
            continue
        seen.add(subject)
        for key in ("agent_id", "agent_version", "review_run", "authoring_run",
                    "date", "scope", "methods", "evidence", "conditions",
                    "disagreements"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                errors.append(f"{subject}: missing {key}")
        if record.get("review_run") == record.get("authoring_run"):
            errors.append(f"{subject}: author and reviewer runs must differ")
        status = record.get("status")
        if status not in STATUSES:
            errors.append(f"{subject}: invalid status")
        findings = record.get("open_findings")
        if not isinstance(findings, list) or any(
                not isinstance(f, str) or not f.strip() for f in findings):
            errors.append(f"{subject}: open_findings must be a list of descriptions")
        elif status == "agent-reviewed" and findings:
            errors.append(f"{subject}: unresolved findings cannot be approved")
        elif status != "agent-reviewed":
            if not findings:
                errors.append(f"{subject}: non-approval needs a specific finding")
            blockers.append(f"{subject}: {status}: {'; '.join(findings)}")
        sources = record.get("source_hashes")
        if not isinstance(sources, dict):
            errors.append(f"{subject}: missing source_hashes")
            continue
        for name in SUBJECTS[subject] - sources.keys():
            errors.append(f"{subject}: missing required source {name}")
        for name, expected in sources.items():
            try:
                if digest(local_file(root, name)) != expected:
                    errors.append(f"{subject}: stale source {name}; re-review required")
            except ValueError as exc:
                errors.append(f"{subject}: {exc}")
        try:
            report = local_file(root, record.get("report"))
            if digest(report) != record.get("report_sha256"):
                errors.append(f"{subject}: changed report; evidence record invalid")
        except ValueError as exc:
            errors.append(f"{subject}: {exc}")
    errors.extend(f"Missing subject review: {s}" for s in sorted(SUBJECTS.keys() - seen))
    return errors, blockers


def main():
    try:
        manifest = []
        for filename in ("humanities-latin-records.json",
                         "algebra-biology-computing-records.json"):
            records = json.loads((ROOT / "reviews" / filename).read_text())
            if not isinstance(records, list):
                raise ValueError(f"{filename}: reviews must be a list")
            manifest.extend(records)
        errors, blockers = inspect(manifest)
    except (OSError, ValueError) as exc:
        print(f"INVALID EVIDENCE: {exc}")
        return 2
    for error in errors:
        print(f"INVALID EVIDENCE: {error}")
    for blocker in blockers:
        print(f"REVIEW BLOCKER: {blocker}")
    if errors:
        return 2
    if blockers:
        print("Evidence structure checked; curriculum review remains blocked.")
        return 1
    print("Agent review evidence is current for recorded scope only.")
    print("Not rights clearance, adoption, certification or permission to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
