"""Deterministic, entirely fabricated two-campus pilot fixtures.

Never replace these with exported school records. IDs are stable, synthetic
UUIDv4-shaped values so they match the G1 API's parser during replayable denial
tests; no names, identifiers, or emails come from people.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

_NAMESPACE = UUID("5cde68fb-9b92-49c0-b52f-b15b2c7029e1")


@dataclass(frozen=True)
class SyntheticLearner:
    learner_id: str
    campus_id: str
    display_name: str


@dataclass(frozen=True)
class SyntheticCampus:
    campus_id: str
    label: str
    learners: tuple[SyntheticLearner, ...]


def _id(kind: str, label: str) -> str:
    # G1's deployed _id() accepts only canonical UUIDv4 IDs.
    # Reproducible test-only v4-shaped IDs ensure each run addresses the same
    # fabricated learner, without ever using exported or actual school data.
    digest = sha256(f"{_NAMESPACE}/bede-synthetic-pilot/{kind}/{label}".encode()).digest()
    return str(UUID(bytes=digest[:16], version=4))


def two_campus_fixture() -> tuple[SyntheticCampus, SyntheticCampus]:
    """Two distinct tenants with intentionally identical learner display names."""
    campuses = []
    for campus_label in ("synthetic-campus-alpha", "synthetic-campus-beta"):
        campus_id = _id("campus", campus_label)
        learners = tuple(
            SyntheticLearner(
                learner_id=_id("learner", f"{campus_label}/{index}"),
                campus_id=campus_id,
                display_name="Example Learner",
            )
            for index in (1, 2)
        )
        campuses.append(SyntheticCampus(campus_id, campus_label, learners))
    return campuses[0], campuses[1]


def assert_synthetic_fixture() -> None:
    """Fail early if fixtures lose unique tenant/learner identity."""
    a, b = two_campus_fixture()
    assert a.campus_id != b.campus_id
    assert {x.learner_id for x in a.learners}.isdisjoint(
        {x.learner_id for x in b.learners}
    )
    assert all(x.campus_id == a.campus_id for x in a.learners)
    assert all(x.campus_id == b.campus_id for x in b.learners)
    assert a.learners[0].display_name == b.learners[0].display_name
