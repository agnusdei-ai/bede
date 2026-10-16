"""G1: name search returns only authorized, UUID-backed learners, and every
bad learner id fails identically without disclosing anything.

Real HTTP through the assembled app (tests/g1_harness.py). SQLite by
default; Postgres when G1_TEST_DATABASE_URL is set.
"""
import pytest

from g1_harness import SAME_NAME, world  # noqa: F401 (fixture)

NOT_FOUND = {"detail": "Record not found"}


def _search(w, teacher_headers, query):
    return w.client.post("/pilot/me/learners/search", json={"query": query}, headers=teacher_headers)


# ── search ──────────────────────────────────────────────────────────────────

def test_search_returns_only_the_teachers_own_uuid_backed_learner(world):
    w = world
    one = _search(w, w.teacher(w.teacher_one), "synthetic")
    two = _search(w, w.teacher(w.teacher_two), "Synthetic Learner")
    assert one.status_code == two.status_code == 200
    assert one.json() == [{"learner_id": w.learner_one, "campus_id": w.campus_one, "display_name": SAME_NAME}]
    assert two.json() == [{"learner_id": w.learner_two, "campus_id": w.campus_two, "display_name": SAME_NAME}]


def test_search_never_reveals_another_campus_learner_or_a_revoked_one(world):
    w = world
    assert _search(w, w.teacher(w.teacher_one), "no such learner").json() == []
    w.revoke(w.campus_one, w.teacher_one, w.learner_one)
    assert _search(w, w.teacher(w.teacher_one), SAME_NAME).json() == []
    # Teacher Two's learner has the same name and is still never visible.
    assert _search(w, w.teacher(w.teacher_one), "Synthetic").json() == []
    # An empty query is a validation error, not a way to list everyone.
    assert _search(w, w.teacher(w.teacher_one), "").status_code == 422


def test_search_result_is_used_by_uuid_and_the_name_cannot_stand_in(world):
    w = world
    t1 = w.teacher(w.teacher_one)
    hit = _search(w, t1, SAME_NAME).json()[0]
    assert w.client.get(f"/pilot/me/learners/{hit['learner_id']}", headers=t1).status_code == 200
    by_name = w.client.get(f"/pilot/me/learners/{SAME_NAME}", headers=t1)
    assert (by_name.status_code, by_name.json()) == (404, NOT_FOUND)
    # The voice start a search result leads to takes the UUID, never the name.
    assert w.client.post("/voice/stream/start", json={"learner_id": hit["learner_id"]},
                         headers=t1).status_code == 200
    r = w.client.post("/voice/stream/start", json={"student_name": SAME_NAME}, headers=t1)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


def test_search_query_is_not_accepted_in_the_url(world):
    w = world
    t1 = w.teacher(w.teacher_one)
    r = w.client.get(f"/pilot/me/learners/search?query={SAME_NAME}", headers=t1)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


def test_search_requires_an_educator(world):
    w = world
    assert _search(w, w.admin(), SAME_NAME).status_code in (401, 403)


# ── uniform failure ─────────────────────────────────────────────────────────

def _bad_ids(w):
    return {
        "random_v4": "1b4e28ba-2fa1-41d2-883f-0016d3cca427",
        "nil": "00000000-0000-0000-0000-000000000000",
        "non_v4": "6f9619ff-8b86-1011-b42d-00cf4fc964ff",
        "uppercase": w.learner_one.upper(),
        "braced": "{" + w.learner_one + "}",
        "malformed": "not-a-uuid",
        "display_name": SAME_NAME,
        "blank": "%20",
        "overlong": "a" * 300,
        "other_campus": w.learner_two,
        "campus_id_as_learner": w.campus_one,
    }


def test_every_bad_learner_id_reads_byte_for_byte_the_same(world):
    w = world
    t1 = w.teacher(w.teacher_one)
    bodies = {}
    for label, bad in _bad_ids(w).items():
        r = w.client.get(f"/pilot/me/learners/{bad}", headers=t1)
        assert r.status_code == 404, (label, r.status_code)
        bodies[label] = r.content
    assert len(set(bodies.values())) == 1, bodies
    assert b'"Record not found"' in next(iter(bodies.values()))


def test_a_stale_learner_id_reads_the_same_as_one_that_never_existed(world):
    w = world
    w.revoke(w.campus_one, w.teacher_one, w.learner_one)
    t1 = w.teacher(w.teacher_one)  # a FRESH token: the id is what is stale
    stale = w.client.get(f"/pilot/me/learners/{w.learner_one}", headers=t1)
    never = w.client.get("/pilot/me/learners/1b4e28ba-2fa1-41d2-883f-0016d3cca427", headers=t1)
    assert (stale.status_code, stale.content) == (never.status_code, never.content)
    assert stale.json() == NOT_FOUND


@pytest.mark.parametrize("disable", ["learner", "campus", "membership"])
def test_a_disabled_link_reads_the_same_as_one_that_never_existed(world, disable):
    w = world

    async def turn_off():
        from core.database import PilotCampus, PilotEducatorCampus, PilotLearner
        async with w.factory() as s:
            row = {
                "learner": lambda: s.get(PilotLearner, w.learner_one),
                "campus": lambda: s.get(PilotCampus, w.campus_one),
                "membership": lambda: s.get(PilotEducatorCampus, (w.teacher_one, w.campus_one)),
            }[disable]
            (await row()).enabled = False
            await s.commit()
    w.run(turn_off)
    r = w.client.get(f"/pilot/me/learners/{w.learner_one}", headers=w.teacher(w.teacher_one))
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


def test_failures_disclose_no_protected_metadata(world):
    w = world
    t2 = w.teacher(w.teacher_two)
    r = w.client.get(f"/pilot/me/learners/{w.learner_one}", headers=t2)
    text = r.text
    for secret in (w.learner_one, w.campus_one, w.teacher_one, SAME_NAME):
        assert secret not in text
    assert set(r.headers) - {"date", "server"} == set(
        w.client.get("/pilot/me/learners/1b4e28ba-2fa1-41d2-883f-0016d3cca427", headers=t2).headers
    ) - {"date", "server"}
