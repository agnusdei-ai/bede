"""Project the reviewed Grades 9-12 factory build into explicitly public fields.

Run locally against the private factory output (generated-artifacts/curriculum-factory/upper-year).
Only bundles whose factory run succeeded and whose manifest hash matches the build index are
exported. Teacher worked models, adult keys/rubrics, misconceptions and private original
records are never copied.
"""
import argparse
import hashlib
import json
from pathlib import Path

RELEASE_ID = "bede-upper-2026-reviewed"
GRADES = (9, 10, 11, 12)
STRANDS = ("literature", "composition", "history", "mathematics", "science", "latin", "spanish",
           "logic_rhetoric", "computing", "fine_arts", "practical_arts", "movement_health")
SUBJECT = {"literature": "living_books", "composition": "language_arts", "history": "history",
           "mathematics": "mathematics", "science": "science", "latin": "latin", "spanish": "spanish",
           "logic_rhetoric": "logic", "computing": "computing", "fine_arts": "art_music",
           "practical_arts": "nature_study", "movement_health": "movement_health"}


def student_lesson(bundle):
    lesson, = bundle["lessons"]
    objectives = {o["id"]: o["statement"] for o in bundle["objectives"]}
    sources = {s["id"]: s for s in bundle["sources"]}
    return {
        "id": lesson["id"], "title": lesson["title"],
        "objective_ids": list(lesson["objective_ids"]),
        "objectives": [objectives[o] for o in lesson["objective_ids"]],
        "entry_evidence": lesson["entry_evidence"],
        "steps": [
            {k: step[k] for k in ("mode", "instruction", "minutes", "materials")}
            for step in lesson["steps"] if step["mode"] != "worked_example"
        ],
        "assessments": [
            {k: a[k] for k in ("kind", "prompt", "supports", "success_criteria")}
            for a in lesson["assessments"]
        ],
        "access": {k: lesson["access"][k] for k in ("construct", "supports", "alternative_response")},
        "safety": {k: lesson["safety"][k] for k in ("hazards", "supervision", "stop_escalation", "safer_alternative")},
        "sources": [
            {**{k: sources[ref["source"]["id"]][k] for k in
                ("title", "creator_editor_translator", "edition", "url", "license", "attribution", "notices")},
             "locator": ref["locator"]}
            for ref in lesson["source_refs"]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True, help="upper-year factory output directory")
    parser.add_argument("--review-summary", type=Path, required=True, help="private review ledger summary JSON")
    parser.add_argument("--output", type=Path, required=True, help="path of upper-student.json")
    args = parser.parse_args()
    index = json.loads((args.build / "build-index.json").read_bytes())
    review = json.loads(args.review_summary.read_bytes())
    if review.get("approved_lessons") != 1728 or review.get("pending") != 0:
        raise ValueError("Every lesson must carry a current, content-bound approved review")
    if len(index) != 1728 or any(v["status"] != "succeeded" for v in index.values()):
        raise ValueError("Every lesson must have a succeeded factory run")
    lessons = {}
    for lid, row in sorted(index.items()):
        g, rest = lid[1:].split("-year-")
        strand, week = rest.rsplit("-w", 1)
        manifest = args.build / "input" / f"g{g}" / strand / f"week-{week}" / "bundle.json"
        raw = manifest.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["manifest_sha256"]:
            raise ValueError(f"Factory manifest changed after build: {lid}")
        if review["lesson_sha256"].get(lid) != row["review_bound_sha256"]:
            raise ValueError(f"Reviewed content does not match the build: {lid}")
        public = student_lesson(json.loads(raw))
        if public["id"] != lid:
            raise ValueError("Lesson id mismatch")
        public.update(grade=int(g), strand=strand, subject=SUBJECT[strand], week=int(week))
        lessons[lid] = public
    out_dir = args.output.parent / "upper-student"
    out_dir.mkdir(parents=True, exist_ok=True)
    lesson_files, weeks = {}, {}
    for g in GRADES:
        weeks[str(g)] = {str(w): [f"g{g}-year-{s}-w{w:02d}" for s in STRANDS] for w in range(1, 37)}
        for s in STRANDS:
            rows = [lessons[f"g{g}-year-{s}-w{w:02d}"] for w in range(1, 37)]
            raw = (json.dumps(rows, ensure_ascii=False, indent=1) + "\n").encode()
            name = f"g{g}-{s}"
            (out_dir / f"{name}.json").write_bytes(raw)
            lesson_files[name] = hashlib.sha256(raw).hexdigest()
    output = {
        "release_id": RELEASE_ID,
        "copyright": "Copyright 2026 Agnus Dei Technologies, LLC. All rights reserved.",
        "scope": "Student-facing original instruction for Grades 9-12; adult keys, worked models and private records excluded.",
        "grades": list(GRADES), "strands": {s: SUBJECT[s] for s in STRANDS},
        "review": {
            "method": "Separate AI author and AI reviewer passes, independent key verification and safety review, bound to exact content hashes.",
            "review_summary_sha256": hashlib.sha256(args.review_summary.read_bytes()).hexdigest(),
            "approved_lessons": review["approved_lessons"],
            "adjudicated_lessons": review["adjudicated_lessons"],
            "human_accepted": False,
        },
        "pilot_evaluated": False,
        "institutionally_promoted": False,
        "weeks": weeks, "lesson_files": lesson_files,
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=1) + "\n")
    print(f"Exported {len(lessons)} student-facing Grades 9-12 records; no adult keys copied.")


if __name__ == "__main__":
    main()
