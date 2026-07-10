"""
Catalog router — Ambleside Online Year 1-3 reading list.

All routes require authentication (parent or child). The catalog is static
in-memory data loaded from data/catalog/ JSON files — no database queries.

Routes:
  GET /catalog/years                     — list of available curriculum years
  GET /catalog/search?q=...             — search across all years
  GET /catalog/book/{book_id}           — single book detail
  GET /catalog/{year}/books             — all books for a year (?subject= filter)
  GET /catalog/{year}/books/{subject}   — books filtered to a specific subject
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.deps import require_auth
from services.catalog_service import get_book, get_books, get_years, search_books

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/years")
async def list_years(
    _: dict = Depends(require_auth),
) -> list[int]:
    """Return the sorted list of available Ambleside Online curriculum years."""
    return get_years()


@router.get("/search")
async def search_catalog(
    q: str = Query(..., min_length=1, max_length=100, description="Search term"),
    _: dict = Depends(require_auth),
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
    _: dict = Depends(require_auth),
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
    _: dict = Depends(require_auth),
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
    _: dict = Depends(require_auth),
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
