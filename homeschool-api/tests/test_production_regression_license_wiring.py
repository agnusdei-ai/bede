"""production-regression.yml mints a throwaway license and swaps the public
key that verifies it into core/licensing.py. Two facts have to agree for
that to work, and neither is checked by anything that runs per-PR:

1. The workflow's regex has to actually match how licensing.py declares
   PUBLIC_KEY_PEM. It stopped matching -- the pattern was written
   `r'[\\s\\S]'`, a RAW string, so `\\s` is a literal backslash followed by
   `s` and the substitution found nothing. Every run of the whole workflow
   died about a second in, on `could not locate PUBLIC_KEY_PEM`, which
   skipped both downstream jobs including full-stack-boot.

2. The job that BOOTS the stack has to trust the key belonging to the
   license actually present in the .env it boots. full-stack-boot used to
   mint a second, unrelated keypair and bake that public key into the image,
   while the .env it downloaded carried a LICENSE_KEY signed by the wizard
   job's DIFFERENT key. Those can never verify each other, so the instance
   booted gated and the blocking license check failed -- which would have
   kept the job red even with (1) fixed.

Both are the "same fact in two files" shape this repo checks rather than
trusts. See CLAUDE.md's "Test The Function AND Its Invocation".
"""

from pathlib import Path
import re

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/production-regression.yml"
LICENSING = REPO / "homeschool-api/core/licensing.py"
TEST_WORKFLOW = REPO / ".github/workflows/test.yml"

PEM_ARTIFACT = "ci-license-public-key.pem"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict:
    return yaml.safe_load(workflow_text)


def _substitution_patterns(text: str) -> list[str]:
    """Every regex the workflow uses to rewrite PUBLIC_KEY_PEM."""
    return re.findall(r"re\.subn\(r'(.*?)', replacement", text)


def test_the_workflow_still_rewrites_the_public_key_somewhere(workflow_text):
    patterns = _substitution_patterns(workflow_text)
    assert patterns, (
        "No PUBLIC_KEY_PEM substitution found in production-regression.yml. "
        "If the license-injection approach changed, this guard needs to change "
        "with it -- do not just delete it."
    )


def test_every_public_key_regex_actually_matches_licensing_py(workflow_text):
    """The defect that reds the workflow: a pattern that matches nothing."""
    source = LICENSING.read_text(encoding="utf-8")
    for pattern in _substitution_patterns(workflow_text):
        count = len(re.findall(pattern, source))
        assert count == 1, (
            f"The workflow's regex {pattern!r} matches core/licensing.py "
            f"{count} time(s), not exactly once. The workflow raises "
            f"SystemExit('could not locate PUBLIC_KEY_PEM') on anything but 1, "
            f"which fails the job before any of it runs."
        )


def test_licensing_declares_the_key_the_way_the_workflow_expects():
    """The other half of the same fact, asserted from licensing.py's side."""
    source = LICENSING.read_text(encoding="utf-8")
    assert re.search(r'^PUBLIC_KEY_PEM = """', source, re.M), (
        "core/licensing.py no longer declares PUBLIC_KEY_PEM as a triple-quoted "
        "module-level assignment. production-regression.yml rewrites it by regex, "
        "so changing this shape silently breaks the entire workflow."
    )


def test_the_booting_job_does_not_mint_its_own_keypair(workflow):
    """full-stack-boot boots the wizard's .env, so minting its own key
    guarantees a signature it cannot verify."""
    steps = workflow["jobs"]["full-stack-boot"]["steps"]
    body = "\n".join(s.get("run", "") for s in steps)
    assert "ECC.generate" not in body, (
        "full-stack-boot mints its own keypair again. The .env it downloads "
        "carries a LICENSE_KEY signed by the wizard job's key, so a locally "
        "minted public key cannot verify it: the instance boots GATED and the "
        "blocking license check fails."
    )


def test_the_booting_job_trusts_the_wizard_key(workflow):
    steps = workflow["jobs"]["full-stack-boot"]["steps"]
    body = "\n".join(s.get("run", "") for s in steps)
    assert PEM_ARTIFACT in body, (
        f"full-stack-boot no longer reads {PEM_ARTIFACT}, so nothing makes the "
        f"image trust the key that signed the license in the .env it boots."
    )


def test_the_wizard_publishes_the_key_it_signed_with(workflow):
    """The producer side of the same handoff."""
    steps = workflow["jobs"]["wizard-end-to-end"]["steps"]

    writes_pem = any(PEM_ARTIFACT in s.get("run", "") for s in steps)
    assert writes_pem, (
        f"The wizard job no longer writes {PEM_ARTIFACT}, so full-stack-boot "
        f"has no key to verify the license the wizard just signed."
    )

    uploads = [
        s for s in steps
        if str(s.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert uploads, "The wizard job no longer uploads an artifact at all."
    paths = "\n".join(str(s.get("with", {}).get("path", "")) for s in uploads)
    assert PEM_ARTIFACT in paths, (
        f"{PEM_ARTIFACT} is written but not uploaded, so full-stack-boot's "
        f"download will not contain it."
    )
    assert ".env" in paths, "The wizard job stopped uploading .env."


def test_this_workflow_is_in_the_ci_change_filter():
    """Without this the guard above never runs for the change it exists to
    catch -- test.yml computes relevant=false and skips api-tests entirely.
    Same reasoning as test_decision_register.py's own filter guard, and the
    same reason it reads the pattern line rather than the whole file (the
    filename appearing in a nearby comment is a vacuous pass)."""
    pattern_line = next(
        (l for l in TEST_WORKFLOW.read_text(encoding="utf-8").splitlines()
         if "grep -qE" in l),
        None,
    )
    assert pattern_line is not None, "Could not find test.yml's grep -qE change filter."
    assert r".github/workflows/production-regression\.yml" in pattern_line, (
        "production-regression.yml is missing from test.yml's change filter, so "
        "a PR editing only that workflow skips api-tests and never runs this file."
    )
