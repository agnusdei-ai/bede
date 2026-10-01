"""Guards for scripts/security_patch.py — the unattended security patcher.

This tool rewrites lockfiles on a schedule with no human watching, so what it
REFUSES to do matters more than what it does. Every test here is one of those
refusals, and each was verified by breaking the behaviour it guards.

The network is stubbed throughout: a security guard whose result depends on
PyPI's mood is not a guard. The one live end-to-end check — replaying the real
pypdf incident and confirming the tool reproduces, byte for byte, the fix a
human shipped in PR #514 — was run by hand and recorded in that PR, following
the same posture as `scripts/mcp_client_e2e_check.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import security_patch as sp  # noqa: E402


def _index(releases: dict[str, list[str]], vulns: dict[str, list[str]]):
    """A fake PyPI: {version: [sha256...]} plus {version: [advisory id...]}."""

    def fake(name: str, version: str | None = None) -> dict:
        if version is None:
            return {"releases": {v: [{"filename": f"{name}-{v}.whl"}] for v in releases}}
        if version not in releases:
            raise sp.AuditError(f"{name}=={version} is not on PyPI")
        return {
            "vulnerabilities": [{"id": i} for i in vulns.get(version, [])],
            "urls": [{"digests": {"sha256": h}} for h in releases[version]],
        }

    return fake


# --------------------------------------------------------------------------
# 1. A declared ceiling is never violated.
# --------------------------------------------------------------------------

def test_it_refuses_to_break_a_declared_ceiling(monkeypatch):
    """The setuptools case, which is a real constraint in requirements.in.

    `setuptools<84` exists so `pkg_resources` survives for webrtcvad, which
    voice authentication depends on. Clearing an alert by stepping over that
    ceiling would trade a denial-of-service advisory for a broken login.
    """
    monkeypatch.setattr(
        sp,
        "_pypi",
        _index(
            releases={"83.0.0": ["a"], "84.0.0": ["b"], "85.0.0": ["c"]},
            vulns={"83.0.0": ["GHSA-x"]},  # only 84+ would clear it
        ),
    )
    fix, reason = sp.choose_fix("setuptools", "83.0.0", SpecifierSet("<84"))
    assert fix is None, "stepped over a ceiling someone wrote down on purpose"
    assert "human decision" in reason


def test_it_takes_the_fix_when_the_ceiling_leaves_room(monkeypatch):
    """The mirror of the above — a ceiling must not block a fix that fits."""
    monkeypatch.setattr(
        sp,
        "_pypi",
        _index(
            releases={"83.0.0": ["a"], "83.5.0": ["b"], "84.0.0": ["c"]},
            vulns={"83.0.0": ["GHSA-x"]},
        ),
    )
    fix, reason = sp.choose_fix("setuptools", "83.0.0", SpecifierSet("<84"))
    assert (fix, reason) == ("83.5.0", None)


# --------------------------------------------------------------------------
# 2. The chosen version is verified clean, not merely newer.
# --------------------------------------------------------------------------

def test_it_does_not_bump_out_of_one_advisory_into_another(monkeypatch):
    """pypdf published eight advisories at once with staggered fix versions.

    Trusting a single `fixed_in` would have landed on a version still affected
    by a sibling advisory.
    """
    monkeypatch.setattr(
        sp,
        "_pypi",
        _index(
            releases={"1.0": ["a"], "1.1": ["b"], "1.2": ["c"], "1.3": ["d"]},
            vulns={"1.0": ["GHSA-a", "GHSA-b"], "1.1": ["GHSA-b"], "1.2": ["GHSA-c"]},
        ),
    )
    fix, _ = sp.choose_fix("thing", "1.0", SpecifierSet())
    assert fix == "1.3", "landed on a version that still has an advisory"


def test_it_picks_the_lowest_clean_version_not_the_latest(monkeypatch):
    """A security fix is the smallest change that stops being vulnerable.

    Jumping to latest is what a wholesale refresh does, and is what
    destabilised the deployed backend (docs/DECISIONS.md entry 12).
    """
    monkeypatch.setattr(
        sp,
        "_pypi",
        _index(
            releases={"1.0": ["a"], "1.1": ["b"], "9.9": ["z"]},
            vulns={"1.0": ["GHSA-a"]},
        ),
    )
    fix, _ = sp.choose_fix("thing", "1.0", SpecifierSet())
    assert fix == "1.1"


def test_it_skips_prereleases_and_yanked_releases(monkeypatch):
    def fake(name, version=None):
        if version is None:
            return {
                "releases": {
                    "1.0": [{"yanked": False}],
                    "1.1": [{"yanked": True}],        # yanked — not a landing spot
                    "2.0rc1": [{"yanked": False}],    # prerelease
                    "2.0": [{"yanked": False}],
                }
            }
        return {"vulnerabilities": [{"id": "G"}] if version == "1.0" else [],
                "urls": [{"digests": {"sha256": "h"}}]}

    monkeypatch.setattr(sp, "_pypi", fake)
    fix, _ = sp.choose_fix("thing", "1.0", SpecifierSet())
    assert fix == "2.0"


# --------------------------------------------------------------------------
# 3. It fails closed.
# --------------------------------------------------------------------------

def test_an_unreachable_index_is_never_reported_as_clean(monkeypatch, capsys):
    """The worst possible outcome is "no advisories found" because nothing was
    asked. Exit 2 is distinct from both 0 (clean) and 1 (vulnerable)."""

    def unreachable(*_args, **_kwargs):
        raise sp.AuditError("network is down")

    monkeypatch.setattr(sp, "_pypi", unreachable)
    assert sp.main(["--check"]) == 2
    assert "CLEAN" not in capsys.readouterr().out


def test_a_blocked_finding_does_not_exit_zero(monkeypatch, tmp_path):
    """--fix that patched nothing because it could not must still be red.

    Exiting 0 would report an unfixed vulnerability as a successful run.
    """
    monkeypatch.setattr(
        sp, "audit",
        lambda: [sp.Finding(name="x", current="1.0", advisories=["G"],
                            blocked_by="ceiling")],
    )
    assert sp.main(["--fix"]) == 1


# --------------------------------------------------------------------------
# 4. The rewrite touches nothing else.
# --------------------------------------------------------------------------

LOCK = """\
alpha==1.0 \\
    --hash=sha256:aaa
    # via -r requirements.in
uvicorn[standard]==0.52.4 \\
    --hash=sha256:bbb \\
    --hash=sha256:ccc
    # via -r requirements.in
zulu==9.9 \\
    --hash=sha256:zzz
    # via alpha
"""


def test_only_the_named_package_moves(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sp, "_pypi",
        _index(releases={"2.0": ["new1", "new2"]}, vulns={}),
    )
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text(LOCK)
    sp.rewrite_pin(lock, "alpha", "1.0", "2.0")
    out = lock.read_text()

    assert "alpha==2.0" in out and "sha256:new1" in out and "sha256:aaa" not in out
    # everything else byte-identical
    for untouched in ("uvicorn[standard]==0.52.4", "sha256:bbb", "sha256:ccc",
                      "zulu==9.9", "sha256:zzz", "# via alpha"):
        assert untouched in out


def test_extras_survive_the_rewrite(monkeypatch, tmp_path):
    """`uvicorn[standard]` losing its extras would silently stop installing them."""
    monkeypatch.setattr(
        sp, "_pypi", _index(releases={"0.60.0": ["h1"]}, vulns={}),
    )
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text(LOCK)
    sp.rewrite_pin(lock, "uvicorn", "0.52.4", "0.60.0")
    assert "uvicorn[standard]==0.60.0" in lock.read_text()


def test_it_refuses_when_the_file_changed_under_it(monkeypatch, tmp_path):
    """A scheduled job races human commits; a stale expectation must not
    overwrite someone else's pin."""
    monkeypatch.setattr(sp, "_pypi", _index(releases={"2.0": ["h"]}, vulns={}))
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text(LOCK)
    with pytest.raises(sp.AuditError, match="changed under us"):
        sp.rewrite_pin(lock, "alpha", "1.5", "2.0")


def test_hashes_are_fetched_for_the_new_version_never_carried_over(monkeypatch, tmp_path):
    """Carried-over hashes fail `pip install --require-hashes`, turning a
    security patch into a broken deploy."""
    monkeypatch.setattr(sp, "_pypi", _index(releases={"2.0": ["fresh"]}, vulns={}))
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text(LOCK)
    sp.rewrite_pin(lock, "alpha", "1.0", "2.0")
    assert "sha256:fresh" in lock.read_text()


def test_a_version_with_no_files_is_an_error_not_an_empty_hash_block(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "_pypi", lambda n, v=None: {"urls": [], "releases": {}})
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text(LOCK)
    with pytest.raises(sp.AuditError, match="no downloadable files"):
        sp.rewrite_pin(lock, "alpha", "1.0", "2.0")


# --------------------------------------------------------------------------
# 5. It reads the same files the rest of the repo's gates read.
# --------------------------------------------------------------------------

def test_it_audits_exactly_the_pairs_the_consistency_gate_checks():
    """Two copies of one fact, so a third lockfile cannot be added to one and
    silently skipped by the other."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import check_lockfile_consistency as consistency  # noqa: PLC0415

    assert sp.PAIRS == consistency.PAIRS


def test_a_withdrawn_advisory_is_not_treated_as_a_vulnerability(monkeypatch):
    monkeypatch.setattr(
        sp, "_pypi",
        lambda n, v=None: {"vulnerabilities": [{"id": "G", "withdrawn": "2026-01-01"}]},
    )
    assert sp.vulnerabilities("thing", "1.0") == []


# --------------------------------------------------------------------------
# 6. The scheduled job exists, and CI runs these guards when it changes.
# --------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO / ".github" / "workflows" / "security-patch.yml"


def test_the_scheduled_patcher_still_exists_and_is_scheduled():
    """The only signal that a gate has been removed is its absence.

    This repository has deleted a security gate once already (#296), and a
    scheduled job is the easiest kind to disable invisibly — commenting out
    `schedule:` leaves a file that still looks present and never runs again.
    """
    import yaml  # noqa: PLC0415

    assert _WORKFLOW.exists(), "the scheduled security patcher is gone"
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML parses a bare `on:` key as the boolean True.
    triggers = workflow.get("on") or workflow.get(True) or {}
    assert "schedule" in triggers, (
        "security-patch.yml has no schedule — it only patches when someone "
        "remembers to dispatch it, which is the state this replaced."
    )
    job = workflow["jobs"]["patch"]
    assert job["permissions"]["contents"] == "write"
    assert job["permissions"]["pull-requests"] == "write"


def test_the_patcher_opens_a_pull_request_and_never_merges():
    """A dependency change must not reach `main` without CI and a human.

    `main` IS the release, so an auto-merged pin is what every family's
    `make update` builds next.
    """
    body = _WORKFLOW.read_text(encoding="utf-8")
    assert "gh pr create" in body
    assert "gh pr merge" not in body, "the patcher must never merge its own PR"
    assert "--force-with-lease" in body, "the branch push must not clobber"


def test_the_workflow_is_in_the_ci_change_filter():
    """Without this, editing the patcher computes `relevant=false`, skips
    `api-tests`, and never runs the guards in this file — the exact gap
    test_decision_register.py documents.

    The `grep -qE` pattern line is read directly rather than searching the
    whole workflow, because the first version of that sibling test passed on
    a comment mentioning the filename.
    """
    test_yml = (_REPO / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    pattern_line = next(
        line for line in test_yml.splitlines() if "grep -qE" in line and "homeschool-api/" in line
    )
    assert r"security-patch\.yml" in pattern_line
