"""The adult's optional first name, for the greeting on their own screens only.

A DISPLAY value. It is never an identity, never a credential and never an
authorization input: nothing here is read by auth, by a route guard, by the
tutor prompt, by an email, by a log line or by the audit log's detail text.
It is returned by one parent-only route and shown as text.

Optional: no row means no name, and every screen has a nameless greeting.
Stored encrypted (a constant row key, like the other single-row parent
settings), in a table that has no student column, so it is not part of any
learner's export or deletion cascade; the adult clears it with the same
route that sets it.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import ParentProfile
from core.encryption import aad_for, decrypt_json, encrypt_json

_KEY = "profile"
MAX_NAME_CHARS = 50


def clean_name(value: object) -> str:
    """A first name for display. Clean, never reject: whitespace becomes a
    single space, markup and prompt-structure characters and control
    characters are dropped, and the result is cut to MAX_NAME_CHARS."""
    spaced = "".join(" " if ch.isspace() else ch for ch in str(value or ""))
    kept = "".join(ch for ch in spaced if ch.isprintable() and ch not in "<>{}[]`\\")
    return " ".join(kept.split())[:MAX_NAME_CHARS]


def _aad() -> bytes:
    return aad_for("parent_profile", "name_enc", "parent")


async def get_name(db: AsyncSession) -> str | None:
    row = await db.get(ParentProfile, _KEY)
    if row is None:
        return None
    name = clean_name((decrypt_json(row.name_enc, _aad()) or {}).get("name", ""))
    return name or None


async def set_name(db: AsyncSession, value: object) -> str | None:
    """Store the cleaned name; an empty or all-junk value clears it. Returns
    the name now stored, or None."""
    name = clean_name(value)
    if not name:
        await clear_name(db)
        return None
    blob = encrypt_json({"name": name}, _aad())
    row = await db.get(ParentProfile, _KEY)
    if row is None:
        db.add(ParentProfile(key=_KEY, name_enc=blob))
    else:
        row.name_enc = blob
    await db.commit()
    return name


async def clear_name(db: AsyncSession) -> None:
    row = await db.get(ParentProfile, _KEY)
    if row is not None:
        await db.delete(row)
        await db.commit()
