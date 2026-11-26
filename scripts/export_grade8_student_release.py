"""Project an accepted private Grade 8 year into explicitly public fields.

Run locally against the retained authoring worktree. Never copy its Git
history, original source bundles, teacher models, keys or placement plans.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import subprocess


def verify_authoring_source(root, commit):
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("Invalid accepted authoring commit")
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", commit, "--", "curriculum/grade-8-year/*.py"],
        check=False,
    )
    if result.returncode:
        raise ValueError("Accepted Grade 8 authoring implementation changed or is unavailable")


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
        "access": {k: lesson["access"][k] for k in
                   ("construct", "supports", "alternative_response")},
        "safety": {k: lesson["safety"][k] for k in
                   ("hazards", "supervision", "stop_escalation", "safer_alternative")},
        "sources": [
            {**{k: sources[ref["source"]["id"]][k] for k in
                ("title", "creator_editor_translator", "edition", "url",
                 "license", "attribution", "notices")},
             "locator": ref["locator"]}
            for ref in lesson["source_refs"]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-worktree", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_worktree.resolve()
    acceptance = json.loads(args.acceptance.read_bytes())
    if acceptance["decision"] != "accepted_authored_year":
        raise ValueError("Explicit whole-year educational acceptance required")
    accepted = acceptance["accepted_version"]
    verify_authoring_source(root, accepted["local_commit"])
    sys.path.insert(0, str(root / "curriculum/grade-8-year"))
    import export_whole_year as year
    import year_plan
    import build
    for name, digest in accepted["files"].items():
        raw = (year.OUTPUT / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"Accepted artifact changed: {name}")
    _, review = year.reviewed_evidence()
    immutable, _ = year.audited_index()
    lessons = {}
    for name in year.REVIEW_TARGETS:
        for row in build.load(name).LESSONS:
            bundle = year.configured_bundle(name, row)
            public = student_lesson(bundle)
            public.update(strand=name, week=row[0])
            public["prerequisite_objective_ids"] = (
                year_plan.assignment(name, row[0])["planned_prerequisite_objectives"]
                if not name.startswith("quarter_") else []
            )
            if f"{name}:{row[0]}" not in immutable:
                raise ValueError("Missing verified factory record")
            lessons[public["id"]] = public
    if len(lessons) != 592:
        raise ValueError("Incomplete reviewed projection")
    weeks = {}
    for pathway in year_plan.PATHWAYS:
        weeks[pathway] = {}
        for week in range(1, 37):
            plan = year_plan.weekly(week, pathway)
            weeks[pathway][str(week)] = {
                "lesson_ids": [a["lesson_id"] for a in plan["assignments"]],
                "reading_minutes": plan["reading_minutes"],
                "composition_scope": plan["composition_scope"],
                "quarter_assessment": plan["quarter_assessment"],
                "retention_due_week": plan["retention_due_week"],
                "geography": {k: plan["geography_within_history"][k] for k in (
                    "week", "site", "latitude", "longitude", "region", "coordinate_status",
                    "primary_text", "historical_map", "task", "minutes_within_history")},
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lesson_dir = args.output.parent / "grade8-student"
    lesson_dir.mkdir(exist_ok=True)
    lesson_files = {}
    for strand in year.REVIEW_TARGETS:
        rows = [lesson for lesson in lessons.values() if lesson["strand"] == strand]
        raw = (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode()
        (lesson_dir / f"{strand}.json").write_bytes(raw)
        lesson_files[strand] = hashlib.sha256(raw).hexdigest()
    resource_files = {}
    with zipfile.ZipFile(year.OUTPUT / "student-year-bundle.zip") as archive:
        for original, destination in (
            ("geography-atlas.html", "grade8-atlas.html"),
            ("original-learning-aids.html", "grade8-visual-source.html"),
        ):
            raw = archive.read(original)
            (args.output.parent / destination).write_bytes(raw)
            resource_files[destination] = hashlib.sha256(raw).hexdigest()
    output = {
        "release_id": "bede-grade8-2026-accepted",
        "copyright": "Copyright 2026 Agnus Dei Technologies, LLC. All rights reserved.",
        "scope": "Student-facing original instruction; teacher keys and private plans excluded.",
        "accepted_authoring_commit": accepted["local_commit"],
        "review_sha256": hashlib.sha256((year.OUTPUT / "whole-year-review.json").read_bytes()).hexdigest(),
        "reviewed_records": len(review["covered_record_hashes"]),
        "pilot_evaluated": False,
        "institutionally_promoted": False,
        "weeks": weeks, "lesson_files": lesson_files, "resource_files": resource_files,
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"Exported {len(lessons)} student-facing records; no private source bundles copied.")


if __name__ == "__main__":
    main()
