"""Regressions for actual instruction/source relationships, not just completeness."""
import pytest

from services.classical_arts_service import catalog, lesson


def directions(row):
    return " ".join([row["objective"], *(step["instruction"] for step in row["steps"]),
                     *(check["prompt"] for check in row["assessments"])]).lower()


@pytest.mark.parametrize("locale", ["en", "es"])
@pytest.mark.parametrize("week", [1, 2, 3])
def test_midsummer_uses_the_performed_prologue_not_the_missing_opening(locale, week):
    row = lesson("midsummer-scene", "8", week, locale)
    text = row["source"]["text"]
    assert "PROLOGUE. If we offend" in text
    assert "HIPPOLYTA. Indeed" in text and text.count("THESEUS.") == 2
    exercise = directions(row)
    assert not any(wrong in exercise for wrong in (
        "opening exchange", "hippolyta complicate theseus", "mental distress",
        "lunatic", "diálogo inicial sobre la imaginación"))
    assert ("prologue" if locale == "en" else "prólogo") in exercise
    if week == 3:
        assert ("audience" if locale == "en" else "público") in row["objective"].lower()
        assert "recorder" in text


@pytest.mark.parametrize("locale", ["en", "es"])
@pytest.mark.parametrize("week", [1, 2, 3])
def test_michelangelo_uses_the_five_finished_frescoes_not_a_museum_drawing(locale, week):
    row = lesson("michelangelo-looking", "8", week, locale)
    assert len(row["visual_previews"]) == 5
    assert all(image["asset_sha256"] and image["source_url"].startswith("https://commons.wikimedia.org/")
               for image in row["visual_previews"])
    metadata = next(unit for unit in catalog("8", locale)["units"] if unit["id"] == "michelangelo-looking")
    assert "fresco" in metadata["content_note"].lower()
    exercise = directions(row)
    assert "fresco" in exercise
    assert not any(wrong in exercise for wrong in (
        "selected museum work", "linked museum drawing", "studies can explore form before",
        "directional study in the actual image", "original tridimensional"))
    if week == 3:
        assert ("two of the five" if locale == "en" else "dos de las cinco") in exercise


@pytest.mark.parametrize("locale", ["en", "es"])
@pytest.mark.parametrize("unit,week,required", [
    ("merchant-mercy", 3, {"caesar"}),
    ("caesar-plutarch", 3, {"north"}),
    ("macbeth-deliberation", 3, {"merchant", "caesar"}),
    ("henryv-community", 3, {"caesar"}),
    ("tempest-release", 2, {"merchant"}),
    ("tempest-release", 3, {"merchant"}),
])
def test_named_speech_comparisons_have_the_actual_companion_sources(locale, unit, week, required):
    row = lesson(unit, "9", week, locale)
    assert required <= {source["id"] for source in row["companion_sources"]}
    if unit == "macbeth-deliberation":
        exercise = directions(row)
        assert ("antony" if locale == "en" else "antonio") in exercise
        assert "or brutus" not in exercise and "o bruto" not in exercise
    for source in row["companion_sources"]:
        if source["id"] == "caesar":
            assert "ANTONY." in source["text"] and "BRUTUS." not in source["text"]


@pytest.mark.parametrize("locale", ["en", "es"])
def test_mercy_week_two_does_not_require_an_unprovided_verdict(locale):
    row = lesson("merchant-mercy", "8", 2, locale)
    exercise = directions(row)
    assert "rest of the cited scene" not in exercise and "claim/action/consequence table" not in exercise
    assert ("verdict is outside" if locale == "en" else "veredicto queda fuera") in exercise
    assert "The quality of mercy" in row["source"]["text"]


@pytest.mark.parametrize("locale", ["en", "es"])
def test_lamb_bridge_does_not_claim_the_prologue_is_the_same_episode(locale):
    row = lesson("lamb-midsummer", "8", 3, locale)
    assert ("different episodes" if locale == "en" else "episodios distintos") in directions(row)
    assert "midsummer" in {source["id"] for source in row["companion_sources"]}
