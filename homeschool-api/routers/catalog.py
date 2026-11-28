"""
Catalog router — Mater Amabilis Year 1-3 reading list.

Book-list routes require authentication (parent or child). The Grade 8
release/atlas/visual-source routes serve only published original student
materials, never learner records or teacher keys. All are static source
data; these handlers make no database queries or external requests.

Routes:
  GET /catalog/years                     — list of available curriculum years
  GET /catalog/search?q=...             — search across all years
  GET /catalog/book/{book_id}           — single book detail
  GET /catalog/{year}/books             — all books for a year (?subject= filter)
  GET /catalog/{year}/books/{subject}   — books filtered to a specific subject
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response

from core.deps import require_real_user
from services.catalog_service import get_book, get_books, get_years, search_books

router = APIRouter(prefix="/catalog", tags=["catalog"])

@router.get("/classical-arts/assets/{asset_id}/{digest}.jpg")
async def classical_arts_image(asset_id: str, digest: str):
    from services.classical_arts_service import art_asset, SourceUnavailable
    try:
        return Response(art_asset(asset_id, digest), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/classical-arts")
async def classical_arts_catalog(
    grade: str = Query(pattern=r"^(?:[4-9]|1[0-2])$"), locale: str = "en",
    program: str = "bede",
):
    """Public source-bound unit metadata; no learner records or adult keys."""
    from services.classical_arts_service import SourceUnavailable, catalog
    try:
        return catalog(grade, locale, program)
    except SourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/classical-arts/{unit_id}")
async def classical_arts_lesson(
    unit_id: str, grade: str = Query(pattern=r"^(?:[4-9]|1[0-2])$"),
    week: int = Query(default=1, ge=1, le=3), locale: str = "en",
    support: str = Query(default="guided", pattern=r"^(guided|independent|extension)$"),
    program: str = "bede",
):
    from services.classical_arts_service import SourceUnavailable, lesson
    try:
        return lesson(unit_id, grade, week, locale, support, program)
    except SourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/curriculum-availability")
async def shared_curriculum_availability():
    """Public K–12 release metadata shared by demo, installed, and native clients."""
    from services.curriculum_delivery import curriculum_availability
    return curriculum_availability()


@router.get("/grade8/atlas")
async def grade8_atlas():
    from services.grade8_curriculum_service import DATA_FILE, load
    try:
        load()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(DATA_FILE.parent / "grade8-atlas.html", media_type="text/html",
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})


@router.get("/grade8/visual-source")
async def grade8_visual_source():
    from services.grade8_curriculum_service import DATA_FILE, load
    try:
        load()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(DATA_FILE.parent / "grade8-visual-source.html", media_type="text/html",
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})


@router.get("/grade8/release")
async def grade8_release(
    week: int = Query(default=1, ge=1, le=36),
    pathway: str = Query(default="foundations", pattern="^(foundations|algebra)$"),
) -> dict:
    """Public original student curriculum only; no user, campus or teacher data.

    Repository publication does not enable tutor activation. The explicit
    operator flag is returned so setup controls cannot promise availability.
    """
    from services.grade8_curriculum_service import RELEASE_ID, STRAND_SUBJECT, enabled, week_plan
    try:
        plan, lessons = week_plan(week, pathway)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "release_id": RELEASE_ID, "runtime_enabled": enabled(),
        "week": week, "pathway": pathway,
        "lessons": [{**lesson, "subject": STRAND_SUBJECT[lesson["strand"]]} for lesson in lessons],
        "reading_minutes": plan["reading_minutes"],
        "composition_scope": plan["composition_scope"],
        "quarter_assessment": plan["quarter_assessment"],
        "retention_due_week": plan["retention_due_week"],
        "pilot_evaluated": False,
    }


@router.get("/years")
async def list_years(
    _: dict = Depends(require_real_user),
) -> list[int]:
    """Return the sorted list of available Mater Amabilis curriculum years."""
    return get_years()


@router.get("/search")
async def search_catalog(
    q: str = Query(..., min_length=1, max_length=100, description="Search term"),
    _: dict = Depends(require_real_user),
) -> list[dict]:
    """
    Full-text search across title, author, concept_tags, and notes.
    Returns matching books from all years, sorted by year then title.
    """
    results = search_books(q)
    if not results:
        return []
    return results


@router.get("/book/{book_id}")
async def get_book_detail(
    book_id: str,
    _: dict = Depends(require_real_user),
) -> dict:
    """Return full detail for a single book by its unique id slug."""
    book = get_book(book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Book '{book_id}' not found in catalog.",
        )
    return book


@router.get("/{year}/books")
async def list_books_for_year(
    year: int,
    subject: str | None = Query(default=None, description="Filter by subject slug (e.g. 'living_books')"),
    _: dict = Depends(require_real_user),
) -> list[dict]:
    """
    Return all books for a curriculum year.
    Optionally filter by subject using the Subject enum slug value.
    """
    books = get_books(year, subject)
    if not books and year not in get_years():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Curriculum year {year} not found. Available years: {get_years()}",
        )
    return books


@router.get("/{year}/books/{subject}")
async def list_books_for_subject(
    year: int,
    subject: str,
    _: dict = Depends(require_real_user),
) -> list[dict]:
    """
    Return books for a specific subject in a curriculum year.
    Subject must be a valid Subject enum slug (e.g. 'living_books', 'history').
    """
    if year not in get_years():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Curriculum year {year} not found. Available years: {get_years()}",
        )
    books = get_books(year, subject)
    return books
