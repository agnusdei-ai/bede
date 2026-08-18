"""The stated release posture is checked against the files that make it true.

`docs/RELEASE_QUALITY_GATES.md` opens by asserting something load-bearing:
there is no release artifact, `main` is the release, and every merge is
immediately what the next family builds. Every other gate in that document
depends on it.

That claim is not self-evident — it is read off `docker-compose.yml` (all four
Bede services `build:` rather than `image:`) and the `Makefile` (`make update`
is `git pull` plus a rebuild). Either could change without anyone touching the
document, and the document would then describe a delivery model the repository
had left. Nothing would error. That is exactly the failure this repository has
shipped before: `DiagnosticEvidenceLog`'s docstring said "off by default" for
four phases after the flip, and a deployer reading it would have concluded
their database stayed empty.

So the claim is pinned to its evidence. What is enforced is agreement between
the document and the mechanics, never whether continuous delivery is the right
model — that is entry 17, and no test can rule on it.

Note the direction: if someone publishes images or changes `make update`, these
tests fail and the *document* is what needs updating, along with entry 17's
status. A red test here is not a reason to revert the mechanics.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GATES = _ROOT / "docs" / "RELEASE_QUALITY_GATES.md"
_COMPOSE = _ROOT / "docker-compose.yml"
_MAKEFILE = _ROOT / "Makefile"
_REGISTER = _ROOT / "docs" / "DECISIONS.md"

# Bede's own services. Third-party images (postgres, caddy) are deliberately
# not here — they are pulled, and always were.
BEDE_SERVICES = {"api", "ui", "locuto-ipc", "trust"}


def _service_blocks() -> dict[str, str]:
    """{service name: its YAML block}, top-level services only.

    Parsed by indentation against the `services:` key rather than by loading
    YAML, so this has no dependency the API image does not already carry.
    """
    text = _COMPOSE.read_text()
    start = re.search(r"^services:\s*$", text, re.MULTILINE)
    assert start, f"No top-level `services:` key in {_COMPOSE}."
    body = text[start.end():]
    # A later top-level key (volumes:, networks:) ends the section.
    end = re.search(r"^[a-z]", body, re.MULTILINE)
    body = body[: end.start()] if end else body

    blocks: dict[str, str] = {}
    current = None
    for line in body.splitlines():
        m = re.match(r"^  ([a-z][a-z0-9-]*):\s*$", line)
        if m:
            current = m.group(1)
            blocks[current] = ""
        elif current is not None:
            blocks[current] += line + "\n"
    return blocks


def test_the_compose_file_parses_into_real_services():
    """A canary. Without it every test below passes vacuously the moment the
    compose layout changes — the vacuous-pass failure this repo has shipped
    twice (the indentation-sensitive palette parser, the `in body` header
    check)."""
    blocks = _service_blocks()
    missing = BEDE_SERVICES - set(blocks)
    assert not missing, (
        f"Could not parse service(s) {sorted(missing)} from {_COMPOSE}. Either "
        "a service was renamed or removed, or the parser broke; both need a "
        "human rather than a deleted test."
    )


def test_no_bede_service_is_published_as_an_image():
    """The claim the whole document rests on. If any Bede service gains an
    `image:` it is being pulled from a registry, which means a published
    artifact exists and `main` is no longer straightforwardly the release."""
    for name, block in _service_blocks().items():
        if name not in BEDE_SERVICES:
            continue
        assert re.search(r"^\s+build:", block, re.MULTILINE), (
            f"Service `{name}` no longer declares `build:`. "
            f"{_GATES}'s opening section states all four Bede services build "
            "from source; update that document and DECISIONS.md entry 17."
        )
        assert not re.search(r"^\s+image:", block, re.MULTILINE), (
            f"Service `{name}` now declares `image:`, so a published artifact "
            f"exists. {_GATES} says there is none, and entry 17 records the "
            "delivery model as an open question premised on that. Both need "
            "updating — this test failing is not a reason to revert the image."
        )


def test_make_update_still_rebuilds_from_source():
    """The other half of the claim: a family gets `main`, not a tagged
    version. If this grows a `git checkout` of a tag, the delivery model
    changed and the document is stale."""
    recipe = re.search(r"^update:.*?\n((?:\t.*\n)+)", _MAKEFILE.read_text(), re.MULTILINE)
    assert recipe, (
        f"No `update:` recipe found in {_MAKEFILE}. If the target was renamed, "
        "update this test and the release posture document together."
    )
    body = recipe.group(1)
    assert "git pull" in body, (
        f"`make update` no longer runs `git pull`. {_GATES} states a family "
        "runs whatever `main` was when they ran it."
    )
    assert "--build" in body, (
        f"`make update` no longer rebuilds. {_GATES} states Bede is rebuilt "
        "from source rather than pulled."
    )
    assert not re.search(r"git checkout|git switch", body), (
        f"`make update` now checks out a specific ref, so families no longer "
        f"track `main`. That is the tagged-release model — update {_GATES} and "
        "close DECISIONS.md entry 17 rather than leaving both describing the "
        "model this repository has left."
    )


def test_the_document_names_every_proof_workflow_that_exists():
    """The proofs table stands in for a release candidate. A workflow listed
    there but deleted would leave the document claiming coverage nobody has —
    the same shape as `frontend-tests.yml` being deleted in #296 and the only
    signal being its absence."""
    doc = _GATES.read_text()
    # Path-qualified references are unambiguous. Bare backticked names are
    # collected too (the table writes "lockfile-freshness in `test.yml`"), but
    # a bare name that exists as a file at the repository root is that file,
    # not a workflow — `docker-compose.yml` is mentioned by name throughout
    # this document and matched the first draft of this pattern, which is how
    # this guard failed against a correct document before it ever ran in CI.
    listed = set(re.findall(r"\.github/workflows/([a-z-]+\.yml)", doc))
    root_files = {p.name for p in _ROOT.iterdir() if p.is_file()}
    listed |= {
        name for name in re.findall(r"`([a-z-]+\.yml)`", doc)
        if name not in root_files
    }
    workflows = {p.name for p in (_ROOT / ".github" / "workflows").glob("*.yml")}
    phantom = listed - workflows
    assert not phantom, (
        f"{_GATES} names workflow(s) {sorted(phantom)} that do not exist in "
        ".github/workflows/. Either they were deleted — in which case the "
        "document is claiming a proof nobody runs — or renamed without the "
        "document following."
    )


def test_the_delivery_model_is_recorded_as_a_decision():
    """A default nobody chose is the thing entry 17 exists to convert into a
    choice. If the entry is dropped, the posture reverts to being accidental
    while the document still describes it as deliberate."""
    register = _REGISTER.read_text()
    assert "## 17." in register, (
        "DECISIONS.md entry 17 (the delivery model) is gone. The release "
        "posture document points at it for the choice it deliberately does "
        "not make itself."
    )
    assert "entry 17" in _GATES.read_text(), (
        f"{_GATES} no longer points at entry 17, so a reader has no route "
        "from the stated posture to the open question behind it."
    )


def test_the_release_posture_files_are_in_the_ci_change_filter():
    """Without this, a change to docker-compose.yml or the Makefile alone
    could compute relevant=false, skip api-tests, and never run this guard —
    the same unreachable-guard failure test_decision_register.py documents."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    filter_lines = [
        line for line in workflow.splitlines() if "grep -qE" in line and "^(" in line
    ]
    assert filter_lines, (
        "Could not find the change-filter `grep -qE` line in "
        ".github/workflows/test.yml. If that job was restructured, this test "
        "needs updating rather than deleting."
    )
    for needed in ("docker-compose", "Makefile", "docs/RELEASE_QUALITY_GATES"):
        assert any(needed in line for line in filter_lines), (
            f"{needed} is not in .github/workflows/test.yml's change-filter "
            "pattern, so a change to it computes relevant=false, skips "
            "api-tests, and never runs this guard."
        )
