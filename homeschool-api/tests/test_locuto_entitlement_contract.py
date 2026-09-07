"""Structural guard for docs/LOCUTO_ENTITLEMENT_CONTRACT.md.

The sibling of test_decision_register.py and test_accessibility_research.py:
a document this repository will be implemented against, checked for shape
rather than for correctness. No test can rule on whether a commercial contract
is the right one. These tests know whether it is still *legible* — versioned,
scoped, naming its counterpart, and carrying the fields both sides agreed to
implement against.

Two properties matter more than the rest, and both regress silently.

**The commercial/runtime separation.** docs/DECISIONS.md entry 14 governs the
runtime Locuto IPC wire schema and requires a joint negotiation; entry 25
governs this commercial contract. They share a product pairing and nothing
else. The failure this file exists to catch is someone reading "Locuto
contract" and registering a capability in services/locuto_ipc/capabilities.py,
which must stay empty until entry 14 closes on its own terms.

**The out-of-scope list.** The contract's value is as much in what it refuses
to specify — Stripe, automated issuance, online validation, monthly billing,
offline revocation. Those refusals are load-bearing: three of them describe
mechanisms core/licensing.py genuinely does not have, and a reader who loses
the refusal designs against a capability that does not exist.

Every guard here was verified by breaking the thing it guards.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = _ROOT / "docs" / "LOCUTO_ENTITLEMENT_CONTRACT.md"
_REGISTER = _ROOT / "docs" / "DECISIONS.md"
_CAPABILITIES = _ROOT / "homeschool-api" / "services" / "locuto_ipc" / "capabilities.py"

# Closed vocabularies, as literals rather than parsed out of the document.
# Parsing them from the file under test would make every assertion below agree
# with whatever the file happens to say, which is the vacuous pass this
# repository has shipped before.
COMMERCIAL_TIERS = {"family", "coop", "network"}
SERVICE_KEYS = {"bede_tutor", "locuto", "family_portal"}
LIFECYCLE_STATES = {
    "pending",
    "provisioned",
    "active",
    "renewal_due",
    "expired",
    "suspended",
    "failed",
    "manual_review",
}
IDENTIFIERS = {
    "organization_id",
    "purchaser_account_id",
    "admin_account_id",
    "entitlement_id",
    "bede_license_id",
    "idempotency_key",
    "correlation_id",
}
EVENT_FIELDS = {
    "contract_version",
    "event_type",
    "occurred_at",
    "effective_date",
    "expiry_date",
    "tier",
    "services",
    "limits",
    "source_reference",
}


def _text() -> str:
    return _CONTRACT.read_text()


def _section(heading_fragment: str) -> str:
    """The body of the section whose heading contains `heading_fragment`.

    Section-scoped rather than whole-document, because a bare substring search
    over a long document is the vacuous pass this repository keeps shipping:
    four guards in the first draft of this file survived the exact regression
    they were written for, because the word they looked for also appeared in a
    cross-reference somewhere else. Verified by breaking each one.
    """
    text = _text()
    headings = list(re.finditer(r"^#{2,3} .*$", text, re.M))
    for i, m in enumerate(headings):
        if heading_fragment.lower() in m.group(0).lower():
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            return text[m.end() : end]
    raise AssertionError(
        f"No section heading containing {heading_fragment!r} in {_CONTRACT}. "
        "Either the section was removed or renamed; both need a human."
    )


def _tier_table_values() -> set[str]:
    """The `tier` values declared in section 3's own table, not anywhere the
    string happens to appear. A tier named only in a cross-reference is not a
    tier either side can send."""
    rows = re.findall(r"^\| `([a-z_]+)` \|", _section("Canonical commercial tiers"), re.M)
    return set(rows)


def _example_payload() -> str:
    match = re.search(r"```json\n(.*?)```", _text(), re.S)
    assert match, "The contract carries no ```json example payload."
    return match.group(1)


def test_the_contract_document_exists_and_is_not_a_stub():
    """A canary. Without it every test below passes on an empty file."""
    assert _CONTRACT.exists(), f"{_CONTRACT} is missing."
    assert len(_text()) > 4000, (
        f"{_CONTRACT} is {len(_text())} characters. Either it was gutted or "
        "this guard is checking a placeholder, which would make every "
        "assertion below meaningless."
    )


def test_it_declares_a_contract_version():
    """Both repositories adopt a version, not a document. Without a stated
    version there is nothing for the Locuto side to say it matches."""
    assert re.search(r"\*\*Contract version:\*\*\s*`[^`]+`", _text()), (
        "No '**Contract version:** `x.y.z`' line. Both sides adopt a version; "
        "a document with no version cannot be jointly adopted."
    )


def test_it_names_locuto_as_the_counterpart_repository():
    assert "agnusdei-ai/locuto" in _text(), (
        "The contract does not name agnusdei-ai/locuto. A contract with an "
        "unnamed counterpart is a specification."
    )


def test_it_says_plainly_that_it_is_not_yet_active():
    """The most dangerous way this document fails is by reading as settled.
    A one-sided draft that looks agreed is worse than no document, because
    someone builds against it and makes a commercial commitment on it."""
    section = _section("Joint adoption required")
    assert re.search(r"[Nn]ot active", section), (
        "The 'Joint adoption required' section no longer states that the "
        "contract is not active. It is a Bede-side draft until the "
        "Locuto-side PR adopts the same version, and a draft that reads as "
        "agreed is worse than no document — someone builds on it."
    )
    assert "contract tests" in section, (
        "The joint-adoption section no longer requires contract tests in both "
        "repositories. A contract asserted on one side is a hope."
    )
    assert "agnusdei-ai/locuto" in section, (
        "The joint-adoption section no longer names the counterpart repository."
    )
    assert re.search(r"\*\*Not active\*\*|\*\*This contract is not active", _text()), (
        "The contract's own header/section no longer carries an emphasised "
        "'not active' statement, so a skim-reader meets it as settled."
    )


def test_the_tier_table_declares_exactly_the_commercial_vocabulary():
    """Read out of section 3's table specifically. An earlier version of this
    guard searched the whole document and passed after the `network` row was
    renamed, because the word survived in a cross-reference. The vocabulary is
    closed and unknown values fail closed, so what is in the table is the
    entire set either side may send."""
    declared = _tier_table_values()
    assert declared == COMMERCIAL_TIERS, (
        f"Section 3's tier table declares {sorted(declared)}, expected "
        f"{sorted(COMMERCIAL_TIERS)}. Changing the commercial tier vocabulary "
        "is a change to what both repositories implement, and to "
        "docs/DECISIONS.md entries 7 and 10 — not a table edit."
    )


def test_legacy_signed_tiers_are_still_promised_acceptance():
    """A tier string is signed into the license payload, so every already-issued
    license carries the old vocabulary permanently. If the contract stops
    promising these keep verifying, the migration it hands to entry 7 becomes
    one that bricks existing deployments."""
    text = _text()
    for legacy in ("trial", "core"):
        assert f"`{legacy}`" in text, (
            f"Legacy signed tier {legacy!r} is no longer named. core/licensing.py "
            "verifies it on boot for licenses already in the field; dropping the "
            "commitment is how an existing family stops being able to start Bede."
        )


def test_the_coop_collision_is_named_rather_than_left_to_be_discovered():
    """`coop` is both a legacy signed tier and the Co-op Membership. That is a
    real ambiguity the migration inherits, and the contract's job is to hand it
    over knowingly."""
    assert "collision" in _text().lower(), (
        "The contract no longer names the `coop` collision — the same string "
        "meaning a legacy signed tier and the Co-op Membership. Losing it "
        "turns a known problem into one the migration PR discovers."
    )


@pytest.mark.parametrize("service", sorted(SERVICE_KEYS))
def test_every_service_entitlement_field_is_defined(service):
    assert f"`{service}`" in _text(), (
        f"Service key {service!r} is not defined. A service that is not named "
        "is not entitled, so an undefined key cannot be sold."
    )


def test_it_refuses_to_claim_a_component_exists_because_it_has_a_name():
    """Two of the three services are not separately built in this repository:
    Locuto is another product, and the Family Portal is the parent-facing pages
    of the tutor app. An entitlement schema that quietly implies three shipped
    products is a marketing claim wearing a data model."""
    text = _text()
    assert "not a distinct deliverable" in text or "Named, not separately built" in text, (
        "The contract no longer states what family_portal actually is today. "
        "A component is not claimed to exist because it has a marketing name."
    )
    assert "Not integrated with Bede" in text, (
        "The contract no longer states that Locuto is not integrated with "
        "Bede. services/locuto_ipc/ is a protocol skeleton with an empty "
        "capability registry, and the contract has to say so."
    )


def test_the_six_child_maximum_is_represented_rather_than_implied():
    """`max_children: 6`, never `seats: 6` and never inferred from the tier.
    A limit inferred from a tier string is a limit that silently changes
    meaning the moment the tier vocabulary moves — which entry 7 says it will."""
    text = _text()
    limits = _section("Limits")
    assert "`max_children`" in limits, "Section 5 defines no `max_children` field."
    assert '"max_children": 6' in _example_payload(), (
        "The example payload no longer carries an explicit \"max_children\": 6. "
        "Six children must travel as data. An earlier version of this guard "
        "accepted the value appearing anywhere in the document, and so passed "
        "after the payload was changed to null while the prose still said 6 — "
        "which is precisely the two-copies-disagreeing failure it exists to "
        "catch. Verified by breaking it."
    )
    assert re.search(r"never `seats: 6`.*never inferred", limits, re.S | re.I), (
        "Section 5 no longer states that six children is `max_children: 6` and "
        "never `seats: 6` and never inferred from the tier. A limit inferred "
        "from a tier string changes meaning the moment the tier vocabulary "
        "moves, which docs/DECISIONS.md entry 7 says it will."
    )
    assert "`max_households`" in limits, (
        "No `max_households` field. A Family Membership caps children and a "
        "Co-op Membership is bounded by households; one integer cannot carry "
        "both without a reader guessing which it means."
    )


@pytest.mark.parametrize("state", sorted(LIFECYCLE_STATES))
def test_every_lifecycle_state_is_defined(state):
    assert f"`{state}`" in _text(), (
        f"Lifecycle state {state!r} is not defined in the contract."
    )


def test_lifecycle_transitions_name_an_owner():
    assert re.search(r"Transition owned by|transition ownership", _text(), re.I), (
        "The lifecycle table no longer names who owns each transition. A state "
        "machine with unowned transitions is two implementations disagreeing "
        "about who moves it."
    )


def test_it_states_that_suspension_has_no_enforcement_in_bede_today():
    """core/licensing.py verifies offline with no revocation path, so a
    `suspended` entitlement does not stop a running deployment. Recording the
    state without recording that gap is how a support team promises something
    the software cannot do."""
    text = _text()
    assert "no revocation" in text.lower(), (
        "The contract no longer states that core/licensing.py has no "
        "revocation mechanism. That is the fact `suspended` depends on."
    )
    assert "no enforcement mechanism in Bede" in text, (
        "The contract no longer states that `suspended` is unenforceable in "
        "Bede today. A lifecycle state that reads as enforced and is not is "
        "the silent-degradation failure this repository refuses."
    )


@pytest.mark.parametrize("identifier", sorted(IDENTIFIERS))
def test_every_stable_identifier_is_defined(identifier):
    assert f"`{identifier}`" in _text(), (
        f"Identifier {identifier!r} is not defined. Both sides implement "
        "against these names, so an undefined one is a field one side invents."
    )


@pytest.mark.parametrize("field", sorted(EVENT_FIELDS))
def test_the_provisioning_event_schema_carries_every_required_field(field):
    assert f"`{field}`" in _text(), (
        f"Provisioning event field {field!r} is missing from the schema."
    )


def test_the_example_payload_is_labelled_illustrative():
    """An unlabelled example in a contract document becomes a fixture, then a
    test vector, then a real-looking record of a customer who does not exist."""
    text = _text()
    fence = text.index("```json")
    preamble = text[max(0, fence - 400) : fence]
    assert re.search(r"[Ii]llustration only|[Ii]llustrative only|not a fixture", preamble), (
        "The disclaimer immediately above the ```json block is gone. A section "
        "heading calling the payload 'illustrative' is not enough — an earlier "
        "version of this guard searched the whole document, and passed after "
        "the disclaimer sentence was deleted because the heading still said the "
        "word. Verified by breaking it."
    )
    assert "EXAMPLE" in _example_payload(), (
        "The example payload's identifiers no longer read as obvious "
        "placeholders. An example that looks like real data becomes a fixture, "
        "then a test vector, then a record of a customer who does not exist."
    )


@pytest.mark.parametrize(
    "requirement",
    ["Idempoten", "etries", "econcil", "anual fallback", "ail closed"],
)
def test_the_delivery_requirements_survive(requirement):
    assert requirement in _text(), (
        f"The contract no longer covers {requirement!r}. Idempotency, retries, "
        "reconciliation, the manual fallback and failing closed are what make "
        "at-least-once delivery safe; dropping one leaves a household "
        "provisioned twice, or once and invisibly."
    )


def test_the_manual_issuance_path_stays_supported():
    """It is the only path that works today: an operator runs issue_license.py
    and a household applies the key through POST /admin/license. An automated
    contract that quietly deprecates it removes the fallback before the
    replacement exists."""
    text = _text()
    assert "issue_license.py" in text, (
        "The contract no longer names homeschool-api/scripts/issue_license.py. "
        "Manual issuance is the only path that works today."
    )
    assert "LICENSE_APPLIED" in text, (
        "The contract no longer names AuditEvent.LICENSE_APPLIED, which is "
        "what makes a hand-applied license reconcilable rather than invisible."
    )


def test_no_child_data_may_appear_in_an_entitlement():
    """The standing rule, applied to a schema. An entitlement carries a
    commercial fact; `max_children: 6` is a limit and a list of six children
    is a contract violation."""
    text = _text()
    assert "No child data" in text, (
        "The contract no longer forbids child data in entitlement events. "
        "An entitlement schema is as good a place to leak a child's record as "
        "a database column."
    )


def test_no_faith_engagement_field_is_permitted():
    """CLAUDE.md's standing refusal, extended to this schema by name. A
    per-tier 'faith engagement' field is the forbidden metric arriving through
    a commercial door."""
    assert "faith-engagement" in _text() or "faith_engagement" in _text(), (
        "The contract no longer explicitly refuses a faith-engagement field. "
        "That refusal is stated here precisely because a schema is somewhere "
        "nobody thinks to look for it."
    )


def test_secrets_are_forbidden_and_the_license_key_is_never_carried():
    """`bede_license_id` is a reference, never the signed key. The key is the
    one credential in this whole flow, and an entitlement event is exactly the
    sort of thing that gets logged, replayed and forwarded."""
    text = _text()
    assert re.search(r"[Nn]o secret ever appears", text), (
        "The contract no longer forbids secrets appearing in it or any other "
        "document under docs/."
    )
    assert re.search(r"[Nn]ever the key itself|never carried in an entitlement", text), (
        "The contract no longer states that the license key itself is never "
        "carried in an entitlement event. bede_license_id is a reference; the "
        "key reaching a household is a separate, credential-bearing path."
    )


def test_the_out_of_scope_refusals_survive():
    """The refusals are load-bearing. Three of them (online validation, monthly
    billing, offline revocation) describe mechanisms core/licensing.py does not
    have, so losing the refusal means someone designs against a capability that
    does not exist."""
    text = _text()
    for refusal in ("Stripe", "monthly billing", "revocation", "online license validation"):
        assert refusal.lower() in text.lower(), (
            f"{refusal!r} is no longer named in the contract's non-scope. The "
            "out-of-scope list is what keeps this a contract definition rather "
            "than an implementation plan."
        )


def test_it_separates_itself_from_the_runtime_ipc_capability_negotiation():
    """The single most likely misreading: 'Locuto contract, therefore register
    a capability'. docs/DECISIONS.md entry 14 requires a joint schema
    negotiation and this document does not touch it."""
    text = _text()
    assert "entry 14" in text.lower(), (
        "The contract no longer points at docs/DECISIONS.md entry 14. Without "
        "that pointer a reader cannot tell this from the runtime IPC schema."
    )
    assert "CAPABILITIES = {}" in text, (
        "The contract no longer states that services/locuto_ipc/capabilities.py "
        "stays empty. That sentence is what stops this document being read as "
        "permission to register a capability."
    )


def test_no_locuto_ipc_capability_was_registered_by_this_work():
    """The behavioural half of the guard above. The contract can say whatever
    it likes; this reads the module. Entry 14 is open and CAPABILITIES stays
    empty until it closes on its own terms."""
    source = _CAPABILITIES.read_text()
    assert re.search(r"^CAPABILITIES\s*:\s*dict[^=\n]*=\s*\{\s*\}\s*$", source, re.M), (
        f"{_CAPABILITIES} no longer declares an empty CAPABILITIES registry. "
        "The wire schema for a runtime capability requires a joint negotiation "
        "with agnusdei-ai/locuto (docs/DECISIONS.md entry 14) and must not be "
        "invented by one side — least of all as a side effect of a commercial "
        "contract document."
    )


def test_the_register_carries_an_entry_pointing_at_this_contract():
    """The register is where a decision's state lives; the document is where
    its argument lives. A contract with no register entry has no status."""
    register = _REGISTER.read_text()
    assert "LOCUTO_ENTITLEMENT_CONTRACT.md" in register, (
        "docs/DECISIONS.md does not reference the contract document, so the "
        "contract has no recorded status and nothing says whether it is agreed."
    )


def test_the_register_entry_records_what_it_does_not_resolve():
    """Recorded in the register rather than only in the contract, because the
    register is what someone reads to find out whether entry 14 is still open."""
    register = _REGISTER.read_text()
    assert "commercial entitlement contract definition only" in register, (
        "The register no longer records that this resolves the commercial "
        "entitlement contract definition ONLY, and not the runtime Locuto IPC "
        "capability negotiation (entry 14)."
    )


def test_the_contract_is_named_in_the_ci_change_filter():
    """Without this, a pull request touching only the contract computes
    relevant=false, skips api-tests, and never runs this file — real everywhere
    except on the changes it exists to guard. Reads the `grep -qE` pattern line
    itself, because an earlier version of the sibling test in
    test_decision_register.py passed on a comment beside the filter."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    filter_lines = [
        line for line in workflow.splitlines() if "grep -qE" in line and "^(" in line
    ]
    assert filter_lines, "Could not find the change-filter line in test.yml."
    assert any("docs/LOCUTO_ENTITLEMENT_CONTRACT" in line for line in filter_lines), (
        "docs/LOCUTO_ENTITLEMENT_CONTRACT.md is not in test.yml's change-filter "
        "pattern, so a contract-only change never runs this guard."
    )


def test_every_document_the_contract_points_at_exists():
    """Same dangling-pointer guard test_decision_register.py applies to the
    register. A contract that cites a renamed document still reads as sourced
    while being unreachable."""
    referenced = sorted(
        {m.group(1) for m in re.finditer(r"\]\((([A-Za-z0-9_-]+\.md))(?:#[^)]*)?\)", _text())}
    )
    assert referenced, (
        "Parsed no document links out of the contract at all. Either the link "
        "convention changed or this pattern needs updating — both need a human "
        "rather than a vacuous pass."
    )
    missing = [name for name in referenced if not (_CONTRACT.parent / name).exists()]
    assert not missing, (
        f"The contract links to document(s) that do not exist: {missing}."
    )
