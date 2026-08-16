"""The Home Screen icon is one fact stored in three files, so they are checked.

A device reaches Bede's Home Screen by one of two routes, and they must not
disagree:

  * Safari's own "Add to Home Screen", which reads `manifest.json`'s icon and
    `index.html`'s `apple-touch-icon`.
  * The `.mobileconfig` from `ipad-profile.sh`, which embeds the icon bytes
    directly into a WebClip payload.

Nothing connected the two. `ipad-profile.sh` named
`homeschool-tutor/public/agnus-dei.png`, which has never existed in that
directory, and its `if [[ -f ]]` guard turned that into a **silent**
degradation: the profile installed fine and the Home Screen showed a generic
Safari screenshot instead of the Bede mark, with nothing anywhere saying why.
It was found during an iPhone install-readiness pass rather than by anything
failing, which is the whole problem — a broken path that produces a plausible
result reports nothing.

This is the same two-copies-of-one-fact discipline CLAUDE.md's standing
workflow describes, and the same reasoning as `src/palette.test.ts` reading
both Tailwind configs and the site CSS rather than trusting them to agree.

What is enforced is agreement and existence, never which image is the right
one to use — that is a design decision no test can hold.
"""
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_SCRIPT = _ROOT / "ipad-profile.sh"
_MANIFEST = _ROOT / "homeschool-tutor" / "public" / "manifest.json"
_INDEX = _ROOT / "homeschool-tutor" / "index.html"


def _icon_path_from_script() -> Path:
    """The ICON_FILE assignment line itself, not any mention of the name.

    Reading the assignment rather than scanning the file is deliberate, for the
    reason test_decision_register.py records: an earlier guard elsewhere in
    this repo asserted a filename appeared *anywhere* in a file and passed on a
    comment beside the real setting, so it would have kept passing after the
    setting was deleted. The comment above ICON_FILE names the old broken path
    on purpose, which would defeat a looser check outright.
    """
    for line in _PROFILE_SCRIPT.read_text().splitlines():
        m = re.match(r'^ICON_FILE="([^"]+)"', line.strip())
        if m:
            return _ROOT / m.group(1)
    raise AssertionError(
        f"No ICON_FILE assignment found in {_PROFILE_SCRIPT}. If the script was "
        "restructured, update this test rather than deleting it."
    )


def test_the_profile_scripts_icon_actually_exists():
    """The defect this file was written for. A missing icon must be a failure
    someone sees, not a Home Screen that quietly looks wrong."""
    icon = _icon_path_from_script()
    assert icon.is_file(), (
        f"ipad-profile.sh points ICON_FILE at {icon}, which does not exist. A "
        "device installing that profile gets a generic Safari screenshot on its "
        "Home Screen instead of the Bede mark."
    )


def test_the_profile_script_refuses_rather_than_shipping_no_icon():
    """The `-f` fallback is what made the original bug invisible. Restoring it
    would restore the silent degradation, so the refusal is pinned rather than
    left to review."""
    text = _PROFILE_SCRIPT.read_text()
    assert re.search(r'\[\[ -f "\$ICON_FILE" \]\] \|\|', text), (
        "ipad-profile.sh no longer refuses when ICON_FILE is missing. A "
        "conditional that skips the icon ships an unbranded profile and reports "
        "nothing, which is how this bug survived."
    )
    assert not re.search(r'^\s*if \[\[ -f "\$ICON_FILE" \]\]; then', text, re.M), (
        "ipad-profile.sh has an `if [[ -f $ICON_FILE ]]` fallback again. That is "
        "the exact silent-degradation shape this test exists to prevent."
    )


def test_all_three_home_screen_routes_use_the_same_icon():
    """Safari's Add to Home Screen and the .mobileconfig must not produce
    different icons for the same app on two devices in the same household."""
    script_icon = _icon_path_from_script().name

    manifest = json.loads(_MANIFEST.read_text())
    manifest_icons = {Path(i["src"]).name for i in manifest.get("icons", [])}
    assert script_icon in manifest_icons, (
        f"ipad-profile.sh embeds {script_icon}, but manifest.json declares "
        f"{sorted(manifest_icons)}. A device installing the profile and a device "
        "using Add to Home Screen would show different icons."
    )

    index = _INDEX.read_text()
    m = re.search(r'<link rel="apple-touch-icon" href="([^"]+)"', index)
    assert m, (
        f"No apple-touch-icon link found in {_INDEX}. iOS falls back to a page "
        "screenshot without it."
    )
    assert Path(m.group(1)).name == script_icon, (
        f"index.html's apple-touch-icon is {Path(m.group(1)).name} but "
        f"ipad-profile.sh embeds {script_icon}. These are the two routes onto "
        "the same Home Screen and must agree."
    )


def test_the_icon_is_a_real_png_at_the_declared_size():
    """A truncated or misnamed file would satisfy every path check above and
    still render as nothing. Reads the PNG's own IHDR rather than trusting the
    extension or the manifest's `sizes` string."""
    icon = _icon_path_from_script()
    data = icon.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{icon} is not a PNG."
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")

    manifest = json.loads(_MANIFEST.read_text())
    declared = {
        i["sizes"] for i in manifest.get("icons", [])
        if Path(i["src"]).name == icon.name
    }
    assert declared, f"{icon.name} is not declared in manifest.json's icons."
    assert f"{width}x{height}" in declared, (
        f"{icon.name} is actually {width}x{height} but manifest.json declares "
        f"{sorted(declared)}. The manifest describes an image that is not there."
    )


def test_the_profile_script_is_named_in_the_ci_change_filter():
    """Without this, a change to ipad-profile.sh alone computes relevant=false,
    skips api-tests, and never runs this guard — the same unreachable-guard
    failure test_decision_register.py documents. Checks the `grep -qE` pattern
    line itself. Verified by removing the pattern."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    filter_lines = [
        line for line in workflow.splitlines() if "grep -qE" in line and "^(" in line
    ]
    assert filter_lines, (
        "Could not find the change-filter `grep -qE` line in "
        ".github/workflows/test.yml. If that job was restructured, this test "
        "needs updating rather than deleting."
    )
    assert any("ipad-profile" in line for line in filter_lines), (
        "ipad-profile.sh is not in .github/workflows/test.yml's change-filter "
        "pattern, so a change to it computes relevant=false, skips api-tests, "
        "and never runs this guard."
    )
