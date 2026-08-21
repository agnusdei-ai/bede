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
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ROOT_LICENSE = _ROOT / "LICENSE"
_PKG = _ROOT / "agent-governance"


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
