#!/usr/bin/env python3
"""`npm audit` as a gate that can carry a recorded exception.

## Why this exists

`.github/workflows/frontend-tests.yml`'s own header has always named the
escape hatch: when the audit goes red, "upgrade, or record why it is
unreachable in `.github/audit-allowlist.json` — never delete the step."
`.github/audit-allowlist.json` was then built for **pip-audit only**, which
takes `--ignore-vuln` flags. `npm audit` has no equivalent flag and had no
consumer, so for the npm half the escape hatch named in the comment did not
exist: the only ways out of a red gate were an upgrade or deleting the step —
and this repository has deleted an audit gate once already (#296), taking
itself from one blocked pull request to zero vulnerability visibility.

That is the gap this closes, and it is the same shape as the allowlist file's
own `_comment`: a stated decision carried into the code that enforces it,
rather than only described.

## What it does

Runs `npm audit --json`, collects the GHSA identifier of every advisory, drops
the ones recorded in the allowlist, and fails if anything at or above
`--min-severity` remains.

Three properties are deliberate:

1. **It fails closed.** A missing `npm`, unparseable JSON, or an unreadable
   allowlist exits non-zero. An audit that reports "clean" because it could
   not ask is indistinguishable from good news, which is the same reasoning
   `scripts/security_patch.py` records for an unreachable PyPI.
2. **An allowlist entry suppresses one ADVISORY, never a package.** npm
   reports the dependents of a vulnerable package as findings in their own
   right — one `braces` advisory surfaces as five entries — so the filter
   works on advisory identity and a cleared root clears its dependents. A
   package-name allowlist would instead hide every future advisory in
   `tailwindcss`, which is not what anyone decided.
3. **A stale exemption is reported.** An allowlisted advisory that no longer
   appears means the constraint is gone and the entry should be deleted; it
   is printed rather than left to accumulate, matching the parametrized
   exemption check in `tests/test_compose_settings_passthrough.py`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_GHSA = re.compile(r"(GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})", re.IGNORECASE)

# npm's own ordering, lowest first.
_ORDER = ["info", "low", "moderate", "high", "critical"]


class GateError(RuntimeError):
    """Anything that stops this reaching a trustworthy verdict."""


def allowlisted_ids(path: Path) -> dict[str, str]:
    """{GHSA id: reason} for the npm section of the allowlist."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 — fail closed
        raise GateError(f"could not read {path}: {exc}") from exc

    entries = data.get("npm") or []
    out: dict[str, str] = {}
    for entry in entries:
        ident = entry.get("id")
        if not ident:
            raise GateError(f"an npm allowlist entry has no id: {entry!r}")
        for field in ("package", "reason", "added"):
            if not entry.get(field):
                raise GateError(f"npm allowlist entry {ident} is missing {field!r}")
        out[ident.upper()] = entry["reason"]
    return out


def run_audit(directory: Path) -> dict:
    try:
        # npm audit exits non-zero WHEN IT FINDS SOMETHING, which is the
        # normal case here, so the return code is not an error signal and
        # check=False is deliberate. A genuine failure shows up as output
        # that will not parse.
        proc = subprocess.run(
            ["npm", "audit", "--json"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GateError("npm is not on PATH") from exc
    if not proc.stdout.strip():
        raise GateError(f"npm audit produced no output in {directory} ({proc.stderr.strip()[:200]})")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(f"could not parse npm audit output in {directory}: {exc}") from exc


def findings(report: dict) -> list[dict]:
    """One row per ADVISORY, not per affected package.

    `vulnerabilities[pkg].via` holds dicts for a package's own advisories and
    plain strings for "this is vulnerable because a dependency is" — only the
    former carry an identifier, which is what makes a cleared root clear its
    dependents for free.
    """
    seen: dict[str, dict] = {}
    for package, entry in (report.get("vulnerabilities") or {}).items():
        for via in entry.get("via") or []:
            if not isinstance(via, dict):
                continue
            match = _GHSA.search(via.get("url") or "")
            ident = match.group(1).upper() if match else f"NPM-{via.get('source')}"
            seen.setdefault(
                ident,
                {
                    "id": ident,
                    "package": via.get("name") or package,
                    "severity": (via.get("severity") or "unknown").lower(),
                    "title": via.get("title") or "",
                    "url": via.get("url") or "",
                },
            )
    return sorted(seen.values(), key=lambda f: (f["package"], f["id"]))


def at_or_above(severity: str, minimum: str) -> bool:
    if severity not in _ORDER:
        return True  # an unknown severity is never silently dropped
    return _ORDER.index(severity) >= _ORDER.index(minimum)


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directories", nargs="+", help="npm project directories to audit")
    parser.add_argument("--min-severity", default="moderate", choices=_ORDER)
    parser.add_argument("--allowlist", default=str(repo / ".github" / "audit-allowlist.json"))
    args = parser.parse_args(argv)

    try:
        allowed = allowlisted_ids(Path(args.allowlist))
    except GateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    blocking: list[tuple[str, dict]] = []
    excused: list[tuple[str, dict]] = []
    seen_ids: set[str] = set()

    for name in args.directories:
        directory = repo / name
        try:
            report = run_audit(directory)
        except GateError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print("Failing closed: no verdict was reached, so none is reported.", file=sys.stderr)
            return 2

        rows = findings(report)
        print(f"\n{name}: {len(rows)} advisor{'y' if len(rows) == 1 else 'ies'}")
        for row in rows:
            seen_ids.add(row["id"])
            if row["id"] in allowed:
                excused.append((name, row))
                print(f"  ALLOWED  {row['id']}  {row['package']}  ({row['severity']})")
            elif at_or_above(row["severity"], args.min_severity):
                blocking.append((name, row))
                print(f"  BLOCKING {row['id']}  {row['package']}  ({row['severity']})  {row['title'][:80]}")
            else:
                print(f"  below {args.min_severity}: {row['id']}  {row['package']}  ({row['severity']})")

    stale = sorted(set(allowed) - seen_ids)
    if stale:
        print(
            "\nNOTE: these allowlist entries no longer match any finding and "
            "should be deleted: " + ", ".join(stale)
        )

    if blocking:
        print(f"\n{len(blocking)} advisory/advisories at or above {args.min_severity} are not allowlisted.")
        print("Upgrade the dependency, or record why it is unreachable in")
        print(".github/audit-allowlist.json's \"npm\" list. Never delete the gate.")
        return 1

    print(f"\nCLEAN at or above {args.min_severity} ({len(excused)} allowlisted finding(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
