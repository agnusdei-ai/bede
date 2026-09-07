"""Parity and boundary guard for docs/BEDE_LOCUTO_ENTITLEMENT_CONTRACT.md.

The contract is a specification adopted by two repositories at one version,
and its whole value is that both copies say the same thing. That property has
no natural enforcement: a paragraph edited here reads as an improvement, is
green everywhere, and quietly makes `agnusdei-ai/locuto`'s copy describe a
different contract than Bede's. So the canonical block carries a digest, and
this file is what refuses a change to it.

What is enforced here is shape and boundary, never whether the contract is a
good contract. No test can rule on that. These tests know whether the document
still says the things Bede adopted it for: one version, three tiers, three
services, fail-closed on every unknown, no ambiguous seat count, no child data,
and no runtime capability.

Deliberately filesystem-only — no app imports, no network, no database. The
contract is a document, and a guard on a document that needed a running stack
would be skipped exactly when the document was being edited.

Note .github/workflows/test.yml's change filter names this document directly.
Without that, a pull request touching only the contract would compute
relevant=false, skip the api-tests job, and never run this file — the same
silent-no-op that filter comment already records for docs/DECISIONS.md.
"""
import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = _ROOT / "docs" / "BEDE_LOCUTO_ENTITLEMENT_CONTRACT.md"
_CAPABILITIES = (
    _ROOT / "homeschool-api" / "services" / "locuto_ipc" / "capabilities.py"
)

_BEGIN = "<!-- CONTRACT-V1-BEGIN -->"
_END = "<!-- CONTRACT-V1-END -->"

# The cross-repository parity token. This is the sha256 of the canonical block
# — the bytes from the start of the BEGIN marker line through the newline that
# ends the END marker line, inclusive of both markers — frozen at
# contract_version 1.0.0. `agnusdei-ai/locuto`'s copy of the same block hashes
# to the same value, and that equality is the only mechanism keeping the two
# documents one document. Changing this constant to make a failing test pass
# is not a fix: it is the divergence, recorded.
CANONICAL_SHA256 = "69abda9af44e68af0a65f8bff80a1857db1495214b5881445fc17d1edf64336e"

CONTRACT_VERSION = "1.0.0"

# Closed vocabularies, written as literals rather than parsed out of whatever
# the document currently says. A test that reads its expectations from its
# subject agrees with it by construction and checks nothing.
COMMERCIAL_TIERS = ["family", "coop", "network"]
SERVICES = ["bede_tutor", "locuto", "family_portal"]
SECTIONS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]


def _canonical_block() -> bytes:
    """The bytes both repositories must agree on, byte for byte.

    Extracted by locating the markers rather than by reading a line range, so
    a preamble or adoption note of any length is free to change without
    touching the block.
    """
    raw = _CONTRACT.read_bytes()
    start = raw.index(_BEGIN.encode())
    end = raw.index(_END.encode()) + len(_END.encode())
    end = raw.index(b"\n", end) + 1
    return raw[start:end]


def _canonical_text() -> str:
    return _canonical_block().decode()


def _table_after(text: str, anchor: str) -> list[list[str]]:
    """The data rows of the first markdown table following `anchor`.

    Returns each row as its list of cell strings, header and separator rows
    dropped. Used for the tier and service vocabularies, which are stated as
    tables and whose row COUNT is part of the claim — "exactly three" is not
    checked by asserting three known values are present.
    """
    assert anchor in text, f"Anchor text not found in the canonical block: {anchor!r}"
    rest = text[text.index(anchor) + len(anchor):]
    rows = []
    seen_table = False
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            seen_table = True
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # separator row
            rows.append(cells)
        elif seen_table and stripped == "":
            break
    return rows[1:]  # drop the header row


def test_the_contract_document_exists_and_carries_both_markers_exactly_once():
    """A canary for every test below. If the markers moved or doubled, the
    block extraction would silently read the wrong bytes and the digest check
    would fail for a reason nobody could interpret."""
    assert _CONTRACT.exists(), (
        f"{_CONTRACT} does not exist. docs/DECISIONS.md entry 25 points at it, "
        "and that register's own dangling-pointer guard will fail too."
    )
    text = _CONTRACT.read_text()
    assert text.count(_BEGIN) == 1, (
        f"Expected exactly one {_BEGIN} marker, found {text.count(_BEGIN)}. "
        "The block is located by these markers, so a second one makes the "
        "parity check read a different span than the one that was frozen."
    )
    assert text.count(_END) == 1, (
        f"Expected exactly one {_END} marker, found {text.count(_END)}."
    )
    assert text.index(_BEGIN) < text.index(_END), (
        "The END marker precedes the BEGIN marker, so the canonical block is "
        "inside out."
    )


def test_the_canonical_block_still_hashes_to_the_frozen_parity_token():
    """The one test this file exists for. Everything else here is a statement
    about the contract's content; this is the statement that Bede's copy and
    Locuto's copy are the same document."""
    import hashlib

    actual = hashlib.sha256(_canonical_block()).hexdigest()
    assert actual == CANONICAL_SHA256, (
        f"The canonical block hashes to {actual}, not the frozen "
        f"{CANONICAL_SHA256}. Something between the CONTRACT-V1 markers "
        "changed. That block is byte-identical to agnusdei-ai/locuto's copy by "
        "contract, so this is a divergence rather than an edit: revert it, or "
        "land the identical change in both repositories and mint a new "
        "contract_version with a new digest."
    )


def test_the_canonical_block_declares_the_adopted_contract_version():
    block = _canonical_text()
    assert f"`{CONTRACT_VERSION}`" in block, (
        f"contract_version {CONTRACT_VERSION} is not stated in the canonical "
        "block. The version is what a consumer fails closed on, so a contract "
        "that does not name its own version cannot be read safely."
    )


@pytest.mark.parametrize("letter", SECTIONS)
def test_every_required_section_is_present(letter):
    """Sections A through J are the contract's structure, and other documents
    cite them by letter (docs/DECISIONS.md entry 25 cites C and J; the
    adoption note cites F and J). A dropped section leaves those citations
    pointing at nothing."""
    block = _canonical_text()
    assert re.search(rf"^## {letter}\. ", block, re.MULTILINE), (
        f"Section {letter} is missing from the canonical block. Sections are "
        "cited by letter from the register and from the adoption note, so "
        "removing one breaks a reference rather than just shortening a "
        "document."
    )


def test_the_commercial_tiers_are_exactly_the_three_adopted_values():
    """`exactly three` is the claim, so the row count is checked as well as
    the values. Asserting only that the three are present would pass on a
    document that had quietly grown a fourth."""
    rows = _table_after(
        _canonical_text(), "The canonical `commercial_tier` values are exactly three:"
    )
    values = [r[0].strip("`") for r in rows]
    assert values == COMMERCIAL_TIERS, (
        f"Commercial tiers are {values}, expected exactly {COMMERCIAL_TIERS}. "
        "A tier added here is a commercial vocabulary change and must be "
        "agreed with agnusdei-ai/locuto under a new contract_version, not "
        "introduced in one repository."
    )


def test_the_entitled_services_are_exactly_the_three_adopted_values():
    rows = _table_after(
        _canonical_text(), "`entitled_services` is a set, drawn from exactly these values:"
    )
    values = [r[0].strip("`") for r in rows]
    assert values == SERVICES, (
        f"Services are {values}, expected exactly {SERVICES}. Section D's own "
        "rule is that an unknown service fails closed, which only means "
        "something while the known set is fixed."
    )


@pytest.mark.parametrize(
    "unknown",
    [
        "an unknown `contract_version`",
        "an unknown `commercial_tier`",
        "an unknown service",
        "an illegal transition",
    ],
)
def test_each_unknown_input_is_stated_to_fail_closed(unknown):
    """Fail-closed is the property the whole contract rests on: a consumer
    that guesses at an unrecognized tier provisions the wrong thing silently,
    which is the outcome sections D and H both name. Each of the four is
    pinned separately so a rewrite cannot drop one and keep the paragraph
    looking complete.

    Matched against whitespace-normalized text, because the contract is hard
    wrapped and every one of these phrases spans a line break in the source.
    A raw substring search would fail on all four for a formatting reason and
    teach whoever hit it to loosen the test.
    """
    # Case-insensitive: the list opens a sentence, so the first entry is
    # capitalized in the source and the rest are not.
    flat = re.sub(r"\s+", " ", _canonical_text()).lower()
    assert unknown.lower() in flat, (
        f"The canonical block no longer states that {unknown} fails closed. "
        "Section I lists them together; if that sentence was reworded, the "
        "reword has to keep every case, because a case that drops out of the "
        "list is a case a consumer is then free to guess at."
    )
    assert "`manual_review`" in flat, (
        "Fail-closed cases are stated but `manual_review` — the state they all "
        "fail into — is no longer named."
    )


def test_there_is_no_bare_seats_field_only_max_seats():
    """Section E bans the field outright: `seats` means children to one
    product, households to another and administrators to a third, and one
    number carrying all three is how a co-op gets provisioned as a family.

    The population scanned is FIELDS — the limits table's rows and the JSON
    example's keys — not the prose, because the prose legitimately contains
    the word in the sentence that bans it. A search for `seats` across the
    whole block matches that ban and also matches `max_seats`, so it would
    pass whatever a future edit did.
    """
    block = _canonical_text()
    flat = re.sub(r"\s+", " ", block)
    assert "There is no bare `seats` field, and there never may be" in flat, (
        "Section E's ban on a bare `seats` field is gone from the canonical "
        "block, which would leave this test enforcing a rule the contract no "
        "longer states."
    )

    limit_fields = [r[0].strip("`") for r in _table_after(block, "| Field | Type | Meaning | Absent means |")]
    assert limit_fields, "Parsed no rows out of section E's limits table."
    assert "seats" not in limit_fields, (
        f"Section E's limits table declares a bare `seats` field: {limit_fields}. "
        "Only `max_seats` is permitted, and it means administrative or adult "
        "accounts and nothing else."
    )
    assert "max_seats" in limit_fields, (
        "`max_seats` is gone from the limits table, which would leave the ban "
        "on `seats` guarding a field that no longer has a replacement."
    )

    example = json.loads(re.findall(r"```json\n(.*?)```", block, re.DOTALL)[0])
    assert "seats" not in example["limits"], (
        "The JSON example's limits object carries a bare `seats` key. That is "
        "the exact ambiguity section E exists to make unrepresentable, and an "
        "example is what a reader copies."
    )


def test_the_json_example_carries_no_child_data_field():
    """The privacy guard, and it has a trap worth stating.

    The prose of section I legitimately CONTAINS every word this rule
    forbids — it is the sentence that forbids them ("No child's name,
    identifier, age, grade, work, narration, assessment, mastery estimate,
    transcript, voice..."). So a scan over the whole document either fails on
    the rule's own text, or is written loosely enough to avoid that and then
    passes vacuously over a real leak. Neither is a guard.

    This scans the JSON example specifically, which is the one place in the
    contract where a field name is asserted rather than discussed, and is
    where a child-data field would actually appear if someone added one.

    `max_children` is the single permitted exception, named as such by
    section I: it is a count of permitted children in a commercial record,
    not a fact about any child.
    """
    block = _canonical_text()
    fences = re.findall(r"```json\n(.*?)```", block, re.DOTALL)
    assert len(fences) == 1, (
        f"Expected exactly one ```json example in the canonical block, found "
        f"{len(fences)}. This guard scans that block by position, so a second "
        "one would go unchecked."
    )
    example = json.loads(fences[0])

    def field_names(obj, prefix=""):
        for k, v in obj.items():
            yield k
            if isinstance(v, dict):
                yield from field_names(v)

    forbidden = (
        "child",
        "student",
        "pupil",
        "narration",
        "assessment",
        "mastery",
        "transcript",
        "voice",
        "prompt",
        "message",
        "email",
        "password",
        "secret",
        "token",
        "card",
        "grade",
        "birth",
    )
    leaks = [
        (name, word)
        for name in field_names(example)
        if name != "max_children"
        for word in forbidden
        if word in name.lower()
    ]
    assert not leaks, (
        f"The JSON example carries field name(s) matching forbidden child, "
        f"credential or payment vocabulary: {leaks}. Section I's rule is "
        "absolute and the example is the first place a reader copies from."
    )
    assert "max_children" in example["limits"], (
        "The example's limits object no longer carries max_children, so the "
        "one permitted exception above is guarding nothing."
    )
    assert "No child data, ever." in block, (
        "Section I's own heading rule is gone from the canonical block, which "
        "would leave this test enforcing a rule the contract no longer states."
    )


def test_the_locuto_ipc_capability_registry_is_still_literally_empty():
    """The contract explicitly is not a capability contract, and the way that
    stops being true is not a paragraph being edited — it is somebody adding
    an entry to CAPABILITIES and citing this document as the schema
    negotiation that authorized it. Read from source rather than by importing
    the module, so this stays filesystem-only and cannot be satisfied by a
    dict that is empty at import time and filled later."""
    source = _CAPABILITIES.read_text()
    assert "CAPABILITIES: dict[str, CapabilityHandler] = {}" in source, (
        f"{_CAPABILITIES} no longer declares CAPABILITIES as a literally empty "
        "dict. The entitlement contract's section A states the registry stays "
        "empty and may not be cited as the schema negotiation that would fill "
        "it; filling it requires that negotiation under bede-ipc-spec.md §4 "
        "and §5, and a decision entry of its own."
    )


def test_the_contract_document_registers_no_capability():
    """The other half of the same boundary: the document must not itself name
    a capability into the registry."""
    text = _CONTRACT.read_text()
    assert "CAPABILITIES[" not in text, (
        "The contract document appears to register a capability. It is a "
        "commercial entitlement specification and section A states plainly "
        "that nothing in it registers, implies, authorizes or prepares a "
        "runtime capability."
    )
    assert "The capability registry stays empty." in text, (
        "The canonical block's statement that the capability registry stays "
        "empty is gone. That sentence is what makes the boundary readable to "
        "someone who reaches this document looking for a capability schema."
    )
