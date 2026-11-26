"""Check the exact public review documents without private inputs or packages."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
STRANDS = {
    "mathematics", "science", "literature", "history",
    "spanish", "computing", "wider_learning",
}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    check(manifest["format"] == "bede-student-review-v1", "Unknown projection format")
    check(manifest["grade"] == 8 and manifest["calendar_weeks"] == 36, "Unexpected scope")
    check(manifest["weekly_focus_drafts"] == 252, "Unexpected record count")
    for field in ("complete", "academic_approval", "live_activation"):
        check(manifest[field] is False, "Review must not assert completion or activation")
    expected = {name + ".md" for name in STRANDS}
    check(set(manifest["documents"]) == expected, "Unexpected public document set")
    check(
        {p.name for p in HERE.iterdir() if p.is_file()}
        == expected | {"README.md", "manifest.json", "verify_review.py"},
        "Unlisted file in public review directory",
    )
    for filename, evidence in manifest["documents"].items():
        data = (HERE / filename).read_bytes()
        check(len(data) == evidence["bytes"], f"Size mismatch: {filename}")
        check(hashlib.sha256(data).hexdigest() == evidence["sha256"], f"Hash mismatch: {filename}")
        text = data.decode("utf-8")
        weeks = re.findall(r"^## Week (\d+):", text, re.MULTILINE)
        check(weeks == [str(i) for i in range(1, 37)], f"Week coverage: {filename}")
        for task in ("Guided", "Independent", "Delayed", "Transfer"):
            check(text.count(f"\n### {task} task\n") == 36, f"Task coverage: {filename}/{task}")
        for forbidden in (
            "PRIVATE_", "key_rubric", "prompt_rescue_record",
            "assessor_role", "worked_example", "<script", "<iframe",
        ):
            check(forbidden not in text, f"Forbidden output marker: {filename}")
    provenance = manifest["lesson_provenance"]
    check(len(provenance) == 252, "Missing lesson provenance")
    check(len({p["lesson_id"] for p in provenance}) == 252, "Duplicate lesson IDs")
    for name in STRANDS:
        check(
            sorted(p["week"] for p in provenance if p["strand"] == name) == list(range(1, 37)),
            f"Provenance week coverage: {name}",
        )
    for p in provenance:
        check(set(p) == {"strand", "week", "lesson_id", "private_bundle_sha256"}, "Unexpected provenance field")
        check(bool(re.fullmatch(r"[a-f0-9]{64}", p["private_bundle_sha256"])), "Invalid provenance hash")
    check(
        manifest["checks"]["private_field_noninterference_checks_passed"] == 252,
        "Private-field projection evidence missing",
    )
    print("PASS: seven public documents; 252 weekly drafts; exact hashes, task coverage and draft boundaries.")
    print("Private-source exclusion was checked locally; this public check cannot independently inspect withheld inputs.")


if __name__ == "__main__":
    main()
