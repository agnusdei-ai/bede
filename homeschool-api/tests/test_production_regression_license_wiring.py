"""production-regression.yml mints a throwaway license per job and swaps the
public key that verifies it into core/licensing.py. Two facts have to hold for
that to work, and until now neither was checked per-PR.

1. The substitution has to actually match how licensing.py declares
   PUBLIC_KEY_PEM. It stopped matching: the pattern was written
   `r'[\\s\\S]'`, a RAW string, so `\\s` is a literal backslash followed by
   `s` and it found nothing. Every run of the whole workflow died about a
   second in on `could not locate PUBLIC_KEY_PEM`, which skipped both
   downstream jobs -- full-stack-boot has been reported as SKIPPED, not red,
   since #502.

2. The key baked into the image and the LICENSE_KEY in the .env being booted
   have to come from the SAME mint. full-stack-boot mints its own keypair
   (see test_production_regression_license_workflow.py, which requires that)
   but boots the .env the WIZARD job uploaded, carrying a LICENSE_KEY the
   wizard signed with a different key. Those cannot verify each other by
   construction, so the instance booted gated and the deliberately-blocking
   license check failed -- which would have kept the job red even with (1)
   fixed. The per-job minting design was right; it was just never finished on
   the consuming side.

Companion to test_production_regression_license_workflow.py, which guards the
ORDER of the minting steps. This file guards that what they mint is coherent.
"""

from pathlib import Path
import re

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/production-regression.yml"
LICENSING = REPO / "homeschool-api/core/licensing.py"
TEST_WORKFLOW = REPO / ".github/workflows/test.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict:
    return yaml.safe_load(workflow_text)


def _substitution_patterns(text: str) -> list[str]:
    return re.findall(r"re\.subn\(r'(.*?)', replacement", text)


def test_the_workflow_still_rewrites_the_public_key_somewhere(workflow_text):
    """Guards the guards: if this ever finds nothing, every check below would
    pass vacuously."""
    assert _substitution_patterns(workflow_text), (
        "No PUBLIC_KEY_PEM substitution found in production-regression.yml. If "
        "the license-injection approach changed, update this file with it -- as "
        "written it would now pass no matter what the workflow does."
    )


def test_every_public_key_regex_actually_matches_licensing_py(workflow_text):
    """The defect that took the whole workflow down: a pattern matching nothing."""
    source = LICENSING.read_text(encoding="utf-8")
    for pattern in _substitution_patterns(workflow_text):
        count = len(re.findall(pattern, source))
        assert count == 1, (
            f"The workflow's regex {pattern!r} matches core/licensing.py "
            f"{count} time(s), not exactly once. The workflow raises "
            f"SystemExit('could not locate PUBLIC_KEY_PEM') on anything but 1, "
            f"killing the job before any of it runs."
        )


def test_licensing_declares_the_key_the_way_the_workflow_expects():
    """The same fact from licensing.py's side."""
    source = LICENSING.read_text(encoding="utf-8")
    assert re.search(r'^PUBLIC_KEY_PEM = """', source, re.M), (
        "core/licensing.py no longer declares PUBLIC_KEY_PEM as a triple-quoted "
        "module-level assignment. production-regression.yml rewrites it by regex, "
        "so changing this shape silently breaks the entire workflow."
    )


def _step_names(job: dict) -> list[str]:
    return [s.get("name") or str(s.get("uses", "")) for s in job["steps"]]


def test_the_booting_job_repoints_the_downloaded_env_at_its_own_license(workflow):
    """full-stack-boot mints its own keypair, so the wizard-signed LICENSE_KEY
    it downloads is unverifiable by the key it just installed."""
    job = workflow["jobs"]["full-stack-boot"]
    body = "\n".join(s.get("run", "") for s in job["steps"])
    assert "LICENSE_KEY=" in body and "CI_TEST_LICENSE_KEY" in body, (
        "full-stack-boot no longer rewrites the downloaded .env's LICENSE_KEY "
        "from the license it minted. It boots a .env signed by the WIZARD job's "
        "key while its image carries a different public key: the gate stays up "
        "and the blocking license check fails every run."
    )


def test_it_repoints_after_downloading_and_before_booting(workflow):
    """Order is the whole point -- rewriting before the download would be
    overwritten by it, and after the boot would be too late."""
    names = _step_names(workflow["jobs"]["full-stack-boot"])
    download = next(i for i, n in enumerate(names) if "download-artifact" in n)
    repoint = next(i for i, n in enumerate(names) if "Re-point" in n)
    boot = next(i for i, n in enumerate(names) if n.startswith("Start the full stack"))
    assert download < repoint < boot, (
        f"full-stack-boot's steps are out of order: download={download}, "
        f"re-point={repoint}, boot={boot}. The re-point must sit between them."
    )


def _repoint_step(workflow: dict) -> dict:
    for step in workflow["jobs"]["full-stack-boot"]["steps"]:
        if "Re-point" in (step.get("name") or ""):
            return step
    raise AssertionError("full-stack-boot has no .env re-point step")


def test_the_repoint_refuses_rather_than_silently_booting_nothing(workflow):
    """A .env with no LICENSE_KEY line must fail loudly. Appending one instead,
    or writing nothing, would boot an unlicensed stack whose /health still
    answers -- a green job proving nothing.

    Scoped to the re-point step's OWN body, never the whole job: the minting
    step above it contains the identical `count != 1` / `raise SystemExit`
    pair, so a job-wide scan passes on that text while this step silently
    stops failing closed. That vacuous version was written first and caught
    by break-verifying it."""
    body = _repoint_step(workflow).get("run", "")
    assert "count != 1" in body, (
        "The .env re-point no longer checks that exactly one LICENSE_KEY line "
        "was replaced."
    )
    assert "raise SystemExit" in body, (
        "The .env re-point no longer fails closed when LICENSE_KEY is absent -- "
        "it would boot an unlicensed stack and report success."
    )


def test_this_workflow_is_in_the_ci_change_filter():
    """Without this the guards above never run for the change they exist to
    catch: test.yml computes relevant=false and skips api-tests. Reads the
    pattern line itself rather than the whole file, since the filename in a
    nearby comment is a vacuous pass -- the trap test_decision_register.py
    records falling into."""
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
