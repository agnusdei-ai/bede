"""The sales runbook's operational facts must match the code it instructs.

`docs/SELLING_BEDE.md` is the operator's procedure for producing a license
key, and every number and tier name in it is a fact that lives somewhere else
too — in `core/licensing.py`, in `routers/pod.py`, or in the decision
register's pricing entry. This repository's standing rule for that situation
is to add the assertion that fails when they drift rather than trusting the
next person to remember, and the failure mode here is unusually bad: the
runbook is read *while fulfilling a sale*, so a stale instruction becomes a
customer with the wrong entitlement, or a command that errors with their
money already taken.

The specific drift this is written against: entry 10 caps the Family
Membership at six children, and nothing in the code knows that number. It is
enforced only because the operator passes `--seats 6` at mint time, which is
an instruction in a markdown file. Change the published cap and the runbook
goes quietly wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "SELLING_BEDE.md"
REGISTER = REPO / "docs" / "DECISIONS.md"
LICENSING = REPO / "homeschool-api" / "core" / "licensing.py"
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def test_the_runbook_exists_and_names_the_scripts_it_tells_you_to_run() -> None:
    text = _runbook()
    for script in ("issue_license.py", "generate_license_keypair.py"):
        assert script in text, f"the runbook no longer mentions {script}"
        assert (REPO / "homeschool-api" / "scripts" / script).exists(), (
            f"the runbook tells an operator to run scripts/{script}, which "
            "does not exist. That is a command typed during a sale."
        )


def test_every_tier_the_runbook_tells_you_to_mint_is_a_real_tier() -> None:
    """A typo'd `--tier` is a script error at the worst possible moment."""
    valid = set(
        re.findall(
            r'"([a-z]+)"',
            re.search(r"_VALID_TIERS\s*=\s*\{([^}]*)\}", LICENSING.read_text()).group(1),
        )
    )
    assert valid, "could not parse _VALID_TIERS out of core/licensing.py"
    used = set(re.findall(r"--tier\s+([a-z_]+)", _runbook()))
    assert used, "the runbook gives no --tier example at all"
    assert used <= valid, (
        f"the runbook mints tier(s) {sorted(used - valid)}, which "
        f"core/licensing.py does not accept (valid: {sorted(valid)})."
    )


def test_the_family_seat_instruction_matches_the_published_child_cap() -> None:
    """The six-child cap is enforced ONLY by this instruction being right.

    `routers/pod.py` compares a pod against the `seats` value signed into the
    license; nothing in the code knows the Family Membership's cap. So the
    published cap and the mint command are two copies of one number, and this
    is the check that they agree.
    """
    cap_match = re.search(r"Up to (\d+) children", REGISTER.read_text(encoding="utf-8"))
    assert cap_match, (
        "decision register entry 10 no longer states the Family Membership's "
        "child cap as 'Up to N children', so the runbook's --seats figure "
        "cannot be checked against anything."
    )
    cap = int(cap_match.group(1))

    # EVERY `--tier core` invocation in the runbook, not the first one the
    # regex happens to reach. The first version of this test anchored on one
    # match and passed with the Family Membership command changed to
    # `--seats 10`, because a different `--tier core` example earlier in the
    # document still said 6 — a guard reading a fact adjacent to the one it
    # was written to check.
    invocations = re.findall(
        r"issue_license\.py(.*?)(?=python scripts/|```|\Z)", _runbook(), re.DOTALL
    )
    assert invocations, "the runbook shows no issue_license.py invocation"

    family_seats = []
    for chunk in invocations:
        tier = re.search(r"--tier\s+([a-z_]+)", chunk)
        seats = re.search(r"--seats\s+(\d+)", chunk)
        if tier and seats and tier.group(1) == "core":
            family_seats.append(int(seats.group(1)))

    assert family_seats, "no `--tier core` invocation in the runbook sets --seats"
    wrong = [s for s in family_seats if s != cap]
    assert not wrong, (
        f"the runbook mints a Family Membership with --seats {wrong}, but "
        f"entry 10 publishes a cap of {cap} children. Whichever is wrong, a "
        "customer gets an entitlement that does not match what they bought — "
        "and the code enforces the minted number, not the published one."
    )


def test_the_runbook_still_states_that_arm_is_unverified() -> None:
    """Selling hardware nobody has booted is the one promise to keep honest.

    `arm64-build-check.yml` builds and imports under emulation; entry 23 is
    open on a real boot. The installer accepts arm64 regardless, so the only
    thing standing between that and a sold Raspberry Pi is this paragraph.
    """
    text = _runbook().lower()
    assert "arm" in text and "entry 23" in text, (
        "the runbook no longer warns that no ARM build has been booted on "
        "real hardware, while packaging/unix/install.sh still accepts "
        "arm64/aarch64."
    )


def test_the_runbook_is_in_the_change_filter() -> None:
    """Otherwise this whole file never runs for an edit to the runbook.

    `test.yml`'s filter computes `relevant=false` for a path it does not name
    and skips `api-tests`, which is the vacuous-guard trap
    `test_decision_register.py` documents. Read the real `grep -qE` pattern
    and require the path as a WHOLE alternative — a substring test would be
    satisfied by any other `docs/...` entry sharing a prefix.
    """
    lines = [ln for ln in WORKFLOW.read_text(encoding="utf-8").splitlines() if "grep -qE" in ln]
    assert lines, "test.yml no longer has a `grep -qE` change filter"
    alternatives: set[str] = set()
    for line in lines:
        group = re.search(r"\^\((.*?)\)'", line)
        if group:
            alternatives.update(p.strip() for p in group.group(1).split("|"))
    assert alternatives, "could not parse test.yml's change-filter alternation"
    assert r"docs/SELLING_BEDE\.md" in alternatives, (
        "docs/SELLING_BEDE.md is not its own alternative in test.yml's "
        "change-filter pattern, so editing the runbook skips api-tests and "
        "this guard never runs for exactly the edit it exists to catch. "
        f"Found: {sorted(a for a in alternatives if 'SELLING' in a)}"
    )
