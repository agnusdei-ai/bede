"""First-party program distinctions and actual source-bound tutor routing."""
import asyncio
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from models.schemas import Subject
from services import classical_arts_service as arts


def note(row, program, support="guided"):
    return (f"Bede classical arts: {row['unit_id']}; week={row['week']}; support={support}"
            f"; program={program}; assignment={row['selection_token']}")


def config(grade, current_unit):
    return SimpleNamespace(grade=str(grade), current_unit=current_unit, current_term=2)


@pytest.mark.parametrize("program,grade,expected", [
    ("valor", 4, set()),
    ("valor", 5, {"midsummer-scene"}),
    ("valor", 6, {"midsummer-scene", "caesar-plutarch"}),
    ("valor", 8, {"midsummer-scene", "caesar-plutarch", "merchant-mercy"}),
    ("valor", 10, {"midsummer-scene", "caesar-plutarch", "merchant-mercy", "macbeth-deliberation", "tempest-release"}),
    ("valor", 11, {"midsummer-scene", "caesar-plutarch", "merchant-mercy", "macbeth-deliberation", "tempest-release", "henryv-community"}),
    ("memoria_press", 7, set()),
    ("memoria_press", 8, {"caesar-plutarch"}),
    ("memoria_press", 9, {"midsummer-scene", "caesar-plutarch"}),
])
def test_actual_program_placement_not_a_shared_grade_guess(program, grade, expected):
    result = arts.catalog(str(grade), "en", program)
    assert result["program"]["id"] == program
    assert {unit["id"] for unit in result["units"]} == expected
    assert "not the school's or publisher's calendar" in result["program"]["schedule_note"]


@pytest.mark.parametrize("locale", ["en", "es"])
def test_program_references_distinguish_text_edition_from_guide(locale):
    valor = arts.lesson("midsummer-scene", "5", locale=locale, program="valor")
    press = arts.lesson("midsummer-scene", "9", locale=locale, program="memoria_press")
    assert valor["program_match"]["reference_isbn"] == "9780743477543"
    assert valor["program_match"]["reference_kind"] == "reading_text"
    assert press["program_match"]["reference_isbn"] == "9781547702299"
    assert press["program_match"]["reference_kind"] == "study_guide"
    assert press["program_match"]["placement"] == "9+"
    assert "GITenberg" in press["source"]["url"]
    assert press["source"] == valor["source"]  # Same verified passage, not either modern edition.
    assert press["program_match"]["edition_note"]
    assert press["program"]["description"] != valor["program"]["description"]


@pytest.mark.parametrize("unit,grade,program", [
    ("midsummer-scene", "8", "memoria_press"),
    ("caesar-plutarch", "5", "valor"),
    ("macbeth-deliberation", "9", "valor"),
    ("michelangelo-looking", "12", "valor"),
    ("merchant-mercy", "12", "memoria_press"),
])
def test_direct_lesson_requests_cannot_bypass_program_coverage(unit, grade, program):
    with pytest.raises(ValueError, match="verified program coverage"):
        arts.lesson(unit, grade, program=program)


@pytest.mark.parametrize("locale", ["en", "es"])
@pytest.mark.parametrize("week", [1, 2, 3])
def test_every_reconciled_week_has_source_specific_guided_entry_and_program_support(locale, week):
    midsummer = arts.lesson("midsummer-scene", "5", week, locale, program="valor")
    caesar = arts.lesson("caesar-plutarch", "6", week, locale, program="valor")
    press = arts.lesson("midsummer-scene", "9", week, locale, program="memoria_press")
    assert midsummer["steps"][-1]["instruction"] != caesar["steps"][-1]["instruction"]
    assert midsummer["steps"][-2]["instruction"] != press["steps"][-2]["instruction"]
    assert all(row["steps"][-1]["instruction"] for row in (midsummer, caesar, press))
    assert midsummer["source"]["id"] == "midsummer"
    assert caesar["source"]["id"] == ("north" if week == 1 else "caesar")
    assert press["rehearsal"] == midsummer["rehearsal"]


def test_operator_activation_and_version_bound_adult_selection(monkeypatch, tmp_path):
    row = arts.lesson("caesar-plutarch", "8", program="memoria_press")
    chosen = config(8, note(row, "memoria_press"))
    assert len(chosen.current_unit) <= 200
    assert arts.selection(chosen.current_unit) == ("caesar-plutarch", 1, "guided")
    monkeypatch.setenv("BEDE_CLASSICAL_ARTS_ENABLED", "false")
    with pytest.raises(arts.SourceUnavailable, match="not been activated"):
        arts.context(chosen, Subject.living_books)
    monkeypatch.setenv("BEDE_CLASSICAL_ARTS_ENABLED", "true")
    result = arts.context(chosen, Subject.living_books)
    assert "Grammar-stage preparation" in result
    assert '"id": "memoria_press"' in result
    assert "never evidence of the school's current assignment" in result
    assert arts.context(chosen, Subject.mathematics) == ""
    with pytest.raises(ValueError, match="Review this source version"):
        arts.context(config(8, chosen.current_unit.rsplit("; assignment=", 1)[0]), Subject.living_books)
    with pytest.raises(ValueError, match="Review this source version"):
        arts.context(config(8, chosen.current_unit.replace("week=1", "week=2")), Subject.living_books)
    data = arts.load_release()
    data["program_steps"]["memoria_press"][0]["en"] += " Check the new support version."
    raw = json.dumps(data, ensure_ascii=False).encode()
    replacement = tmp_path / "new-reviewed-release.json"
    replacement.write_bytes(raw)
    monkeypatch.setattr(arts, "RELEASE_FILE", replacement)
    monkeypatch.setattr(arts, "RELEASE_SHA256", sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="Review this source version"):
        arts.context(chosen, Subject.living_books)


@pytest.mark.parametrize("field,value", [("grade", "9"), ("week", 2), ("support", "extension"), ("program", "other")])
def test_selection_binding_changes_with_each_relevant_configuration(field, value):
    args = {"unit_id": "caesar-plutarch", "grade": "8", "week": 1, "locale": "en",
            "support": "guided", "program": "memoria_press"}
    original = arts.lesson(**args)["selection_token"]
    args[field] = value
    assert arts.lesson(**args)["selection_token"] != original


def test_approved_language_change_keeps_the_actual_assignment(monkeypatch):
    monkeypatch.setenv("BEDE_CLASSICAL_ARTS_ENABLED", "true")
    english = arts.lesson("caesar-plutarch", "8", locale="en", program="memoria_press")
    spanish = arts.lesson("caesar-plutarch", "8", locale="es", program="memoria_press")
    assert english["selection_token"] == spanish["selection_token"]
    result = arts.context(config(8, note(english, "memoria_press")), Subject.living_books, "es")
    assert "Preparación de la etapa gramatical" in result
    assert '"id": "memoria_press"' in result


def test_legacy_and_other_program_selection_remain_explicit(monkeypatch):
    monkeypatch.setenv("BEDE_CLASSICAL_ARTS_ENABLED", "true")
    legacy = config(8, "Bede classical arts: merchant-mercy; week=2; support=guided")
    assert arts.selection_program(legacy.current_unit) == "bede"
    assert "PORTIA" in arts.context(legacy, Subject.living_books)
    own = arts.lesson("merchant-mercy", "8", program="other")
    assert own["program_match"] is None
    assert "No publisher placement is assumed" in own["program"]["description"]
    assert '"id": "other"' in arts.context(config(8, note(own, "other")), Subject.living_books)
    with pytest.raises(ValueError, match="supported classical curriculum program"):
        arts.catalog("8", program="unverified_publisher")


@pytest.mark.parametrize("grade", ["6", "7"])
@pytest.mark.parametrize("locale", ["en", "es"])
def test_younger_caesar_route_stays_with_its_actual_reading_and_background(grade, locale):
    for program in ("bede", "valor", "other"):
        for week in (1, 2, 3):
            row = arts.lesson("caesar-plutarch", grade, week, locale, program=program)
            assert {source["id"] for source in row["companion_sources"]} <= {"north"}
            if week == 3:
                prompt = next(item["prompt"] for item in row["assessments"] if item["kind"] == "transfer")
                assert ("announcement" if locale == "en" else "anuncio") in prompt
                assert "Portia" not in prompt and "Porcia" not in prompt


def test_http_query_program_reaches_both_public_routes():
    import httpx
    from fastapi import FastAPI
    from routers.catalog import router

    async def run():
        app = FastAPI()
        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            result = await client.get("/catalog/classical-arts?grade=5&program=valor&locale=es")
            assert result.status_code == 200
            assert result.json()["program"]["id"] == "valor"
            assert [row["id"] for row in result.json()["units"]] == ["midsummer-scene"]
            valid = await client.get("/catalog/classical-arts/midsummer-scene?grade=9&program=memoria_press&week=3")
            assert valid.status_code == 200
            assert valid.json()["program_match"]["placement"] == "9+"
            assert valid.json()["selection_token"]
            assert (await client.get("/catalog/classical-arts/midsummer-scene?grade=8&program=memoria_press")).status_code == 422
            assert (await client.get("/catalog/classical-arts?grade=8&program=unknown")).status_code == 422
    asyncio.run(run())
