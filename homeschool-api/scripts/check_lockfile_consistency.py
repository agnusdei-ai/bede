#!/usr/bin/env python3
"""Fail when the committed lockfiles disagree with `requirements*.in`.

## Why this exists, and what it replaced

`scripts/check_lockfile_freshness.sh` answers "is the committed lockfile what
`pip-compile` would produce **today**". That is a currency check, and it is a
useful thing to run — but it was the gate on every pull request, which made
every pull request hostage to PyPI. Any transitive dependency publishing a
release turned it red with nothing in the repository having changed:
`openai` 3.0.0 → 3.1.0, `charset-normalizer` 3.5.0 → 3.5.1,
`cuda-pathfinder` 1.6.0 → 1.6.1, `protobuf` 7.36.0 → 7.36.1 — four occasions
recorded in `docs/DECISIONS.md` entry 12 before that entry was re-decided.

The toil was meant to be absorbed by `.github/workflows/lockfile-refresh.yml`,
which is now off: refreshing ~110 packages daily into a memory-constrained
production instance was destabilising it. So nothing absorbed it, and the
question entry 12 closed became live again. It has now been re-decided — see
that entry's 2026-09-02 amendment.

## What this checks instead, and why it is not simply weaker

Entry 12's stated alternative was "fail only when `requirements*.in` changed
without the lockfiles changing alongside them" — a git-diff check. That would
stop the false positives, but it verifies nothing about the lockfile's
*content*: two files touched in one commit is not evidence that one was
derived from the other.

This checks the property the gate was actually written to protect, directly
and offline:

**Every requirement declared in an `.in` file must be present in the matching
lockfile, at a version its specifier accepts.**

That catches all three shapes of the real defect, and catches them whether or
not the same commit touched both files:

* A package added to `.in` and never compiled in — CI would install without
  it, and the failure surfaces at import, or later.
* A package removed from `.in` while the lockfile keeps installing it.
* **A raised floor that the lockfile does not honour** — `bar>=1.0` becoming
  `bar>=2.0` for a security fix while the lockfile goes on pinning 1.4. This
  is the one that matters most and the one that fails silently: nothing errors,
  nothing is missing, and the vulnerable version is what ships.

It reads only the two files, so a release published on PyPI five minutes ago
cannot affect the result. Determinism is the whole point: this gate should
fail for something a contributor did, never for something the world did.

## What it deliberately gives up

The pins can now drift behind what the floors permit without this saying so.
That is a real loss and it is the trade entry 12 records. Currency is now an
attended concern: run `scripts/check_lockfile_freshness.sh` (or dispatch
`lockfile-refresh.yml`) when someone is watching the deploy, since a refresh
changes what production installs and is a deployment rather than CI hygiene.

Transitive pins are not verified against anything here — only the direct
requirements a human wrote. Verifying the transitive closure is precisely
what needs a resolver, and a resolver is what makes the check non-deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

HERE = Path(__file__).resolve().parent.parent

PAIRS = [
    ("requirements.in", "requirements.lock.txt"),
    ("requirements-dev.in", "requirements-dev.lock.txt"),
]

# A pinned line in a pip-compile lockfile: `name==version`, optionally followed
# by a line continuation for its hashes.
#
# The extras group is not optional decoration — pip-compile DOES carry a
# requirement's extras into the pinned name (`uvicorn[standard]==0.52.4`,
# `sqlalchemy[asyncio]==2.0.52`). Omitting it made this checker report both as
# absent from a lockfile that pins them, on its very first run. Extras are
# matched and discarded: what is being compared is the distribution, and a
# requirement's extras are checked by pip at install time, not here.
_PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)(?:\[[^\]]*\])?==(?P<version>[^\s\\;]+)")


def read_pins(lockfile: Path) -> dict[str, str]:
    """Canonical name -> pinned version, for every `name==version` in the file."""
    pins: dict[str, str] = {}
    for line in lockfile.read_text().splitlines():
        match = _PIN.match(line)
        if match:
            pins[canonicalize_name(match["name"])] = match["version"]
    return pins


def read_requirements(source: Path) -> list[Requirement]:
    """Direct requirements declared in an `.in` file.

    `-r other.in` lines are skipped rather than followed: each `.in` is checked
    against its own lockfile, and `requirements-dev.lock.txt` already contains
    everything `requirements.lock.txt` does, so following the include would only
    re-report the same finding twice. Options (`-c`, `--index-url`) and comments
    are skipped for the same reason they are not requirements.
    """
    requirements = []
    for raw in source.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            requirements.append(Requirement(line))
        except Exception as exc:  # noqa: BLE001 — report, never skip silently
            print(f"  ! {source.name}: cannot parse {line!r} ({exc})")
            requirements.append(None)  # type: ignore[arg-type]
    return requirements


def check(source: Path, lockfile: Path) -> list[str]:
    problems: list[str] = []
    pins = read_pins(lockfile)

    if not pins:
        # An empty parse is not a pass. Either the lockfile is empty or this
        # parser stopped understanding the format — both are reasons to stop.
        return [
            f"{lockfile.name}: no `name==version` pins found at all. The file is "
            "empty, or its format changed and this checker needs updating; "
            "either way this gate is not currently checking anything."
        ]

    for requirement in read_requirements(source):
        if requirement is None:
            problems.append(f"{source.name}: an unparseable requirement line (above)")
            continue

        name = canonicalize_name(requirement.name)
        pinned = pins.get(name)

        if pinned is None:
            problems.append(
                f"{source.name} requires {requirement.name!r}, which is absent from "
                f"{lockfile.name}. CI installs from the lockfile, so this dependency "
                "would not be installed at all."
            )
            continue

        try:
            version = Version(pinned)
        except InvalidVersion:
            problems.append(
                f"{lockfile.name} pins {requirement.name}=={pinned}, which is not a "
                "valid version string."
            )
            continue

        # prereleases=True so a floor deliberately satisfied by a pre-release
        # pin is accepted rather than reported as a phantom violation.
        if not requirement.specifier.contains(version, prereleases=True):
            problems.append(
                f"{source.name} requires {requirement} but {lockfile.name} pins "
                f"{requirement.name}=={pinned}. The floor was raised without "
                "regenerating — CI would install the version the floor rules out. "
                "Run scripts/check_lockfile_freshness.sh --fix and commit the result."
            )

    return problems


def main() -> int:
    failures: list[str] = []

    for source_name, lock_name in PAIRS:
        source, lockfile = HERE / source_name, HERE / lock_name
        for path in (source, lockfile):
            if not path.exists():
                failures.append(f"{path.name} is missing.")
        if failures:
            continue

        problems = check(source, lockfile)
        if problems:
            failures.extend(problems)
        else:
            count = len([r for r in read_requirements(source) if r is not None])
            print(f"OK   {source_name} — all {count} declared requirements satisfied "
                  f"by {lock_name}")

    if failures:
        print("\nLockfiles disagree with requirements*.in:\n")
        for failure in failures:
            print(f"  * {failure}")
        print(
            "\nThis gate does NOT check whether the pins are the newest ones the\n"
            "floors permit — that is a separate, attended concern; see\n"
            "scripts/check_lockfile_freshness.sh and docs/DECISIONS.md entry 12.\n"
            "Every failure above is something changed in this repository."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
