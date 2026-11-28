"""Program-aware routing of Bede support; no external retrieval or learner data."""
from copy import deepcopy
import re

PROGRAM_IDS = ("bede", "valor", "memoria_press", "other")


def program_id(value):
    if value not in PROGRAM_IDS:
        raise ValueError("Choose a supported classical curriculum program")
    return value


def validate(data, unit_ids):
    programs = data["programs"]
    if set(programs) != set(PROGRAM_IDS):
        raise ValueError("Missing curriculum program references")
    for key, program in programs.items():
        for field in ("label", "description", "coverage_note"):
            if not all(program[field].get(lang) for lang in ("en", "es")):
                raise ValueError("Incomplete program language")
        for reference in program["references"]:
            if not reference["url"].startswith("https://") or not reference["locator"]:
                raise ValueError("Missing first-party program reference")
        for unit_id, match in program["matches"].items():
            if unit_id not in unit_ids or type(match["min_grade"]) is not int:
                raise ValueError("Invalid program placement")
            if not 4 <= match["min_grade"] <= 12 or not match["reference_url"].startswith("https://"):
                raise ValueError("Invalid program reference")
            if match["reference_isbn"] and not re.fullmatch(r"\d{13}", match["reference_isbn"]):
                raise ValueError("Invalid reference ISBN")
            if match["reference_kind"] not in ("reading_text", "study_guide"):
                raise ValueError("Distinguish a reading text from a study guide")
    for field in ("program_schedule_note", "program_edition_note"):
        if not all(data[field].get(lang) for lang in ("en", "es")):
            raise ValueError("Missing program/source distinction")
    steps = data["program_steps"]
    for route in (steps["valor"]["lower"], steps["valor"]["upper"], steps["memoria_press"]):
        if len(route) != 3 or not all(all(row.get(lang) for lang in ("en", "es")) for row in route):
            raise ValueError("Incomplete program-specific tutoring support")


def view(data, program, locale):
    program = program_id(program)
    row = data["programs"][program]
    return {
        "id": program, "label": row["label"][locale],
        "description": row["description"][locale],
        "coverage_note": row["coverage_note"][locale],
        "schedule_note": data["program_schedule_note"][locale],
        "references": deepcopy(row["references"]),
    }


def eligible(data, program, unit, grade):
    program = program_id(program)
    if grade < unit["min_grade"]:
        return False
    if program in ("bede", "other"):
        return True
    match = data["programs"][program]["matches"].get(unit["id"])
    return match is not None and grade >= match["min_grade"]


def course_match(data, program, unit, locale):
    row = data["programs"][program_id(program)]["matches"].get(unit["id"])
    if row is None:
        return None
    return {
        "work": row["work"], "placement": row["placement"],
        "reference_isbn": row["reference_isbn"], "reference_url": row["reference_url"],
        "reference_kind": row["reference_kind"],
        "edition_note": data["program_edition_note"][locale],
    }


def support_step(data, program, grade, week, locale):
    """Original guidance, not copied publisher questions or a school timetable."""
    program_id(program)
    if program == "valor":
        route = data["program_steps"]["valor"]["upper" if grade >= 9 else "lower"]
    elif program == "memoria_press":
        route = data["program_steps"]["memoria_press"]
    else:
        return []
    return [{
        "label": "Preparación para el programa" if locale == "es" else "Program preparation",
        "instruction": route[week - 1][locale],
    }]
