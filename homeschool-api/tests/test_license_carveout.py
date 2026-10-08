"""Guards the one place this repository carries two licenses at once.

`agent-governance/` is a generic extraction licensed to everyone under
Apache-2.0 (docs/DECISIONS.md entry 18); everything around it stays
proprietary. That single fact is now written in seven places — the root
LICENSE's carve-out, the package's own LICENSE and NOTICE, its README, the
decision register, the SPDX headers on its sources, and the generated
handout in its dist/. A relicensing that updated some of them and not the
root LICENSE would leave this repository stating two different things about
the same directory, which is worse than a stale comment: it is a
contradiction in the document that grants rights.

Shape only, never whether the choice is correct — the same discipline
test_decision_register.py applies to the register. Note .github/workflows/
test.yml's change filter names both LICENSE and agent-governance/, without
which a licensing-only edit would compute relevant=false and never run this.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ROOT_LICENSE = _ROOT / "LICENSE"
_PKG = _ROOT / "agent-governance"


def _root_copyright_holder() -> str:
    """The repository's own statement of who owns it, read from the root
    LICENSE rather than restated here.

    This is what makes the guard below span the repository boundary. The
    holder used to be hardcoded, and it named a different entity from the
    one on the root LICENSE and on every other file in the repository — so
    the Apache grant was made in one company's name inside a repository
    owned by another, with nothing anywhere saying how the two were
    related. Deriving it means the two cannot disagree again: rename the
    company and this fails until the sweep is finished.
    """
    first = _ROOT_LICENSE.read_text().splitlines()[0]
    match = re.match(r"Copyright \(c\) \d{4} (.+?)\. All Rights Reserved\.", first)
    assert match, (
        "The root LICENSE no longer opens with a parseable copyright line, so "
        f"the package's holder cannot be checked against it: {first!r}"
    )
    return match.group(1)


def test_the_package_exists_and_is_apache_licensed():
    """Canary: every test below would pass vacuously if the directory moved."""
    assert _PKG.is_dir(), f"{_PKG} is missing — did the package move?"
    text = (_PKG / "LICENSE").read_text()
    assert text.lstrip().startswith("Apache License")
    assert "Version 2.0, January 2004" in text
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in text


def test_the_root_license_carves_the_package_out_by_name():
    """Without this clause, the root 'All Rights Reserved' and the package's
    Apache grant contradict each other with nothing to resolve them."""
    text = _ROOT_LICENSE.read_text()
    assert "agent-governance/" in text, (
        "The root LICENSE no longer names agent-governance/. If the package "
        "was relicensed or removed, update the root LICENSE in the same change."
    )
    assert "Apache License, Version 2.0" in text


def test_one_copyright_holder_across_the_whole_package():
    """The holder now appears in the NOTICE, in every shipped source header,
    and in the root LICENSE's carve-out. A rename that reached some of those
    and not the others would leave the grant naming two different licensors,
    which is worse than a stale comment: it is ambiguity in the document that
    conveys rights."""
    holder = _root_copyright_holder()
    notice = (_PKG / "NOTICE").read_text()
    assert f"Copyright 2026 {holder}" in notice

    sources = sorted((_PKG / "reference").glob("*.py")) + \
        sorted((_PKG / "reference").glob("*.ts")) + \
        sorted((_PKG / "tools").glob("*.ts")) + \
        sorted((_PKG / "tools").glob("*.sh"))
    assert len(sources) >= 6, "no shipped sources found; this guard would be empty"
    for source in sources:
        head = "\n".join(source.read_text(encoding="utf-8").splitlines()[:4])
        assert f"Copyright 2026 {holder}" in head, source.name

    # Deliberately the carve-out SECTION, not the file. `holder` is derived
    # from the root LICENSE's first line, so "is it anywhere in that file"
    # is tautological and would pass with section 6 naming nobody at all.
    section = _ROOT_LICENSE.read_text().split("6. SEPARATELY LICENSED COMPONENT")
    assert len(section) == 2, "the root LICENSE no longer has a section 6 to read"
    # Collapse whitespace first: this is wrapped prose, so a 27-character
    # company name straddles a line break as often as not, and a literal
    # substring check would fail on formatting rather than on substance.
    carveout = " ".join(section[1].split("\n\n")[0].split())
    assert holder in carveout, (
        "The root LICENSE's section 6 carve-out does not name "
        f"{holder!r} as the publisher of the separately licensed directory. "
        "A permissive grant inside a proprietary repository has to say who "
        "is making it.\n" + carveout
    )


def test_no_second_entity_appears_as_a_copyright_holder_in_the_package():
    """The guard above proves the right entity is named everywhere it looked.
    This one proves no *other* entity is named anywhere else in the package.

    Those are different failures. A hardcoded holder caught a rename that
    reached some files and not others; it could not catch a new file, or a
    new paragraph, introducing a second licensor beside the first — which is
    how the Apache grant came to be made in a name the repository never
    identified. Every copyright line in the package must name the one entity
    the root LICENSE says owns this repository.
    """
    holder = _root_copyright_holder()
    pattern = re.compile(r"Copyright(?:\s+\(c\))?\s+\d{4}\s+(.+)")
    offenders: list[str] = []
    for path in sorted(_PKG.rglob("*")):
        if not path.is_file() or path.name == "LICENSE":
            continue  # Apache-2.0's own text carries no holder of ours.
        if any(part in {"dist", "__pycache__", ".pytest_cache", "node_modules"}
               for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line in text.splitlines():
            found = pattern.search(line)
            if found and not found.group(1).startswith(holder):
                offenders.append(f"{path.relative_to(_ROOT)}: {line.strip()}")
    assert not offenders, (
        f"These lines name a copyright holder other than {holder!r}, the owner "
        "named on the root LICENSE. A permissive grant must identify its "
        "licensor, and this repository has exactly one:\n  "
        + "\n  ".join(offenders)
    )


def test_the_carveout_preserves_the_trademark_reservation():
    """A permissive grant on the prompts must never read as a grant on the
    name. The package's own NOTICE says the same thing from its side."""
    assert "grants any" in _ROOT_LICENSE.read_text() or "no rights" in _ROOT_LICENSE.read_text()
    assert "trademark" in (_PKG / "NOTICE").read_text().lower()


def test_the_public_readme_states_the_carveout():
    """The root README is the public statement, and it said outright that this
    repository is "not open source" with redistribution "not permitted" for a
    commit after the carve-out landed. A licence exception that only the LICENSE
    file knows about is one nobody reusing the package will ever find.
    """
    readme = (_ROOT / "README.md").read_text()
    assert "agent-governance/" in readme, (
        "The root README does not mention agent-governance/. It is the public "
        "statement of what this repository is; a licence carve-out missing from "
        "it reads as though the package is proprietary too."
    )
    assert "Apache" in readme


def test_the_register_records_the_decision():
    register = (_ROOT / "docs" / "DECISIONS.md").read_text()
    assert "agent-governance/" in register and "Apache" in register


@pytest.mark.parametrize(
    "source", sorted((_PKG / "reference").glob("*.py")) + sorted((_PKG / "reference").glob("*.ts"))
)
def test_every_shipped_source_declares_the_same_license(source: Path):
    head = "\n".join(source.read_text(encoding="utf-8").splitlines()[:3])
    assert "SPDX-License-Identifier: Apache-2.0" in head, source.name


def test_no_license_header_sits_in_a_prompt_payload():
    """prompts/*.md are read verbatim into a system prompt, so a header added
    there ships into the model's context. The package guards this too; it is
    repeated here because this is the file someone edits when relicensing."""
    for prompt in sorted((_PKG / "prompts").glob("*.md")):
        text = prompt.read_text(encoding="utf-8")
        assert "SPDX" not in text and "<!--" not in text, prompt.name


def test_the_change_filter_names_both_licensing_paths():
    """A guard unreachable on the change it guards is not a guard — the same
    failure test_decision_register.py documents for the register itself."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    filter_line = next(ln for ln in workflow.splitlines() if "grep -qE" in ln)
    for path in ("agent-governance/", "LICENSE", "README"):
        assert path in filter_line, (
            f"{path} is missing from test.yml's change filter, so a change to "
            f"only that path would skip this suite entirely."
        )
