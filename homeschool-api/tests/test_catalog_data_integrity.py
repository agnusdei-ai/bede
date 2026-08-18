"""
Data-integrity safety net for the curated content catalogs — see
docs/CONTENT_CONTRIBUTING.md. Not testing application logic; testing the
DATA itself, so a future content contribution (a new book, saint, visual
aid, or poem) fails loudly in CI on a malformed entry instead of silently
shipping a broken lookup (a duplicate id silently shadowing an earlier
entry, an empty required field, a subject value that doesn't match any
real Subject enum member).
"""
import json
from pathlib import Path

import pytest

from models.schemas import BIBLE_TRANSLATIONS, PUBLIC_DOMAIN_BIBLE_TRANSLATIONS, GradeStage, Subject
from services import catalog_service

_DATA_DIR = Path(__file__).parent.parent / "data"
_VALID_SUBJECTS = {s.value for s in Subject}


def _load_year_files() -> list[tuple[str, dict]]:
    catalog_dir = _DATA_DIR / "catalog"
    return [
        (f.name, json.loads(f.read_text(encoding="utf-8")))
        for f in sorted(catalog_dir.glob("year*.json"))
    ]


YEAR_FILES = _load_year_files()


def test_at_least_one_year_file_exists():
    assert YEAR_FILES, "no data/catalog/year*.json files found"


@pytest.mark.parametrize("filename,data", YEAR_FILES, ids=[f[0] for f in YEAR_FILES])
def test_year_file_has_required_top_level_fields(filename, data):
    assert "year" in data, f"{filename} missing top-level 'year'"
    assert isinstance(data["year"], int), f"{filename}'s 'year' must be an int"
    assert "books" in data and isinstance(data["books"], list), f"{filename} missing 'books' list"


@pytest.mark.parametrize("filename,data", YEAR_FILES, ids=[f[0] for f in YEAR_FILES])
def test_every_book_has_required_non_empty_fields(filename, data):
    required = ("id", "title", "author", "subject", "type")
    for book in data["books"]:
        for field in required:
            assert book.get(field), f"{filename}: book {book.get('id', '?')!r} missing/empty {field!r}"
        assert book["type"] in ("spine", "supplemental", "reference"), (
            f"{filename}: book {book['id']!r} has unknown type {book['type']!r} "
            f"(expected spine/supplemental/reference)"
        )


@pytest.mark.parametrize("filename,data", YEAR_FILES, ids=[f[0] for f in YEAR_FILES])
def test_every_book_subject_is_a_real_subject_enum_value(filename, data):
    for book in data["books"]:
        assert book["subject"] in _VALID_SUBJECTS, (
            f"{filename}: book {book['id']!r} has subject {book['subject']!r}, "
            f"not a real Subject enum value"
        )


def test_book_ids_are_globally_unique_across_every_year():
    seen: dict[str, str] = {}
    for filename, data in YEAR_FILES:
        for book in data["books"]:
            book_id = book["id"]
            assert book_id not in seen, (
                f"duplicate book id {book_id!r} in {filename} (already used in {seen.get(book_id)!r}) "
                f"— a duplicate silently shadows the earlier entry in catalog_service's lookup index"
            )
            seen[book_id] = filename


# ── Catechism ────────────────────────────────────────────────────────────

def test_catechism_covers_every_grade_one_through_eight():
    for grade in ("1", "2", "3", "4", "5", "6", "7", "8"):
        note = catalog_service.get_catechism_note(grade)
        assert note is not None, f"no Faith and Life entry for grade {grade}"


# ── Visual aids ──────────────────────────────────────────────────────────

def _load_visual_aids_raw() -> list[dict]:
    raw = json.loads((_DATA_DIR / "visual_aids.json").read_text(encoding="utf-8"))
    return raw.get("visual_aids", [])


def test_visual_aid_ids_are_unique():
    entries = _load_visual_aids_raw()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate id in data/visual_aids.json"


def test_every_visual_aid_has_required_non_empty_fields():
    required = ("id", "subject", "category", "title", "wiki_title", "description")
    for entry in _load_visual_aids_raw():
        for field in required:
            assert entry.get(field), f"visual aid {entry.get('id', '?')!r} missing/empty {field!r}"
        assert entry["subject"] in _VALID_SUBJECTS, (
            f"visual aid {entry['id']!r} has subject {entry['subject']!r}, not a real Subject enum value"
        )


# ── Composer catalog ─────────────────────────────────────────────────────

def _load_composer_works_raw() -> list[dict]:
    raw = json.loads((_DATA_DIR / "composer_catalog.json").read_text(encoding="utf-8"))
    return raw.get("composer_works", [])


def test_composer_work_ids_are_unique():
    entries = _load_composer_works_raw()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate id in data/composer_catalog.json"


def test_every_composer_work_has_required_non_empty_fields():
    required = (
        "id", "subject", "composer", "composer_dates", "work_title", "movement",
        "era", "forces", "composer_bio", "listening_notes",
    )
    for entry in _load_composer_works_raw():
        for field in required:
            assert entry.get(field), f"composer work {entry.get('id', '?')!r} missing/empty {field!r}"
        assert entry["subject"] in _VALID_SUBJECTS, (
            f"composer work {entry['id']!r} has subject {entry['subject']!r}, not a real Subject enum value"
        )


def test_every_composer_work_has_all_three_stage_notes():
    # Must key by GradeStage MEMBER NAME ("foundations"/"core_mastery"/
    # "independent") — services/ai_service.py's _get_composer_context looks
    # entries up by config.grade_stage.name, not .value ("K-2"/"3-5"/"6-8").
    required_stages = {s.name for s in GradeStage}
    for entry in _load_composer_works_raw():
        stage_notes = entry.get("stage_notes") or {}
        missing = required_stages - stage_notes.keys()
        assert not missing, f"composer work {entry['id']!r} missing stage_notes for {missing}"
        for stage, note in stage_notes.items():
            assert note, f"composer work {entry['id']!r} has an empty stage_notes[{stage!r}]"


# ── Bible translation copyright permissions ─────────────────────────────────

def _load_bible_permissions_raw() -> dict:
    path = _DATA_DIR / "bible_translations" / "copyright_permissions.json"
    return json.loads(path.read_text(encoding="utf-8")).get("translations", {})


def test_every_copyrighted_translation_has_a_permissions_entry():
    copyrighted = [t for t in BIBLE_TRANSLATIONS if t not in PUBLIC_DOMAIN_BIBLE_TRANSLATIONS]
    entries = _load_bible_permissions_raw()
    for translation in copyrighted:
        assert translation in entries, f"no copyright_permissions.json entry for {translation!r}"


def test_no_stray_entries_for_public_domain_translations():
    entries = _load_bible_permissions_raw()
    for translation in PUBLIC_DOMAIN_BIBLE_TRANSLATIONS:
        assert translation not in entries, (
            f"{translation!r} is public domain (PUBLIC_DOMAIN_BIBLE_TRANSLATIONS) and shouldn't have a "
            "copyright_permissions.json entry at all"
        )


def test_every_permissions_entry_has_required_non_empty_fields():
    required = ("publisher", "conditions", "source")
    for code, entry in _load_bible_permissions_raw().items():
        for field in required:
            assert entry.get(field), f"{code!r} missing/empty {field!r}"
        assert entry["source"].startswith("https://"), f"{code!r}'s source isn't a real URL: {entry['source']!r}"
        has_verses = "free_quote_verses" in entry
        has_words = "free_quote_words" in entry
        assert has_verses != has_words, (
            f"{code!r} must have exactly one of free_quote_verses/free_quote_words, not both or neither"
        )


def test_get_bible_translation_permission_returns_none_for_public_domain():
    for translation in PUBLIC_DOMAIN_BIBLE_TRANSLATIONS:
        assert catalog_service.get_bible_translation_permission(translation) is None


def test_get_bible_translation_permission_returns_data_for_copyrighted():
    permission = catalog_service.get_bible_translation_permission("ESV")
    assert permission is not None
    assert permission["publisher"] == "Crossway"
