#!/usr/bin/env python3
"""Patch pinned Python dependencies that have a known vulnerability — and only those.

## Why this exists

`docs/DECISIONS.md` entry 12 split two questions that look like one:

* **Consistency** (`check_lockfile_consistency.py`) — do the lockfiles honour
  what `requirements*.in` declares? Offline, deterministic, runs per PR.
* **Currency** (`check_lockfile_freshness.sh`) — are these the pins
  `pip-compile` produces today? Resolves against PyPI, and was removed from
  the PR gate because it failed for what the world did rather than what a
  contributor did.

Neither answers a third question, which is the one that actually matters to a
family running this software: **is anything we ship known to be vulnerable?**
That question went unasked between PRs, and it cost us twice on 2026-10-01 —
urllib3 (CVE-2026-97687/97688/97689) and then pypdf (eight advisories,
CVE-2026-102993 through -103000) — each found only because a human looked.

This is that third check, and it is deliberately NOT a refresh. A wholesale
`pip-compile` run moves ~110 packages at once, which is what destabilised the
memory-constrained deployed backend and why `lockfile-refresh.yml` remains
`workflow_dispatch`-only. This moves **only packages with a known advisory**,
and only as far as the **lowest version that actually clears it**. A security
fix should be the smallest change that stops being vulnerable, not an excuse
to move everything else.

## The five properties that make this safe to run unattended

1. **A declared ceiling is never violated.** `requirements.in` pins
   `setuptools<84` so `pkg_resources` survives for `webrtcvad` (a
   `resemblyzer` dependency, and voice authentication depends on it). If the
   only fix for a future setuptools advisory were 84+, this REPORTS that and
   changes nothing, rather than silently breaking voice auth to clear an
   alert. A tool that can quietly violate a constraint someone wrote down on
   purpose is worse than no tool.
2. **The chosen version is verified clean itself**, not merely greater than
   some `fixed_in`. Bumping out of one advisory into another is a real
   failure mode when a package publishes several at once, which is exactly
   what pypdf did.
3. **Hashes are fetched for the new version**, never carried over. A pin
   whose hashes belong to a different release fails `--require-hashes` at
   install, which would turn a security patch into a broken deploy.
4. **It fails closed.** Any network or parse error exits non-zero and patches
   nothing. A security check that reports "clean" because it could not reach
   PyPI is the worst possible outcome — it is indistinguishable from good news.
5. **Nothing else moves.** Only the pinned version line and its `--hash=`
   lines of an affected package are rewritten; every other byte of the
   lockfile is untouched, so the diff is reviewable at a glance.

## Usage

    python scripts/security_patch.py --check   # exit 1 if anything is vulnerable
    python scripts/security_patch.py --fix     # rewrite the pins, report what moved

Data comes from PyPI's own `vulnerabilities` field, which is fed by OSV and
carries the same GHSA records GitHub's Dependabot alerts are drawn from.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

HERE = Path(__file__).resolve().parent.parent

# Same pairing check_lockfile_consistency.py uses. requirements-mobile.in has
# no lockfile of its own and is therefore not audited here; it is listed in
# neither PAIRS nor the consistency gate.
PAIRS = [
    ("requirements.in", "requirements.lock.txt"),
    ("requirements-dev.in", "requirements-dev.lock.txt"),
]

# Shared with check_lockfile_consistency.py's `_PIN`, extras group included:
# pip-compile carries extras into the pinned name (`uvicorn[standard]==0.52.4`),
# and omitting the group made that checker report such packages as absent on
# its first run. Here it matters twice over — the extras must survive the
# rewrite, or the lockfile stops installing them.
_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)(?P<extras>\[[^\]]*\])?==(?P<version>[^\s\\;]+)"
)

_TIMEOUT_SECONDS = 30


class AuditError(RuntimeError):
    """Anything that stops this from reaching a trustworthy verdict.

    Raised rather than returned so no call path can mistake an unreachable
    index for a clean result — property 4 above.
    """


@dataclass
class Finding:
    name: str
    current: str
    advisories: list[str]
    lockfiles: set[str] = field(default_factory=set)
    fix: str | None = None
    blocked_by: str | None = None

    @property
    def actionable(self) -> bool:
        return self.fix is not None


def _pypi(name: str, version: str | None = None) -> dict:
    url = (
        f"https://pypi.org/pypi/{name}/{version}/json"
        if version
        else f"https://pypi.org/pypi/{name}/json"
    )
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AuditError(f"{name}=={version} is not on PyPI") from exc
        raise AuditError(f"PyPI returned {exc.code} for {name} {version or ''}") from exc
    except Exception as exc:  # noqa: BLE001 — fail closed, never assume clean
        raise AuditError(f"could not reach PyPI for {name} {version or ''}: {exc}") from exc


def vulnerabilities(name: str, version: str) -> list[dict]:
    """Advisories affecting exactly this version, withdrawn ones excluded."""
    data = _pypi(name, version)
    return [v for v in (data.get("vulnerabilities") or []) if not v.get("withdrawn")]


def declared_specifier(in_file: Path, name: str) -> SpecifierSet:
    """The specifier `requirements*.in` declares for a package, if any.

    An empty SpecifierSet means the package is transitive — nobody wrote a
    constraint, so any version satisfies it.
    """
    wanted = canonicalize_name(name)
    for raw in in_file.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            requirement = Requirement(line)
        except Exception:  # noqa: BLE001 — the consistency gate reports these
            continue
        if canonicalize_name(requirement.name) == wanted:
            return requirement.specifier
    return SpecifierSet()


def choose_fix(name: str, current: str, specifier: SpecifierSet) -> tuple[str | None, str | None]:
    """Lowest released version that is clean AND satisfies the declared specifier.

    Returns (version, None) on success, or (None, reason) when no such version
    exists — which is a real answer a human has to act on, not a failure to
    paper over.
    """
    try:
        current_version = Version(current)
    except InvalidVersion as exc:
        raise AuditError(f"{name}: cannot parse pinned version {current!r}") from exc

    releases = []
    for raw, files in (_pypi(name).get("releases") or {}).items():
        if not files or all(f.get("yanked") for f in files):
            continue  # a yanked-only release is not somewhere to land
        try:
            candidate = Version(raw)
        except InvalidVersion:
            continue
        if candidate > current_version and not candidate.is_prerelease:
            releases.append(candidate)

    allowed = [v for v in sorted(releases) if specifier.contains(str(v))]
    if not allowed:
        if releases:
            return None, (
                f"every newer release is excluded by the declared specifier "
                f"{specifier or '(none)'} — raising it is a human decision"
            )
        return None, "no newer release exists on PyPI"

    for candidate in allowed:
        if not vulnerabilities(name, str(candidate)):
            return str(candidate), None

    return None, (
        f"every version {specifier or ''} allows is itself affected "
        "— upstream has not shipped a fix within that constraint"
    )


def _hashes_for(name: str, version: str) -> list[str]:
    digests = sorted(
        f["digests"]["sha256"] for f in (_pypi(name, version).get("urls") or [])
    )
    if not digests:
        raise AuditError(f"{name}=={version} has no downloadable files to hash")
    return digests


def rewrite_pin(lockfile: Path, name: str, old: str, new: str) -> None:
    """Replace one package's pin and its hash lines. Everything else is untouched."""
    lines = lockfile.read_text().splitlines(keepends=True)
    wanted = canonicalize_name(name)

    start = None
    for index, line in enumerate(lines):
        match = _PIN.match(line)
        if match and canonicalize_name(match["name"]) == wanted:
            if match["version"] != old:
                raise AuditError(
                    f"{lockfile.name}: {name} is pinned to {match['version']}, "
                    f"expected {old} — the file changed under us"
                )
            start = index
            break
    if start is None:
        raise AuditError(f"{lockfile.name}: no pin found for {name}")

    end = start + 1
    while end < len(lines) and lines[end].lstrip().startswith("--hash="):
        end += 1

    extras = _PIN.match(lines[start])["extras"] or ""
    digests = _hashes_for(name, new)
    block = [f"{name}{extras}=={new} \\\n"]
    for position, digest in enumerate(digests):
        suffix = " \\\n" if position < len(digests) - 1 else "\n"
        block.append(f"    --hash=sha256:{digest}{suffix}")

    lockfile.write_text("".join(lines[:start] + block + lines[end:]))


def audit() -> list[Finding]:
    findings: dict[str, Finding] = {}
    for in_name, lock_name in PAIRS:
        in_file, lock_file = HERE / in_name, HERE / lock_name
        if not lock_file.exists():
            raise AuditError(f"{lock_name} is missing")
        for line in lock_file.read_text().splitlines():
            match = _PIN.match(line)
            if not match:
                continue
            name, version = match["name"], match["version"]
            advisories = vulnerabilities(name, version)
            if not advisories:
                continue
            key = f"{canonicalize_name(name)}=={version}"
            finding = findings.get(key)
            if finding is None:
                fix, blocked = choose_fix(name, version, declared_specifier(in_file, name))
                finding = findings[key] = Finding(
                    name=name,
                    current=version,
                    advisories=sorted(a.get("id", "?") for a in advisories),
                    fix=fix,
                    blocked_by=blocked,
                )
            finding.lockfiles.add(lock_name)
    return sorted(findings.values(), key=lambda f: f.name)


def report(findings: list[Finding]) -> None:
    if not findings:
        print("CLEAN — no pinned version in any lockfile has a known advisory")
        return
    for finding in findings:
        where = ", ".join(sorted(finding.lockfiles))
        print(f"\n{finding.name}=={finding.current}  ({where})")
        for advisory in finding.advisories:
            print(f"    {advisory}")
        if finding.actionable:
            print(f"  -> fix: {finding.current} -> {finding.fix}")
        else:
            print(f"  -> NO AUTOMATIC FIX: {finding.blocked_by}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report only; exit 1 if vulnerable")
    mode.add_argument("--fix", action="store_true", help="rewrite the affected pins")
    args = parser.parse_args(argv)

    try:
        findings = audit()
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Failing closed: no verdict was reached, so none is reported.", file=sys.stderr)
        return 2

    report(findings)
    if not findings:
        return 0

    if args.check:
        return 1

    patched, blocked = [], []
    for finding in findings:
        if not finding.actionable:
            blocked.append(finding)
            continue
        try:
            for lock_name in sorted(finding.lockfiles):
                rewrite_pin(HERE / lock_name, finding.name, finding.current, finding.fix)
        except AuditError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        patched.append(finding)

    print()
    for finding in patched:
        print(f"PATCHED  {finding.name} {finding.current} -> {finding.fix}")
    for finding in blocked:
        print(f"BLOCKED  {finding.name}=={finding.current}: {finding.blocked_by}")
    # A blocked finding is still an open vulnerability: it must not exit 0.
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
