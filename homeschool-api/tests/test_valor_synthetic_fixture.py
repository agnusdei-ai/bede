"""Fixture invariants only; these do not prove deployed G1 authorization."""
from uuid import UUID

from valor_synthetic_fixture import assert_synthetic_fixture, two_campus_fixture


def test_synthetic_campuses_have_distinct_stable_ids():
    first = two_campus_fixture()
    assert first == two_campus_fixture()
    assert first[0].campus_id != first[1].campus_id
    for campus in first:
        assert UUID(campus.campus_id).version == 4
        for learner in campus.learners:
            assert UUID(learner.learner_id).version == 4
            assert learner.campus_id == campus.campus_id


def test_same_named_learners_have_distinct_identity():
    alpha, beta = two_campus_fixture()
    assert alpha.learners[0].display_name == beta.learners[0].display_name
    assert alpha.learners[0].learner_id != beta.learners[0].learner_id
    assert_synthetic_fixture()


def test_ids_round_trip_through_g1_canonical_uuid_parser():
    # Parser logic mirrors the deployed G1 pilot route: canonical lowercase v4.
    alpha, beta = two_campus_fixture()
    all_ids = [alpha.campus_id, beta.campus_id] + [
        learner.learner_id for campus in (alpha, beta) for learner in campus.learners
    ]
    for value in all_ids:
        parsed = UUID(value)
        assert parsed.version == 4
        assert str(parsed) == value
    assert len(set(all_ids)) == len(all_ids)
