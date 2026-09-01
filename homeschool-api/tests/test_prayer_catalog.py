"""
Regression tests for the weekly Catholic prayer rotation
(services/prayer_catalog.py) — mirrors test_poetry_catalog.py's coverage
of the identical weekly-rotation architecture (see that file's own docstring
for the fuller "why" behind each check), plus the locale-based text
selection this catalog adds on top (English/Spanish, per the session's own
login-time locale — see routers/auth.py's login()).
"""
from datetime import date

import pytest

from models.schemas import GradeStage, SessionConfig, Subject, VALID_GRADES
from services.ai_service import _build_subject_prompt, _session_position_note
from services.prayer_catalog import (
    _COLLECTION,
    _DAILY_COLLECTION,
    current_week,
    daily_prayer_for,
    daily_prayer_note,
    prayer_for_week,
    prayer_note,
)

pytestmark = pytest.mark.asyncio


async def test_every_grade_stage_has_at_least_one_prayer():
    for stage in (GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent):
        assert any(stage in e["stages"] for e in _COLLECTION), stage


async def test_every_individual_grade_has_at_least_one_prayer():
    for grade in VALID_GRADES:
        assert any(grade in e["grades"] for e in _COLLECTION), grade


async def test_every_entry_has_nonempty_bilingual_text_grades_and_stages():
    for entry in _COLLECTION:
        assert entry["text_en"].strip()
        assert entry["text_es"].strip()
        assert entry["grades"]
        assert entry["stages"]
        assert entry["title"]
        assert entry["attribution"]


async def test_stages_are_derived_from_grades_not_hand_maintained():
    from models.schemas import grade_to_stage
    for entry in _COLLECTION:
        assert entry["stages"] == {grade_to_stage(g) for g in entry["grades"]}


async def test_current_week_is_the_iso_week_number():
    assert current_week(date(2026, 7, 15)) == date(2026, 7, 15).isocalendar()[1]


async def test_prayer_for_week_with_a_grade_only_returns_entries_tagged_for_that_grade():
    for grade in VALID_GRADES:
        for week in range(1, 53):
            entry = prayer_for_week(grade, GradeStage.foundations, today=date.fromisocalendar(2026, week, 1))
            assert grade in entry["grades"]


async def test_prayer_for_week_falls_back_to_stage_when_grade_is_none():
    for stage in (GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent):
        for week in range(1, 53):
            entry = prayer_for_week(None, stage, today=date.fromisocalendar(2026, week, 1))
            assert stage in entry["stages"]


async def test_prayer_for_week_falls_back_to_stage_for_an_unrecognized_grade():
    entry = prayer_for_week("13", GradeStage.independent, today=date(2026, 7, 15))
    assert GradeStage.independent in entry["stages"]


async def test_prayer_for_week_changes_across_the_calendar_year():
    for grade in VALID_GRADES:
        titles = {
            prayer_for_week(grade, GradeStage.foundations, today=date.fromisocalendar(2026, week, 1))["title"]
            for week in range(1, 53)
        }
        assert len(titles) > 1


async def test_prayer_for_week_is_stable_within_the_same_calendar_week():
    same_week_a = prayer_for_week("7", GradeStage.independent, today=date(2026, 7, 13))  # Monday
    same_week_b = prayer_for_week("7", GradeStage.independent, today=date(2026, 7, 19))  # Sunday, same ISO week
    assert same_week_a["title"] == same_week_b["title"]


async def test_week_salt_can_change_which_prayer_is_picked():
    fixed_date = date(2026, 7, 15)
    titles = {
        prayer_for_week("3", GradeStage.core_mastery, week_salt=salt, today=fixed_date)["title"]
        for salt in range(9)
    }
    assert len(titles) > 1


async def test_prayer_note_includes_the_verbatim_english_text_by_default():
    note = prayer_note("8", GradeStage.independent, today=date(2026, 7, 15))
    entry = prayer_for_week("8", GradeStage.independent, today=date(2026, 7, 15))
    assert entry["text_en"] in note
    assert entry["text_es"] not in note
    assert entry["title"] in note
    assert "VERBATIM" in note
    assert "never recite it from memory" in note


async def test_prayer_note_uses_spanish_text_when_locale_is_es():
    note = prayer_note("8", GradeStage.independent, locale="es", today=date(2026, 7, 15))
    entry = prayer_for_week("8", GradeStage.independent, today=date(2026, 7, 15))
    assert entry["text_es"] in note
    assert entry["text_en"] not in note


async def test_prayer_note_falls_back_to_english_for_an_untranslated_locale():
    note = prayer_note("8", GradeStage.independent, locale="pl", today=date(2026, 7, 15))
    entry = prayer_for_week("8", GradeStage.independent, today=date(2026, 7, 15))
    assert entry["text_en"] in note


async def test_prayer_note_returns_empty_string_when_nothing_matches():
    assert prayer_note(None, None, today=date(2026, 7, 15)) == ""


async def test_prayer_note_never_frames_recitation_as_scored_or_measured():
    """Bede's constitution (CLAUDE.md) forbids quantifying a child's faith
    engagement — this prompt block must actively steer away from that, not
    just happen not to mention it."""
    note = prayer_note("3", GradeStage.foundations, today=date(2026, 7, 15))
    assert "never a quiz" in note
    assert "never something you score or measure" in note


# ── Wiring into _build_subject_prompt ───────────────────────────────────────
#
# locale is a per-request parameter here (the login-time JWT claim — see
# routers/auth.py's login()), not read from settings.locale globally, so
# these pass it directly rather than monkeypatching settings.

def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


async def test_prayer_recitation_is_included_for_morning_time():
    prompt = await _build_subject_prompt(_config(), Subject.morning_time)
    assert "<prayer_recitation>" in prompt


async def test_prayer_recitation_is_omitted_for_other_subjects():
    prompt = await _build_subject_prompt(_config(), Subject.mathematics)
    assert "<prayer_recitation>" not in prompt

    # living_books gets the poetry catalog but not the prayer catalog —
    # prayer recitation is Morning Time's own territory, not literature time.
    prompt = await _build_subject_prompt(_config(), Subject.living_books)
    assert "<prayer_recitation>" not in prompt


async def test_prayer_recitation_follows_the_requesting_sessions_locale():
    entry = prayer_for_week("4", GradeStage.core_mastery, week_salt=_config().current_term)
    prompt = await _build_subject_prompt(_config(), Subject.morning_time, locale="es")
    assert entry["text_es"] in prompt
    assert entry["text_en"] not in prompt


async def test_prayer_recitation_defaults_to_english_when_locale_omitted():
    entry = prayer_for_week("4", GradeStage.core_mastery, week_salt=_config().current_term)
    prompt = await _build_subject_prompt(_config(), Subject.morning_time)
    assert entry["text_en"] in prompt
    assert entry["text_es"] not in prompt


# ── Daily opening/closing prayer catalog (Sacred Rule 10) ───────────────────
#
# Backs the day's opening/closing prayer moment so Bede never composes it
# itself — see services/prayer_catalog.py's own docstring on _DAILY_COLLECTION
# for why this replaced an earlier "freshly adapted" free-composition design.

async def test_every_daily_entry_has_nonempty_bilingual_text_and_a_valid_moment():
    for entry in _DAILY_COLLECTION:
        assert entry["text_en"].strip()
        assert entry["text_es"].strip()
        assert entry["title"]
        assert entry["attribution"]
        assert entry["tradition"] in ("catholic", "christian")
        assert entry["moments"] and entry["moments"] <= {"opening", "closing"}


async def test_daily_collection_spans_both_catholic_and_christian_traditions():
    traditions = {e["tradition"] for e in _DAILY_COLLECTION}
    assert traditions == {"catholic", "christian"}


async def test_both_opening_and_closing_moments_have_entries():
    assert any("opening" in e["moments"] for e in _DAILY_COLLECTION)
    assert any("closing" in e["moments"] for e in _DAILY_COLLECTION)


async def test_daily_prayer_for_only_returns_entries_tagged_for_that_moment():
    for day in range(1, 32):
        opening = daily_prayer_for("opening", today=date(2026, 1, day))
        assert "opening" in opening["moments"]
        closing = daily_prayer_for("closing", today=date(2026, 1, day))
        assert "closing" in closing["moments"]


async def test_daily_prayer_for_changes_across_the_month():
    titles = {daily_prayer_for("closing", today=date(2026, 1, day))["title"] for day in range(1, 32)}
    assert len(titles) > 1


async def test_daily_prayer_for_is_stable_for_the_same_calendar_day():
    a = daily_prayer_for("opening", today=date(2026, 7, 15))
    b = daily_prayer_for("opening", today=date(2026, 7, 15))
    assert a["title"] == b["title"]


async def test_daily_prayer_note_includes_verbatim_text_and_the_never_compose_instruction():
    note = daily_prayer_note("opening", today=date(2026, 7, 15))
    entry = daily_prayer_for("opening", today=date(2026, 7, 15))
    assert entry["text_en"] in note
    assert entry["text_es"] not in note
    assert entry["title"] in note
    assert "VERBATIM" in note
    assert "never compose, paraphrase, or improvise a prayer of your own" in note


async def test_daily_prayer_note_uses_spanish_text_when_locale_is_es():
    note = daily_prayer_note("closing", locale="es", today=date(2026, 7, 15))
    entry = daily_prayer_for("closing", today=date(2026, 7, 15))
    assert entry["text_es"] in note
    assert entry["text_en"] not in note


async def test_session_position_note_never_leaves_bede_to_compose_its_own_prayer():
    config = SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery, subjects=[Subject.morning_time],
    )
    note = _session_position_note(config, Subject.morning_time, today=date(2026, 7, 15))
    assert "<daily_prayer moment=\"opening\">" in note
    assert "<daily_prayer moment=\"closing\">" in note


# ── Moment retagging + pool growth ───────────────────────────────────────────
#
# Before this pass, three prayers were tagged opening-only and five
# closing-only — mechanically correct (the code always picked SOME entry
# tagged for the moment) but too small a pool for a real school week: a
# child heard the identical opening prayer up to 4 times in a 10-day sprint.
# See services/prayer_catalog.py's own docstring on _DAILY_COLLECTION for
# the honest-character reasoning behind which prayers moved.

# Prayers whose actual content/liturgical shape ties them to one specific
# end of the day — these must NEVER gain the other moment, however tempting
# it is to keep growing the pool, or the retagging stops being honest.
#
# The 2026-09 additions are classified here too, and deliberately not all
# swept into "either" to fatten both pools: each of the four below looks
# FORWARD by its own words — a day being made, words about to be spoken,
# paths about to be walked, wisdom about to be asked for — which is an
# opening and not a send-off.
_GENUINELY_OPENING_ONLY = {"Come, Holy Spirit", "Prayer Before Study",
                           "This Is the Day (Psalm 118:24)",
                           "Let the Words of My Mouth (Psalm 19:14)",
                           "Show Me Your Ways (Psalm 25:4-5)",
                           "If Anyone Lacks Wisdom (James 1:5)"}
_GENUINELY_CLOSING_ONLY = {"The Blessing (Numbers 6:24-26)", "Now I Lay Me Down to Sleep",
                           "The Grace (2 Corinthians 13:14)"}

# Prayers general enough in content to honestly serve either end of the
# day — these must carry BOTH moments, not just one, or the pool shrinks
# back toward the problem this pass fixed.
_GENUINELY_EITHER_MOMENT = {"Prayer of St. Francis", "Glory Be (Doxology)", "The Doxology",
                            "The Serenity Prayer", "Let Nothing Disturb You (St. Teresa's Bookmark)",
                            # Asking for a clean heart, and asking for mercy,
                            # are both as true at the end of a day as at the
                            # start; neither is shaped as a greeting or a
                            # send-off.
                            "Create in Me a Clean Heart (Psalm 51:10)",
                            "The Jesus Prayer"}


async def test_genuinely_single_moment_prayers_were_not_widened():
    by_title = {e["title"]: e for e in _DAILY_COLLECTION}
    for title in _GENUINELY_OPENING_ONLY:
        assert by_title[title]["moments"] == {"opening"}, title
    for title in _GENUINELY_CLOSING_ONLY:
        assert by_title[title]["moments"] == {"closing"}, title


async def test_genuinely_general_prayers_serve_both_moments():
    by_title = {e["title"]: e for e in _DAILY_COLLECTION}
    for title in _GENUINELY_EITHER_MOMENT:
        assert by_title[title]["moments"] == {"opening", "closing"}, title


async def test_every_daily_prayer_is_accounted_for_in_exactly_one_honesty_bucket():
    # A future addition that isn't sorted into one of the three buckets above
    # is a future addition nobody actually reasoned about — this catches
    # that omission rather than letting a new entry pass silently.
    titles = {e["title"] for e in _DAILY_COLLECTION}
    accounted = _GENUINELY_OPENING_ONLY | _GENUINELY_CLOSING_ONLY | _GENUINELY_EITHER_MOMENT
    assert titles == accounted


async def test_daily_pool_did_not_shrink_back_down():
    # Regression floor, not a target — the fix here was measured (3->7
    # opening, 5->8 closing); this only guards against silently losing it.
    opening = sum(1 for e in _DAILY_COLLECTION if "opening" in e["moments"])
    closing = sum(1 for e in _DAILY_COLLECTION if "closing" in e["moments"])
    assert opening >= 6, opening
    assert closing >= 6, closing


async def test_a_ten_day_sprint_does_not_repeat_the_same_prayer_more_than_twice():
    """The actual complaint this pass answers: a family running an
    intense, near-daily 2-week sprint should not hear the identical
    opening or closing prayer three or more times in that stretch.
    Simulates a real 10-school-day run (Mon-Fri x2) the same way the
    investigation that led to this fix did, rather than asserting an
    abstract pool-size number."""
    from collections import Counter
    from datetime import timedelta

    start = date(2026, 8, 3)  # a Monday
    school_days = [start + timedelta(days=d) for d in range(14) if (start + timedelta(days=d)).weekday() < 5]
    assert len(school_days) == 10

    for moment in ("opening", "closing"):
        titles = [daily_prayer_for(moment, today=d)["title"] for d in school_days]
        most_repeated = max(Counter(titles).values())
        assert most_repeated <= 2, (moment, most_repeated, titles)


# ── The two prayers added in this pass ───────────────────────────────────────

async def test_st_teresas_bookmark_is_present_and_well_formed():
    by_title = {e["title"]: e for e in _DAILY_COLLECTION}
    entry = by_title["Let Nothing Disturb You (St. Teresa's Bookmark)"]
    assert "Let nothing disturb you" in entry["text_en"]
    assert "God alone suffices" in entry["text_en"]
    assert "Nada te turbe" in entry["text_es"]
    assert "solo Dios basta" in entry["text_es"]
    assert entry["tradition"] == "catholic"


async def test_the_grace_2_corinthians_is_present_and_well_formed():
    by_title = {e["title"]: e for e in _DAILY_COLLECTION}
    entry = by_title["The Grace (2 Corinthians 13:14)"]
    assert "grace of the Lord Jesus Christ" in entry["text_en"]
    assert "fellowship of the Holy Spirit" in entry["text_en"]
    assert "gracia del Señor Jesucristo" in entry["text_es"]
    assert entry["tradition"] == "christian"
    # A benediction that closes a letter has no business opening a lesson.
    assert entry["moments"] == {"closing"}


# ── Corrections found by cross-checking against real published sources ──────
#
# Regression guards for real drift this pass found and fixed — see
# services/prayer_catalog.py's module docstring for the sourcing and the
# full account of each. Pinned so a future edit can't silently reintroduce
# any of them.

async def test_grace_after_meals_uses_the_real_archaic_verb_forms():
    entry = next(e for e in _COLLECTION if e["title"] == "Grace After Meals")
    assert "livest and reignest" in entry["text_en"]
    assert "lives and reigns" not in entry["text_en"]


async def test_morning_offering_carries_its_real_intercessions_not_a_flat_ending():
    entry = next(e for e in _COLLECTION if e["title"] == "Morning Offering")
    assert "salvation of souls" in entry["text_en"]
    assert "reparation for sin" in entry["text_en"]
    assert "reunion of all Christians" in entry["text_en"]
    assert "Holy Father" in entry["text_en"]
    assert "salvación de las almas" in entry["text_es"]


async def test_prayer_before_study_carries_the_double_darkness_and_eloquence_clauses():
    entry = next(e for e in _DAILY_COLLECTION if e["title"] == "Prayer Before Study")
    assert "double darkness" in entry["text_en"]
    assert "thoroughness and charm" in entry["text_en"]
    assert "doble oscuridad" in entry["text_es"]


async def test_spanish_prayer_of_st_francis_carries_its_own_traditions_full_clause_set():
    entry = next(e for e in _DAILY_COLLECTION if e["title"] == "Prayer of St. Francis")
    assert "discordia" in entry["text_es"]
    assert "unión" in entry["text_es"]
    assert "error" in entry["text_es"]
    assert "verdad" in entry["text_es"]


# ── The weekday lock (reported 2026-09) ───────────────────────────────────
#
# A parent reported Bede recycling the opening prayers. The cause was not
# pool size, it was arithmetic: daily_prayer_for indexed with
# `ordinal % len(entries)`, a calendar ordinal advances by 7 across a week,
# and there were exactly 7 opening prayers. `% 7` on an ordinal is therefore
# a pure function of the WEEKDAY. Every Monday drew "Prayer Before Study",
# every Tuesday "Prayer of St. Francis", forever, and the two entries that
# landed on Saturday and Sunday were never heard by a Mon-Fri family.
#
# The sprint test above passed throughout, and passed BECAUSE of the bug: a
# perfect weekday lock over two weeks yields exactly 2 of each, landing
# exactly on its "no more than twice" threshold. It measured repeat count
# and never asked how many distinct prayers were reachable. These tests ask
# the second question.


def _school_days(start: date, weeks: int) -> list:
    from datetime import timedelta
    return [
        start + timedelta(days=d)
        for d in range(weeks * 7)
        if (start + timedelta(days=d)).weekday() < 5
    ]


async def test_no_weekday_is_locked_to_a_single_prayer():
    """The bug itself. Over a long horizon each weekday must draw many
    different prayers — if any weekday yields exactly one, the index has
    become a function of the day of the week again."""
    from datetime import timedelta

    start = date(2026, 9, 7)  # a Monday
    for moment in ("opening", "closing"):
        by_weekday: dict[int, set] = {}
        for d in range(7 * 20):
            day = start + timedelta(days=d)
            if day.weekday() >= 5:
                continue
            by_weekday.setdefault(day.weekday(), set()).add(
                daily_prayer_for(moment, today=day)["title"]
            )
        for weekday, titles in sorted(by_weekday.items()):
            assert len(titles) > 1, (
                f"{moment}: weekday {weekday} always draws {titles} — the index "
                "is a function of the day of the week again. Check that "
                "daily_prayer_for still adds the cycle number rather than "
                "using a bare `% len(entries)`."
            )


async def test_every_prayer_is_reachable_by_a_monday_to_friday_family():
    """Two prayers were stranded on Saturday and Sunday and could never be
    heard by a family schooling Mon-Fri. Pool entries that no real session
    can reach are worse than absent: they read as content while being
    unreachable."""
    for moment in ("opening", "closing"):
        pool = {e["title"] for e in _DAILY_COLLECTION if moment in e["moments"]}
        seen = {
            daily_prayer_for(moment, today=d)["title"]
            for d in _school_days(date(2026, 9, 7), weeks=12)
        }
        assert pool <= seen, (
            f"{moment}: never reachable on a school day: {sorted(pool - seen)}"
        )


async def test_a_school_month_of_opening_prayers_is_genuinely_varied():
    """The parent's actual ask: rotation THROUGH the month, not within the
    week. Asserted on the opening moment, which is the one reported, and
    against a real 20-school-day month rather than an abstract pool size.

    No rotation function can beat pool depth here — 20 sittings cannot be
    varied out of 7 prayers — so this necessarily also guards the size of
    the opening pool, and says so rather than leaving a future reader to
    wonder why trimming the catalog broke a rotation test."""
    from collections import Counter

    days = _school_days(date(2026, 9, 7), weeks=4)
    assert len(days) == 20

    counts = Counter(daily_prayer_for("opening", today=d)["title"] for d in days)
    assert len(counts) >= 12, (
        f"only {len(counts)} distinct opening prayers in a 20-day school month "
        f"(was 5 when this was reported): {counts}"
    )
    assert max(counts.values()) <= 2, (
        f"an opening prayer repeats {max(counts.values())}x in one school "
        f"month: {counts.most_common(3)}"
    )


async def test_each_aligned_block_covers_the_whole_pool_exactly_once():
    """Still a rotation, not a shuffle: within one block of N days the pool
    is exhausted before anything repeats.

    ALIGNED blocks specifically. A window straddling a boundary crosses the
    cycle shift, so it repeats one prayer and skips another — the first
    version of this test asserted the stronger "any N consecutive days"
    property, taken from a code comment that claimed it, and failed. The
    comment was wrong and is now corrected; this is the true property."""
    from datetime import timedelta

    for moment in ("opening", "closing"):
        size = len([e for e in _DAILY_COLLECTION if moment in e["moments"]])
        # Start on a block boundary so the run does not cross the shift.
        start = date(2026, 9, 7)
        start += timedelta(days=(-start.toordinal()) % size)
        assert start.toordinal() % size == 0

        for block in range(3):
            titles = [
                daily_prayer_for(moment, today=start + timedelta(days=block * size + d))["title"]
                for d in range(size)
            ]
            assert len(set(titles)) == size, (
                f"{moment} block {block}: {size} days covered only "
                f"{len(set(titles))} distinct prayers"
            )


async def test_the_index_does_not_lock_to_a_weekday_at_a_pool_size_of_seven(monkeypatch):
    """Guards the ARITHMETIC, not today's pool size — and this file needed
    that distinction pointed out by its own failure.

    The tests above were written first and passed against the OLD
    `ordinal % len(entries)` index, because the same change that fixed the
    bug also grew the opening pool from 7 to 13, and 13 is coprime with 7.
    The symptom vanished on pool size alone and the guards proved nothing.

    `% N` on a calendar ordinal collapses to the weekday exactly when N
    divides 7, so the danger returns silently the moment someone trims the
    catalog back to seven opening prayers — a plausible edit, since three of
    the current thirteen are recent additions. This pins the property at the
    size where it breaks, with a synthetic pool, so it fails on the
    arithmetic regardless of what the real catalog happens to hold.
    """
    from datetime import timedelta

    import services.prayer_catalog as pc

    seven = [
        {"title": f"P{i}", "attribution": "t", "tradition": "christian",
         "moments": {"opening"}, "text_en": "x", "text_es": "x"}
        for i in range(7)
    ]
    monkeypatch.setattr(pc, "_DAILY_COLLECTION", seven)

    start = date(2026, 9, 7)  # a Monday
    by_weekday: dict[int, set] = {}
    for d in range(7 * 12):
        day = start + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        by_weekday.setdefault(day.weekday(), set()).add(
            pc.daily_prayer_for("opening", today=day)["title"]
        )

    for weekday, titles in sorted(by_weekday.items()):
        assert len(titles) > 1, (
            f"with a 7-entry pool, weekday {weekday} always draws {titles}. "
            "daily_prayer_for has gone back to a bare `% len(entries)`, which "
            "is a pure function of the weekday whenever the pool size divides "
            "7 — the original reported bug."
        )

    # And every entry must still be reachable by a Mon-Fri family at that size.
    reachable = {
        pc.daily_prayer_for("opening", today=start + timedelta(days=d))["title"]
        for d in range(7 * 12)
        if (start + timedelta(days=d)).weekday() < 5
    }
    assert len(reachable) == 7, f"only {len(reachable)}/7 reachable on school days"
