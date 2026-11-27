"""Shared curriculum routing for every client; no demo-specific content tier.

This describes existing adapters, not a second content engine or a promotion
path. A selectable grade is not evidence of an authored full-year release.
"""
from hashlib import sha256
from pathlib import Path

from models.schemas import VALID_GRADES

CONTRACT_VERSION = 1
CATALOG_DIR = Path(__file__).resolve().parents[1] / "data/catalog"


def normalize_grade(grade: str) -> str:
    value = grade.strip().upper()
    if value == "0":
        value = "K"
    if value not in VALID_GRADES:
        raise ValueError("Unsupported curriculum grade")
    return value


def catalog_year_for_grade(grade: str) -> int | None:
    """One mapping used by tutoring and discovery; never map high school to K–8."""
    value = normalize_grade(grade)
    if value in ("K", "1"):
        return 1
    return int(value) if int(value) <= 8 else None


def curriculum_availability() -> dict:
    """Public source/version metadata only: no learner plans or adult answers."""
    from services.grade8_curriculum_service import DATA_FILE, RELEASE_ID, enabled, load

    # Use the existing integrity-checked adapter. A missing/tampered accepted
    # release must fail explicitly, not be relabeled as ready or fall back.
    accepted = load()
    accepted_release = {
        "release_id": RELEASE_ID,
        "source_sha256": sha256(DATA_FILE.read_bytes()).hexdigest(),
        "runtime_enabled": enabled(),
        "reviewed_records": accepted["reviewed_records"],
    }
    grades = []
    for grade in VALID_GRADES:
        year = catalog_year_for_grade(grade)
        catalog = CATALOG_DIR / f"year{year}.json" if year else None
        grades.append({
            "grade": grade,
            "default_route": "catalog_guided" if year else "grade_specific_practice",
            "catalog_year": year,
            "catalog_sha256": sha256(catalog.read_bytes()).hexdigest() if catalog else None,
            "accepted_full_year": accepted_release if grade == "8" else None,
        })
    return {"contract_version": CONTRACT_VERSION, "grades": grades}
