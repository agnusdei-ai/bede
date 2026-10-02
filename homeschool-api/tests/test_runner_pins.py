"""Linux CI runners are pinned to a named Ubuntu, never `ubuntu-latest`.

GitHub migrates the `ubuntu-latest` label to a new major release on a date it
chooses — Ubuntu 26 on 2026-10-19. Every job carrying that label moves on the
same day, together, with no canary and nothing a contributor did to cause it.

This repository has already decided how it treats that class of event. Decision
register entry 12 removed the currency check from the per-PR gate precisely
because it "failed for something the world did rather than something a
contributor did", and `lockfile-refresh.yml` stays `workflow_dispatch`-only so
moving the floor under a memory-constrained deployment is an **attended** act.
An OS major-version bump under `production-regression.yml` — the job that
rehearses the whole paid Linux install, mints a license, boots the stack,
proves the gate lifted and proves backup/restore recovers real data loss — is
the same kind of event and deserves the same treatment: deliberate, on a day
someone is watching, not whenever a label is repointed.

`main` IS the release (`docs/RELEASE_QUALITY_GATES.md`), so a runner change is
a change to what every family's `make update` is verified against.

**This is a pin, not a freeze.** Moving to `ubuntu-26.04` is one edit here plus
one across the workflows, and that is the point — someone decides, rather than
discovering it from a red `main` on a Monday.

`windows-latest` is deliberately untouched: it is a different OS on a different
migration schedule, and `build-windows-installer.yml` is the only job using it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# The Ubuntu this repository's CI is verified against today.
PINNED_UBUNTU = "ubuntu-24.04"

_FLOATING = re.compile(r"runs-on:\s*ubuntu-latest")


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files, f"no workflow files found under {WORKFLOWS}"
    return files


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_no_workflow_runs_on_ubuntu_latest(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not _FLOATING.search(text), (
        f"{path.name} uses `ubuntu-latest`. Pin it to `{PINNED_UBUNTU}` (or "
        "whichever named Ubuntu this repo has moved to). A floating label "
        "moves every job at once on a date GitHub picks, which for "
        "production-regression.yml means the paid-install rehearsal changes "
        "OS without anyone deciding to."
    )


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_linux_runner_is_the_same_pinned_ubuntu(path: Path) -> None:
    """One Ubuntu across the estate, so a green job proves the same thing.

    Two different pinned versions would be worse than one floating label: the
    suite would pass on one OS and the paid-install rehearsal run on another,
    and nothing would say so.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job_name, job in (data.get("jobs") or {}).items():
        runner = job.get("runs-on")
        if not isinstance(runner, str) or not runner.startswith("ubuntu"):
            continue  # windows-latest, or a matrix form a human should review
        assert runner == PINNED_UBUNTU, (
            f"{path.name}:{job_name} runs on {runner!r}, but the rest of CI is "
            f"pinned to {PINNED_UBUNTU!r}. Move the whole estate together or "
            "not at all."
        )


def test_the_workflows_directory_is_in_the_change_filter() -> None:
    """Without this, the guard above is unreachable for workflow-only edits.

    `test.yml`'s filter computes `relevant=false` and skips `api-tests` for a
    change it does not recognise, so a PR that reintroduced `ubuntu-latest` in
    a workflow and touched nothing else would never run this file. That is the
    same vacuous-guard trap `test_decision_register.py` documents, which is why
    this reads the actual `grep -qE` pattern line rather than looking for the
    path anywhere in the workflow (a comment would satisfy that).
    """
    text = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    pattern_lines = [ln for ln in text.splitlines() if "grep -qE" in ln]
    assert pattern_lines, "test.yml no longer has a `grep -qE` change filter"

    # Split the `^(a|b|c)` alternation and require the directory as a WHOLE
    # alternative. A substring test is not enough and was wrong on the first
    # attempt: `\.github/workflows/test\.yml` contains the directory path, so
    # `in` matched a more specific sibling entry and the check kept passing
    # with the directory alternative deleted — a guard that cannot fail.
    alternatives: set[str] = set()
    for line in pattern_lines:
        group = re.search(r"\^\((.*?)\)'", line)
        if group:
            alternatives.update(part.strip() for part in group.group(1).split("|"))
    assert alternatives, "could not parse test.yml's change-filter alternation"
    assert r"\.github/workflows/" in alternatives, (
        "`.github/workflows/` is not its own alternative in test.yml's "
        "change-filter pattern, so a workflow-only change to a file this "
        "filter does not name individually skips api-tests, and this guard "
        f"never runs for exactly the edit it exists to catch. Found: "
        f"{sorted(a for a in alternatives if 'workflows' in a)}"
    )
