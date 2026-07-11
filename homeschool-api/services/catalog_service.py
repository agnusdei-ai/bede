"""
Catalog service — loads Ambleside Online Year 1-3 book lists from JSON seed files
at import time. Static in-memory data; no database required.

Functions:
  get_years()                               -> list of available year numbers
  get_books(year, subject=None)             -> books for a year, optionally filtered
  get_book(book_id)                         -> single book dict or None
  search_books(query)                       -> full-text search across title/author/tags
  get_catalog_note(year, subject)           -> brief context note for the AI subject prompt
  get_catechism_note(grade)                 -> Faith and Life grade-level orientation for `saints`
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# ── Load catalog JSON files at import time ────────────────────────────────────

_DATA_DIR = Path(__file__).parent.parent / "data" / "catalog"
_VISUAL_AIDS_FILE = Path(__file__).parent.parent / "data" / "visual_aids.json"
_CATECHISM_FILE = Path(__file__).parent.parent / "data" / "catechism" / "faith_and_life.json"

# _CATALOG: year (int) -> {"year": int, "description": str, "books": list[dict]}
_CATALOG: dict[int, dict] = {}

# _BOOK_INDEX: book_id (str) -> book dict (with "year" injected)
_BOOK_INDEX: dict[str, dict] = {}

# _VISUAL_AIDS: visual_aid id (str) -> entry dict
_VISUAL_AIDS: dict[str, dict] = {}

# _CATECHISM: grade (str, e.g. "1".."8") -> {"book_title": str, "theme": str, "topics": list[str]}
_CATECHISM: dict[str, dict] = {}


def _load_catalog() -> None:
    """Load all year*.json files from the data/catalog directory."""
    if not _DATA_DIR.exists():
        log.warning("Catalog data directory not found: %s — catalog endpoints will return empty", _DATA_DIR)
        return

    files_found = 0
    for json_file in sorted(_DATA_DIR.glob("year*.json")):
        try:
            with json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            year = int(data["year"])
            _CATALOG[year] = data
            for book in data.get("books", []):
                enriched = {**book, "year": year}
                _BOOK_INDEX[book["id"]] = enriched
            files_found += 1
            log.info("Catalog loaded: %s (%d books)", json_file.name, len(data.get("books", [])))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            log.warning("Failed to load catalog file %s: %s", json_file, exc)

    if files_found == 0:
        log.warning("No catalog JSON files found in %s", _DATA_DIR)
    else:
        log.info("Catalog ready: %d years, %d books total", len(_CATALOG), len(_BOOK_INDEX))


def _load_visual_aids() -> None:
    """Load the curated picture-study/map/artifact catalog for show_visual_aid."""
    if not _VISUAL_AIDS_FILE.exists():
        log.warning("Visual aids file not found: %s — show_visual_aid will have nothing to offer", _VISUAL_AIDS_FILE)
        return
    try:
        with _VISUAL_AIDS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("visual_aids", []):
            _VISUAL_AIDS[entry["id"]] = entry
        log.info("Visual aids loaded: %d entries", len(_VISUAL_AIDS))
    except (json.JSONDecodeError, KeyError) as exc:
        log.warning("Failed to load visual aids file: %s", exc)


def _load_catechism() -> None:
    """Load the Faith and Life grade-level orientation data. See
    data/catechism/faith_and_life.json's own _comment for the sourcing and
    scope disclaimer (thematic orientation, not a claimed-exhaustive chapter
    list, never the book's actual text)."""
    if not _CATECHISM_FILE.exists():
        log.info("Catechism data file not found: %s — saints subject won't get Faith and Life context", _CATECHISM_FILE)
        return
    try:
        with _CATECHISM_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        _CATECHISM.update(data.get("grades", {}))
        log.info("Catechism catalog loaded: %d grades", len(_CATECHISM))
    except (json.JSONDecodeError, KeyError) as exc:
        log.warning("Failed to load catechism file %s: %s", _CATECHISM_FILE, exc)


_load_catalog()
_load_visual_aids()
_load_catechism()


# ── Public API ────────────────────────────────────────────────────────────────

def get_years() -> list[int]:
    """Return sorted list of available curriculum years."""
    return sorted(_CATALOG.keys())


def get_books(year: int, subject: str | None = None) -> list[dict]:
    """
    Return all books for a given year.
    If subject is provided, filter to that subject only.
    Returns empty list for unknown years.
    """
    year_data = _CATALOG.get(year)
    if year_data is None:
        return []

    books = [
        {**book, "year": year}
        for book in year_data.get("books", [])
    ]

    if subject:
        books = [b for b in books if b.get("subject") == subject]

    return books


def get_book(book_id: str) -> dict | None:
    """Return a single book by its unique id slug, or None if not found."""
    return _BOOK_INDEX.get(book_id)


def search_books(query: str) -> list[dict]:
    """
    Case-insensitive search across title, author, and concept_tags.
    Returns all matching books across all years, sorted by year then title.
    """
    if not query or not query.strip():
        return []

    q = query.strip().lower()
    results = []

    for book in _BOOK_INDEX.values():
        # Search title
        if q in book.get("title", "").lower():
            results.append(book)
            continue
        # Search author
        if q in book.get("author", "").lower():
            results.append(book)
            continue
        # Search concept_tags
        if any(q in tag.lower() for tag in book.get("concept_tags", [])):
            results.append(book)
            continue
        # Search notes
        if q in book.get("notes", "").lower():
            results.append(book)
            continue

    results.sort(key=lambda b: (b.get("year", 0), b.get("title", "")))
    return results


def get_catalog_note(year: int | None, subject: str | None) -> str | None:
    """
    Return a brief catalog context note for the AI subject prompt, given a year and subject.
    Used by ai_service._build_subject_prompt() to guide Bede on what books are in scope.

    Returns None if year or subject is unknown, so the caller can skip injection gracefully.
    """
    if year is None or subject is None:
        return None

    books = get_books(year, subject)
    spine_books = [b for b in books if b.get("type") == "spine"]
    supplemental_books = [b for b in books if b.get("type") == "supplemental"]

    if not spine_books and not supplemental_books:
        return None

    lines = [f"Ambleside Online Year {year} — {subject.replace('_', ' ').title()} books:"]

    if spine_books:
        titles = ", ".join(
            f"{b['title']} ({b['author']})" for b in spine_books[:4]
        )
        lines.append(f"Core reading: {titles}")

    if supplemental_books:
        titles = ", ".join(
            f"{b['title']}" for b in supplemental_books[:3]
        )
        lines.append(f"Supplemental: {titles}")

    return " ".join(lines)


def get_visual_aids(subject: str) -> list[dict]:
    """
    Return curated visual aids (picture study art, historical maps/artifacts)
    available for a subject — only "art_music" and "history" have entries today.
    Used by ai_service._get_visual_aids_context() to tell Bede which ids are
    valid to reference for show_visual_aid, so it never invents one.
    """
    return [v for v in _VISUAL_AIDS.values() if v.get("subject") == subject]


def get_visual_aid(visual_aid_id: str) -> dict | None:
    """
    Server-side authoritative lookup for a single visual aid by id.
    Always resolve show_visual_aid's tool input through this — never pass a
    model-supplied id (or any other field it invents) straight to the client.
    """
    return _VISUAL_AIDS.get(visual_aid_id)


def get_subject_plan(year: int | None, subject: str) -> str | None:
    """
    Return the term plan for a non-book-list subject (mathematics, art_music,
    language_arts, morning_time) for a given year, or None if unavailable.
    Used by ai_service._get_catalog_context() the same way get_catalog_note()
    is used for the book-list subjects.
    """
    if year is None:
        return None
    year_data = _CATALOG.get(year)
    if year_data is None:
        return None
    return year_data.get("subject_plans", {}).get(subject)


def get_catechism_note(grade: str | None) -> str | None:
    """
    Return a brief Faith and Life (Ignatius Press) grade-level orientation
    note for the `saints` subject, given a grade like "3" or "K". Returns
    None for an unrecognized/ungraded value (e.g. "K", which the series
    doesn't cover — it starts at grade 1) so the caller can skip it
    gracefully, same contract as get_catalog_note(). See data/catechism/
    faith_and_life.json's _comment for what this is and isn't (thematic
    orientation, never the book's actual copyrighted text).
    """
    if not grade:
        return None
    grade = grade.strip()
    entry = _CATECHISM.get(grade)
    if entry is None:
        return None
    topics = "; ".join(entry.get("topics", []))
    return (
        f"Faith and Life Grade {grade} — \"{entry['book_title']}\" ({entry['theme']}). "
        f"This grade's topics include: {topics}."
    )
