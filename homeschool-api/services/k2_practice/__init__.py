"""K-2 practice: Watch, Together, Your turn (docs/K2_PRACTICE.md).

What every practice area shares: the closed list of areas, which of them is
built, the subjects each belongs to, the card each one's invitation carries,
and the record of which areas were already offered in a session.

Only phonics is built (step 1 of the spec's build order). The other areas
are named so `invite_practice`'s `area` field is a closed list from the
start, and are refused until their own step ships: a card inviting a round
that does not exist is worse than no card.

Nothing here is model-written. A lesson is built by the area's own module
(phonics.py) and checked by its routes (routers/k2_practice.py).
"""
from __future__ import annotations

import time

from models.schemas import Subject

#: The closed vocabulary of `invite_practice`'s `area` field (spec §4).
AREAS = ("phonics", "handwriting", "math", "spelling", "copy_sentence")

#: Built and offerable. Every other area is refused at prompt build and at
#: dispatch until its own build step ships.
ENABLED_AREAS = frozenset({"phonics"})

#: The subjects each area belongs to (spec §5). An offer is also limited to
#: the subjects actually in that child's routine today.
AREA_SUBJECTS: dict[str, tuple[Subject, ...]] = {
    "phonics": (Subject.language_arts, Subject.living_books),
}

#: The card's prefix, the same in every locale, so the once-a-session scan
#: of the conversation keys on it rather than on translated words (the same
#: reason ai_service's _MAP_CARD_PREFIX exists).
CARD_PREFIX: dict[str, str] = {
    "phonics": "\U0001F524 ",  # the "input latin letters" symbol
}

# ── Which areas were offered in which session ────────────────────────────────
# The conversation history a turn carries is the current subject's only, so a
# history scan alone would allow a second phonics offer when the child moves
# from Language Arts to Living Books. The session id (TutorRequest.session_id,
# minted per sitting) closes that. In memory, like turn ids (docs/RELIABILITY.md):
# a restart can at worst allow one more offer, never record anything.
_OFFER_TTL_SECONDS = 12 * 60 * 60
_MAX_OFFERS = 4096
_offered: dict[tuple[str, str, str], float] = {}


def _sweep(now: float) -> None:
    if len(_offered) < _MAX_OFFERS:
        return
    for key in [k for k, at in _offered.items() if now - at > _OFFER_TTL_SECONDS]:
        _offered.pop(key, None)
    while len(_offered) >= _MAX_OFFERS:
        _offered.pop(next(iter(_offered)))


def mark_offered(student_name: str, session_id: str | None, area: str) -> None:
    if not session_id:
        return
    now = time.monotonic()
    _sweep(now)
    _offered[(student_name, session_id, area)] = now


def was_offered(student_name: str, session_id: str | None, area: str) -> bool:
    if not session_id:
        return False
    at = _offered.get((student_name, session_id, area))
    return at is not None and time.monotonic() - at <= _OFFER_TTL_SECONDS
