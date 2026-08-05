"""services/content_curation.py — the gate new library content passes.

Two things are being pinned here. First, that each rule in
docs/CONTENT_CONTRIBUTING.md and each relevant constitutional rule actually
blocks something, rather than being a paragraph nobody enforces. Second — and
this is the one that makes a growing library safe — that content cannot join
the library without saying what it teaches, so the diagnostic and the
curriculum cannot silently drift apart.
"""
import pytest

from models.schemas import GradeStage, Subject
from services.content_curation import (
    ContentCandidate,
    curate,
    curate_all,
    known_skill_ids,
)


def candidate(**kwargs) -> ContentCandidate:
    base = dict(
        id="y3-test",
        title="A Test Entry",
        subject=Subject.history,
        exercises_no_tracked_skill=True,
    )
    base.update(kwargs)
    return ContentCandidate(**base)


def rules(verdict) -> set:
    return {finding.rule for finding in verdict.findings}


def blocking_rules(verdict) -> set:
    return {finding.rule for finding in verdict.blocking}


# ── The baseline ────────────────────────────────────────────────────────


def test_a_clean_candidate_is_accepted():
    assert curate(candidate()).accepted


def test_acceptance_means_nothing_mechanical_is_wrong_not_that_it_is_good():
    """Documented explicitly because the name invites the other reading."""
    verdict = curate(candidate(title="A Dull But Valid Entry"))
    assert verdict.accepted
    assert verdict.findings == []


def test_all_findings_are_returned_not_just_the_first():
    """A contributor should fix one submission once, not rediscover the next
    problem on every run."""
    verdict = curate(candidate(
        subject=Subject.living_books,   # missing anti_twaddle
        verbatim_text="some text",      # no source, not public domain
        skills=["not_a_real_skill"],
        exercises_no_tracked_skill=False,
    ))
    assert len(verdict.findings) >= 4


# ── Mastery linkage: the check that keeps the library and the engine in step ──


def test_content_must_say_what_it_exercises():
    """A library that grows without saying what it teaches drifts away from
    what the diagnostic measures — and the symptom a parent sees is their
    child appearing to fail at material Bede never taught."""
    verdict = curate(candidate(exercises_no_tracked_skill=False))
    assert "mastery.linkage_undeclared" in blocking_rules(verdict)


def test_exercising_nothing_is_allowed_but_must_be_explicit():
    """A poem does not map to a math skill. Saying so is honest; leaving the
    field empty is indistinguishable from never filling it in."""
    assert curate(candidate(exercises_no_tracked_skill=True)).accepted


def test_an_empty_skill_list_alone_is_not_a_declaration():
    verdict = curate(candidate(skills=[], exercises_no_tracked_skill=False))
    assert "mastery.linkage_undeclared" in blocking_rules(verdict)


def test_content_cannot_invent_a_skill_id():
    """MasteryProfile stores skill ids as the only link to a family's
    accumulated history, and there is no ALTER TABLE path. Growing the map is
    a separate, deliberately reviewed change — never a side effect of adding
    a poem."""
    verdict = curate(candidate(
        skills=["oa.telepathy"], exercises_no_tracked_skill=False
    ))
    assert "mastery.unknown_skill" in blocking_rules(verdict)


def test_content_may_reference_a_real_skill():
    real = sorted(known_skill_ids())[0]
    verdict = curate(candidate(skills=[real], exercises_no_tracked_skill=False))
    assert verdict.accepted


def test_declaring_both_skills_and_none_is_contradictory():
    verdict = curate(candidate(
        skills=[sorted(known_skill_ids())[0]], exercises_no_tracked_skill=True
    ))
    assert "mastery.contradictory_linkage" in blocking_rules(verdict)


def test_known_skill_ids_spans_every_subject_area():
    """Read live from the diagnostic modules rather than copied, so this
    cannot drift from the maps it validates against."""
    ids = known_skill_ids()
    assert "oa.add_within_20" in ids          # skill_map (mathematics)
    assert "phonological_awareness" in ids    # phonics
    assert "decoding_multisyllable" in ids    # literacy
    assert "latin" in ids                     # language exposure
    assert len(ids) > 100


# ── Truth ───────────────────────────────────────────────────────────────


def test_verbatim_text_needs_a_source():
    verdict = curate(candidate(
        verbatim_text="Some quoted line", public_domain=True
    ))
    assert "truth.source_required" in blocking_rules(verdict)


def test_verbatim_text_with_a_source_is_fine():
    verdict = curate(candidate(
        verbatim_text="Some quoted line",
        source="Checked against the 1872 first edition facsimile",
        public_domain=True,
    ))
    assert verdict.accepted


def test_a_known_misattribution_is_flagged():
    """Seeded from a real finding in this repo: 'Ora et Labora' appears
    nowhere in St. Benedict's Rule, and latin_catalog.py says so rather than
    repeating the pleasant, universally-repeated, false attribution."""
    verdict = curate(candidate(
        body="St. Benedict taught us Ora et Labora — pray and work.",
    ))
    assert "truth.known_misattribution" in rules(verdict)


def test_a_misattribution_warns_rather_than_blocks():
    """It may be being quoted precisely in order to correct it — which is
    what latin_catalog.py does."""
    verdict = curate(candidate(
        body="The motto 'Ora et Labora' is often credited to St. Benedict, "
             "but it is Maurus Wolter, Beuron, 1880.",
    ))
    assert verdict.accepted


# ── Copyright ───────────────────────────────────────────────────────────


def test_verbatim_copyrighted_text_is_refused():
    """docs/CONTENT_CONTRIBUTING.md's one hard rule."""
    verdict = curate(candidate(
        verbatim_text="A modern translation's exact wording",
        source="Some 1990s edition",
        public_domain=False,
    ))
    assert "copyright.verbatim_requires_public_domain" in blocking_rules(verdict)


# ── Formation ───────────────────────────────────────────────────────────


def test_a_living_book_must_declare_anti_twaddle():
    verdict = curate(candidate(subject=Subject.living_books))
    assert "formation.anti_twaddle" in blocking_rules(verdict)


def test_a_living_book_declaring_anti_twaddle_is_fine():
    verdict = curate(candidate(subject=Subject.living_books, anti_twaddle=True))
    assert verdict.accepted


def test_anti_twaddle_false_is_not_the_same_as_declared():
    verdict = curate(candidate(subject=Subject.living_books, anti_twaddle=False))
    assert "formation.anti_twaddle" in blocking_rules(verdict)


# ── Stage fit ───────────────────────────────────────────────────────────


def test_logic_content_may_not_target_k2():
    """Enforced in four places already. This is the fifth route in, and it
    is closed too."""
    verdict = curate(candidate(
        subject=Subject.logic, stages=[GradeStage.foundations]
    ))
    assert "stage.logic_is_never_k2" in blocking_rules(verdict)


def test_logic_content_at_the_logic_stage_is_fine():
    verdict = curate(candidate(
        subject=Subject.logic, stages=[GradeStage.core_mastery]
    ))
    assert verdict.accepted


# ── Physical safety ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        "Light a candle and watch the wax melt.",
        "Climb the tree to reach the nest.",
        "Throw the ball as hard as you can to test momentum.",
        "Cut the leaf with scissors.",
        "Taste each of the three powders.",
    ],
)
def test_hazardous_activities_are_flagged(body):
    """_physical_safety_guardrails() constrains Bede's OWN suggestions. It
    says nothing about material handed to it, so content could route around
    it entirely."""
    verdict = curate(candidate(body=body))
    assert "safety.physical_hazard" in rules(verdict)


def test_an_ordinary_activity_is_not_flagged():
    verdict = curate(candidate(
        body="Draw what you noticed in your nature notebook with a pencil."
    ))
    assert "safety.physical_hazard" not in rules(verdict)


# ── Faith scope ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "subject", [Subject.scripture, Subject.latin, Subject.greek]
)
def test_tradition_neutral_subjects_reject_denominational_doctrine(subject):
    """scripture is denomination-neutral by design, and latin/greek are
    deliberately usable by a family holding none of the distinctively
    Catholic doctrines — tests/test_latin_catalog.py already asserts that
    against the rendered prompt."""
    verdict = curate(candidate(
        subject=subject,
        body="Here we pray the Ave Maria and consider purgatory.",
    ))
    assert "faith.tradition_neutrality" in blocking_rules(verdict)


def test_the_saints_module_may_carry_catholic_material():
    """It is explicitly Catholic in scope — that is the whole point of it
    existing alongside scripture."""
    verdict = curate(candidate(
        subject=Subject.saints,
        body="The rosary, and the intercession of the saints.",
    ))
    assert verdict.accepted


def test_a_faith_engagement_metric_is_refused():
    """CLAUDE.md: never measure, score, or quantify a child's spiritual
    engagement or growth. A content field is as good a place to introduce
    one as a database column."""
    verdict = curate(candidate(extra_fields={"faith_engagement_score": 7}))
    assert "faith.no_engagement_metric" in blocking_rules(verdict)


@pytest.mark.parametrize(
    "field_name",
    ["piety_score", "spiritual_growth_score", "devotion_level", "holiness_rating"],
)
def test_every_shape_of_faith_metric_is_refused(field_name):
    verdict = curate(candidate(extra_fields={field_name: 1}))
    assert "faith.no_engagement_metric" in blocking_rules(verdict)


# ── Batches ─────────────────────────────────────────────────────────────


def test_duplicate_ids_in_a_batch_are_caught():
    """Ids are lookup keys. test_catalog_data_integrity.py already checks
    global uniqueness of what is committed; this catches it before it is."""
    verdicts = curate_all([candidate(id="same"), candidate(id="same")])
    assert all("id.duplicate" in blocking_rules(v) for v in verdicts)


def test_distinct_ids_in_a_batch_are_fine():
    verdicts = curate_all([candidate(id="a"), candidate(id="b")])
    assert all(v.accepted for v in verdicts)


def test_an_empty_batch_is_fine():
    assert curate_all([]) == []
