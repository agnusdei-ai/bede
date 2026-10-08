"""Guards the trademark attribution the two frontends actually paint.

`LICENSE` section 5 reserves the mark, and the register's own IP work treats
trademark registration as the asset most worth holding for a product sold to
households. None of that reaches a family. What reaches a family is one
sentence in `BedeMark.tsx`, and that sentence exists twice — once in the app,
once in the demo — with nothing asserting the two agree, and nothing tying
either to the entity the root LICENSE says owns the mark.

Two copies of one fact, so this is the check that they agree, per the standing
rule. The failure is silent in the worst way available: one shipped surface
would go on claiming the mark for an entity that does not hold it, or stop
claiming it at all, and neither renders as an error.

Shape only. Whether the wording is legally sufficient is a question for a
lawyer, not a test.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ROOT_LICENSE = _ROOT / "LICENSE"
_MARKS = (
    _ROOT / "homeschool-tutor" / "src" / "components" / "BedeMark.tsx",
    _ROOT / "demo" / "src" / "BedeMark.tsx",
)


def _root_copyright_holder() -> str:
    """Read the owner from the root LICENSE rather than restating it here."""
    first = _ROOT_LICENSE.read_text().splitlines()[0]
    match = re.match(r"Copyright \(c\) \d{4} (.+?)\. All Rights Reserved\.", first)
    assert match, f"root LICENSE no longer opens with a copyright line: {first!r}"
    return match.group(1)


def _attribution(path: Path) -> str:
    """The sentence a family actually reads, never a comment that mentions it.

    The first cut of this matched any line containing "trademark", which in
    both copies is the file's own docstring — so it asserted against prose
    describing the attribution rather than the attribution. That is the same
    vacuous pass the COPPA guards hit, and it is why this reads the rendered
    claim and requires exactly one.
    """
    claims = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "are trademarks of" in line
    ]
    if not claims:
        pytest.fail(
            f"{path.relative_to(_ROOT)} renders no trademark attribution. "
            "A brand surface that claims nothing is a surface that reserves "
            "nothing."
        )
    assert len(claims) == 1, (
        f"{path.relative_to(_ROOT)} renders {len(claims)} trademark claims; "
        f"one of them will go stale: {claims}"
    )
    return claims[0]


@pytest.mark.parametrize("path", _MARKS, ids=lambda p: p.parent.name)
def test_each_frontend_attributes_the_mark_to_the_repositorys_owner(path: Path):
    """An attribution naming anyone but the owner is worse than none: it is a
    public claim that the mark belongs somewhere it does not."""
    assert path.is_file(), f"{path} is missing — did the component move?"
    assert _root_copyright_holder() in _attribution(path)


def test_both_frontends_carry_the_same_attribution():
    """The app and the demo are the same product to a family looking at them."""
    app, demo = (_attribution(p) for p in _MARKS)
    assert app == demo, (
        "The two BedeMark copies state the trademark differently:\n"
        f"  app : {app}\n  demo: {demo}"
    )


def test_the_root_license_still_reserves_the_mark():
    """Canary: the attribution above is only meaningful while this holds."""
    text = _ROOT_LICENSE.read_text()
    assert "trademark" in text.lower()
    assert "Bede" in text


@pytest.mark.parametrize("path", _MARKS, ids=lambda p: p.parent.name)
def test_the_guarded_files_are_in_cis_change_filter(path: Path):
    """This suite reads two files outside homeschool-api/, and test.yml's
    filter computes relevant=false for a change that touches nothing it names
    — skipping api-tests entirely. Without these entries the guard would be
    real everywhere except on the one edit it exists to catch.

    Reads the grep -qE pattern line itself, not the workflow anywhere: an
    earlier version of this check elsewhere in the repo passed on a comment
    sitting beside the filter.
    """
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    pattern_lines = [ln for ln in workflow.splitlines() if "grep -qE" in ln]
    assert pattern_lines, "test.yml no longer has a grep -qE change filter"
    escaped = str(path.relative_to(_ROOT)).replace(".", r"\.")
    assert any(escaped in ln for ln in pattern_lines), (
        f"{escaped} is not named in test.yml's change filter, so editing it "
        "skips this suite."
    )
