"""Regression for the real curation declaration, not a waiver of the rule."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "factory"))
from fixture import example, write_fixture
from boundary import contract as c, Error
from validation import validate_bundle


def refreshed(bundle):
    bundle["units"][0]["lesson_refs"] = [c.ref(bundle["lessons"][0])]
    bundle["grade"]["unit_refs"] = [c.ref(bundle["units"][0])]
    for gate in bundle["gates"]:
        gate["target"] = c.ref(bundle["grade"])
    return bundle


def test_living_books_needs_explicit_true_declaration(tmp_path):
    write_fixture(tmp_path)
    bundle = example()
    bundle["lessons"][0]["subject"] = "living_books"
    for declaration in (None, False):
        if declaration is None:
            bundle["lessons"][0].pop("anti_twaddle", None)
        else:
            bundle["lessons"][0]["anti_twaddle"] = declaration
        with pytest.raises(Error, match="anti_twaddle"):
            validate_bundle(refreshed(bundle), tmp_path)
    bundle["lessons"][0]["anti_twaddle"] = True
    validate_bundle(refreshed(bundle), tmp_path)
