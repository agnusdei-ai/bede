"""Fixture invariants only; these do not prove deployed G1 authorization."""
from uuid import UUID

from valor_synthetic_fixture import assert_synthetic_fixture, two_campus_fixture


def test_synthetic_campuses_have_distinct_stable_ids():
    first = two_campus_fixture()
    assert first == two_campus_fixture()
    assert first[0].campus_id != first[1].campus_id
    for campus in first:
        UUID(campus.campus_id)
        for learner in campus.learners:
            UUID(learner.learner_id)
            assert learner.campus_id == campus.campus_id


def test_same_named_learners_have_distinct_identity():
    alpha, beta = two_campus_fixture()
    assert alpha.learners[0].display_name == beta.learners[0].display_name
    assert alpha.learners[0].learner_id != beta.learners[0].learner_id
    assert_synthetic_fixture()
