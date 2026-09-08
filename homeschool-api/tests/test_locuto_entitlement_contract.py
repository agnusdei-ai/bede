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
import json
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
# `family_portal` is deliberately NOT here — docs/DECISIONS.md entry 26 rules it
# a SURFACE of bede_tutor for v1, not a third service. A guard below fails if it
# reappears as a service key, because "add the Family Portal as a service" is an
# obvious-sounding change and the reason it is refused lives in a register entry
# nobody re-reads.
SERVICE_KEYS = {"bede_tutor", "locuto"}
SURFACE_IDS = {"family_portal"}
# The surface-level extension point. `bundled` is the only value legal at
# 1.0.0-draft; `independent` exists in the vocabulary, reserved, so that a later
# version promotes a surface by adding a legal VALUE rather than a field shape.
SURFACE_ENTITLEMENTS = {"bundled", "independent"}
LEGAL_SURFACE_ENTITLEMENTS_V1 = {"bundled"}
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


def _flat(text: str) -> str:
    """Whitespace collapsed to single spaces.

    Markdown wraps prose at 79 columns, so a phrase this file asserts can sit
    across a line break and a raw substring check reports it missing after an
    innocent rewrap. Two break-verification attempts on this file failed for
    exactly that reason and briefly looked like vacuous guards. Normalising
    makes the assertion about the words rather than about the wrapping.
    """
    return " ".join(text.split())


def _table_first_column(section_fragment: str, header_label: str) -> set[str]:
    """The backticked values in the first column of the table whose header row
    starts with `header_label`.

    Scoped to one named table rather than to a section, because a section here
    routinely carries three: section 4.2 declares surfaces, then the fields a
    surface carries, then the `entitlement` vocabulary, and a bare row regex
    reads all three as if they were one list. That mistake was made writing
    this file and caught by the guard below failing with `included` and
    `notes` in the surface set.
    """
    section = _section(section_fragment)
    lines = section.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"| {header_label} |"):
            values = set()
            for row in lines[i + 2 :]:
                if not row.startswith("|"):
                    break
                m = re.match(r"^\| `([a-z_]+)` \|", row)
                if m:
                    values.add(m.group(1))
            return values
    raise AssertionError(
        f"No table with a {header_label!r} first column in the section matching "
        f"{section_fragment!r}. Either the table was removed or its header "
        "changed; both need a human rather than a vacuous pass."
    )


def _tier_table_values() -> set[str]:
    """The `tier` values declared in section 3's own table, not anywhere the
    string happens to appear. A tier named only in a cross-reference is not a
    tier either side can send."""
    return _table_first_column("Canonical commercial tiers", "`tier` value")


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


@pytest.mark.parametrize("service", sorted(SERVICE_KEYS | SURFACE_IDS))
def test_every_service_and_surface_is_defined_somewhere(service):
    assert f"`{service}`" in _text(), (
        f"{service!r} is not defined anywhere in the contract. A service or "
        "surface that is not named is not entitled."
    )


def test_it_refuses_to_claim_a_component_exists_because_it_has_a_name():
    """Neither non-tutor component is separately built in this repository:
    Locuto is another product, and the Family Portal is the parent-facing pages
    of the tutor app. An entitlement schema that quietly implies three shipped
    products is a marketing claim wearing a data model — and the marketing site
    does present three named things, which is exactly why the schema has to be
    the place that says otherwise."""
    text = _text()
    assert "Not a distinct deliverable" in text, (
        "The contract no longer states what family_portal actually is today. "
        "A component is not claimed to exist because it has a marketing name."
    )
    assert "Not integrated with Bede" in text, (
        "The contract no longer states that Locuto is not integrated with "
        "Bede. services/locuto_ipc/ is a protocol skeleton with an empty "
        "capability registry, and the contract has to say so."
    )


def _service_table_keys() -> set[str]:
    """Service keys from section 4.1's own service table — not its field table."""
    return _table_first_column("4.1 Services", "Service key")


def _surface_table_ids() -> set[str]:
    """Surface ids from section 4.2's surface table — not its field table and
    not its `entitlement` vocabulary table."""
    return _table_first_column("4.2 Surfaces", "Surface id")


def test_the_service_table_declares_exactly_the_independently_entitled_services():
    declared = _service_table_keys()
    assert declared == SERVICE_KEYS, (
        f"Section 4.1's service table declares {sorted(declared)}, expected "
        f"{sorted(SERVICE_KEYS)}. A service key is a thing that can be bought "
        "on its own; adding one is a commercial ruling (docs/DECISIONS.md "
        "entries 13 and 26), not a table edit."
    )


def test_family_portal_is_a_surface_and_not_a_service():
    """docs/DECISIONS.md entry 26. The parent-facing pages are served by the
    same process, behind the same auth, as the tutor — entitling them
    separately would sell a boundary that does not exist. 'Add the Family
    Portal as a service' is an obvious-sounding change, so the refusal is
    placed where someone making it would trip over it."""
    assert "family_portal" not in _service_table_keys(), (
        "family_portal is back in section 4.1's service table. For contract v1 "
        "it is an included SURFACE of bede_tutor (docs/DECISIONS.md entry 26). "
        "If this is deliberate, entry 26, entry 13 and section 4.4's promotion "
        "rules all need changing first — not just the table."
    )
    assert _surface_table_ids() == SURFACE_IDS, (
        f"Section 4.2's surface table declares {sorted(_surface_table_ids())}, "
        f"expected {sorted(SURFACE_IDS)}."
    )


def test_every_service_in_the_example_payload_carries_a_surfaces_object():
    """`surfaces` is required and present even when empty. That is the whole
    extension point: a field that ships in v1 carrying its only legal value can
    be extended by adding a VALUE later, where a field added later makes every
    v1 payload retroactively ambiguous — a reader cannot tell 'this version had
    no surfaces' from 'this producer omitted them'."""
    payload = json.loads(_example_payload())
    services = payload["services"]
    assert set(services) == SERVICE_KEYS, (
        f"The example payload's services are {sorted(services)}, expected "
        f"{sorted(SERVICE_KEYS)}."
    )
    for key, service in services.items():
        assert "surfaces" in service, (
            f"Service {key!r} in the example payload has no `surfaces` object. "
            "It is required even when empty; an omitted one is what makes a "
            "later promotion ambiguous."
        )
        assert isinstance(service["surfaces"], dict), (
            f"Service {key!r}'s `surfaces` is not an object."
        )


def test_the_example_payload_bundles_family_portal_under_bede_tutor():
    payload = json.loads(_example_payload())
    surfaces = payload["services"]["bede_tutor"]["surfaces"]
    assert "family_portal" in surfaces, (
        "The example payload no longer carries family_portal as a surface of "
        "bede_tutor (docs/DECISIONS.md entry 26)."
    )
    assert surfaces["family_portal"]["entitlement"] == "bundled", (
        "family_portal is not `bundled` in the example payload. `independent` "
        "is reserved and not legal at this contract version — §4.2."
    )
    for name, surface in surfaces.items():
        assert surface["entitlement"] in LEGAL_SURFACE_ENTITLEMENTS_V1, (
            f"Surface {name!r} carries entitlement "
            f"{surface['entitlement']!r}, which is not legal at 1.0.0-draft. "
            f"Legal values: {sorted(LEGAL_SURFACE_ENTITLEMENTS_V1)}."
        )
        assert "included" in surface, f"Surface {name!r} has no `included` field."


@pytest.mark.parametrize("value", sorted(SURFACE_ENTITLEMENTS))
def test_the_surface_entitlement_vocabulary_is_declared(value):
    """Both values are named in §4.2's table, including the reserved one. A
    reserved value documented now is what makes promotion a value addition
    rather than a schema change."""
    assert f"`{value}`" in _section("4.2 Surfaces"), (
        f"Surface entitlement value {value!r} is not declared in section 4.2. "
        "`independent` must stay documented-and-reserved even though it is "
        "illegal at this version — that is the extension point."
    )


def test_independent_entitlement_is_reserved_and_illegal_at_this_version():
    """The reserved value must be unmistakably not-yet-legal. A vocabulary that
    lists `independent` without saying it is refused reads as permission."""
    section = _section("4.2 Surfaces")
    assert re.search(r"`independent`.*[Rr]eserved", section, re.S), (
        "Section 4.2 no longer marks `independent` as reserved."
    )
    assert re.search(r"[Nn]ot a legal value|fails closed|\*\*No\. Reserved\.\*\*", section), (
        "Section 4.2 no longer states that `independent` is refused at this "
        "contract version. Listing a value without refusing it reads as "
        "permission to send it."
    )


def test_the_v1_ruling_on_family_portal_is_stated_and_sourced():
    section = _section("4.3 The v1 ruling")
    assert "entry 26" in section, (
        "Section 4.3 no longer cites docs/DECISIONS.md entry 26, so the ruling "
        "has no recorded status and nothing says who made it."
    )
    assert re.search(r"included surface of\s+`bede_tutor`", section), (
        "Section 4.3 no longer states the ruling: family_portal is an included "
        "surface of bede_tutor, not a separately entitled product."
    )


@pytest.mark.parametrize(
    "rule, missing",
    [
        (
            r"carrying its only legal value|value addition in a later\s+version",
            "the field-ships-in-v1 rule — without it, adding `surfaces` later "
            "makes every v1 payload ambiguous",
        ),
        (
            r"share one namespace",
            "the shared-namespace rule — without it, promotion is a rename and "
            "the surface id stops meaning one thing",
        ),
        (
            r"[Ii]dentifiers do not move|changes no `organization_id`",
            "the identifiers-do-not-move rule — the explicit requirement that a "
            "later promotion disturbs no existing household",
        ),
        (
            r"interpreted under the `contract_version` it was issued",
            "the no-retroactive-redefinition rule — an entitlement is read under "
            "the version it was issued under",
        ),
        (
            r"disposition of already-issued entitlements",
            "the requirement that a promoting version states what happens to "
            "entitlements already sold",
        ),
        (
            r"not a way to remove something from an\s+existing membership",
            "the refusal to use promotion to strip a paid-for surface",
        ),
    ],
)
def test_the_promotion_rules_survive(rule, missing):
    """Section 4.4 is the half of entry 26 that makes the v1 ruling safe to
    revisit. Each rule exists against a specific failure, and losing one is
    silent — the schema still validates, and the damage appears only when
    someone tries to promote a surface years later."""
    assert re.search(rule, _section("4.4 Why the extension point"), re.S), (
        f"Section 4.4 no longer carries {missing}."
    )


def test_the_extension_point_does_not_pre_empt_the_a_la_carte_decision():
    """Entry 13 is open on whether the membership is sold à la carte at all.
    The extension point keeps that decision reachable; it must not read as
    having taken it."""
    text = _text()
    assert "entry 13" in text, (
        "The contract no longer points at docs/DECISIONS.md entry 13. Without "
        "it, §4.4's extension point reads as a plan to unbundle rather than as "
        "keeping an open decision reachable."
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


def test_suspended_is_ruled_prospective_only():
    """docs/DECISIONS.md entry 27. `suspended` blocks future issuance, renewal
    and provisioning, and reaches nothing already issued — because
    core/licensing.py verifies offline with no revocation path, so nothing the
    commercial system records can touch a deployment already holding a valid
    key."""
    section = _section("6.1 `suspended` is prospective only")
    assert "entry 27" in section, (
        "Section 6.1 no longer cites docs/DECISIONS.md entry 27, so the ruling "
        "has no recorded status."
    )
    for blocked in ("Future issuance", "Renewal", "Further provisioning"):
        assert blocked in section, (
            f"Section 6.1 no longer states that suspension blocks {blocked!r}. "
            "Prospective-only means naming what it DOES block, not only what "
            "it does not — a state that blocks nothing is not a state."
        )
    assert re.search(r"[Rr]evoke an already-issued signed key", section), (
        "Section 6.1 no longer states that suspension does not revoke an "
        "already-issued key. That is the half a support conversation gets "
        "wrong."
    )
    assert "no revocation path" in section, (
        "Section 6.1 no longer explains WHY suspension is prospective — "
        "core/licensing.py verifies offline with no revocation path. Without "
        "the mechanism, the rule reads as a policy choice someone can argue "
        "with rather than a fact about the software."
    )


def test_the_suspension_communications_rule_survives():
    """The operative half of entry 27, and the one that reaches past this
    contract. A schema can carry a state honestly while a support macro
    promises something the software cannot do, and the second is what a
    customer actually hears."""
    section = _section("6.1 `suspended` is prospective only")
    assert re.search(
        r"[Cc]ustomer-facing and support materials must not represent suspension\s+as\s+immediate runtime enforcement",
        section,
    ), (
        "Section 6.1 no longer forbids customer-facing and support materials "
        "representing suspension as immediate runtime enforcement. That "
        "sentence is the reason entry 27 exists as a product ruling rather "
        "than a schema footnote."
    )


def test_the_suspended_row_points_at_its_own_ruling():
    """The lifecycle table is what an implementer reads. A row that reads
    'administratively halted' with no pointer invites the assumption that
    halting is what it does."""
    assert re.search(r"\| `suspended` \|[^|]*[Pp]rospective only", _section("6. Lifecycle")), (
        "The `suspended` row in the lifecycle table no longer marks itself "
        "prospective-only. Someone reading the table alone would take "
        "'administratively halted mid-term' at face value."
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


@pytest.mark.parametrize(
    "prop, why",
    [
        ("Explicit", "a declared mapping, never signed_tier = commercial_tier"),
        ("Tested", "each pair asserted, so a passthrough cannot pass by luck"),
        ("Versioned", "which mapping produced a given signed key stays answerable"),
        ("Reversible", "an already-issued license stays attributable at renewal"),
    ],
)
def test_the_tier_mapping_ruling_names_all_four_properties(prop, why):
    """docs/DECISIONS.md entry 7's 2026-09-08 amendment. Commercial tier
    identifiers and Bede signed-tier identifiers are separate namespaces that
    happen to share a spelling, and the mapping between them is never a
    passthrough."""
    section = _section("11. Compatibility plan")
    assert f"**{prop}**" in section, (
        f"Section 11 no longer requires the tier mapping to be {prop.lower()} "
        f"— {why}."
    )


def test_the_no_passthrough_rule_is_stated_in_the_contract():
    section = _section("11. Compatibility plan")
    assert re.search(r"never a passthrough|not be treated as a passthrough", section), (
        "Section 11 no longer forbids a passthrough tier mapping. `coop` means "
        "a legacy signed tier AND the Co-op Membership, so `coop` -> `coop` "
        "mints a valid key today and the ambiguity surfaces only once the two "
        "vocabularies diverge — after keys have been issued."
    )
    assert re.search(r"separate\s+namespaces", section), (
        "Section 11 no longer states that the commercial and signed tier "
        "vocabularies are separate namespaces. Sharing a spelling is the whole "
        "trap; without this sentence the two read as one vocabulary."
    )


def test_the_register_carries_the_tier_mapping_ruling():
    """Entry 7 stays open — the migration is unbuilt — but the ruling that
    constrains it is decided and belongs in the register, not only in a design
    document."""
    register = _REGISTER.read_text()
    assert "must not be\ntreated as a passthrough" in register or re.search(
        r"must not be\s+treated as a passthrough", register
    ), (
        "docs/DECISIONS.md no longer carries the no-passthrough tier-mapping "
        "ruling. The contract's §11 is the compatibility plan; the register is "
        "where the decision's state lives."
    )


def test_the_adoption_record_exists_and_names_what_adoption_requires():
    """Joint adoption is a dated, owned fact or it has not happened. An
    adoption with no date and no named owner on each side is the shape that
    lets two repositories each believe the other went first."""
    section = _section("12.1 Adoption record")
    for field in (
        "Effective contract version",
        "Effective date",
        "Bede-side owner",
        "Locuto-side owner",
        "Locuto companion pull request",
    ):
        assert field in section, (
            f"The adoption record no longer has a {field!r} row. Each is a "
            "thing that must be true before this contract binds anyone."
        )


def test_the_adoption_record_is_still_unfilled():
    """A canary, not a permanent rule. This contract is not adopted, and the
    record says so by being empty. When it is genuinely filled, this test is
    what should be updated — deliberately, by whoever adopts it — rather than
    the record quietly acquiring values nobody ratified."""
    section = _section("12.1 Adoption record")
    assert section.count("*unfilled*") >= 5, (
        "The adoption record has acquired values. If the contract has genuinely "
        "been jointly adopted, update this test and docs/DECISIONS.md entry 25 "
        "in the same change — an adoption record filled in without the register "
        "moving is exactly the drift this repository keeps catching."
    )


def test_approval_scope_is_recorded_where_an_implementer_will_read_it():
    """'The contract is approved' is a sentence read later by someone deciding
    whether they may build against it. Approving a draft artifact is not
    authorising an implementation, and the distinction has to survive in the
    document rather than in a pull-request comment."""
    section = _section("12.2 What approving this document does and does not")
    for forbidden in (
        "payment",
        "entitlement issuance",
        "validation",
        "revocation",
        "IPC capability registration",
        "provisioning",
    ):
        assert forbidden.lower() in _flat(section).lower(), (
            f"Section 12.2 no longer names {forbidden!r} among what approval "
            "does NOT authorise."
        )
    assert re.search(r"draft contract artifact only", section), (
        "Section 12.2 no longer states that approval covers a draft contract "
        "artifact only."
    )


def test_the_locuto_side_obligations_are_enumerated():
    """Condition 1 of the merge conditions. 'A compatible Locuto PR' is not
    checkable; a named list of what it must adopt is."""
    section = _section("Joint adoption required")
    for obligation in ("identifiers", "event contract", "lifecycle", "limits", "idempotency"):
        assert obligation in _flat(section).lower(), (
            f"The joint-adoption section no longer requires the Locuto side to "
            f"adopt the same {obligation}. Without the list, 'compatible' is "
            "whatever the other side decides it means."
        )
