#!/usr/bin/env python3
"""Reject deprecated GitHub Actions Node.js runtimes and unpinned supported actions."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
NODE24_PINNED = {
    "checkout": {"3d3c42e5aac5ba805825da76410c181273ba90b1"},
    "setup-node": {"949feb2413d6458794dcd2491c4babbbce0c15c1",
                   "820762786026740c76f36085b0efc47a31fe5020"},
    "setup-python": {"5fda3b95a4ea91299a34e894583c3862153e4b97"},
    "upload-artifact": {"cf430e030ddbb5b0abf93d22962f4752f3646cd9"},
    "download-artifact": {"9000827ccba6bdab643e8b6fd33ac0654aef8333"},
    "setup-dotnet": {"26b0ec14cb23fa6904739307f278c14f94c95bf1"},
}
USE = re.compile(r"^\s*-?\s*uses:\s*actions/([a-z-]+)@([^\s#]+)")
NODE_VERSION = re.compile(r"^\s*node-version:\s*(.+)$")
problems = []
for path in sorted(WORKFLOWS.glob("*.yml")):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        label = f"{path.relative_to(ROOT)}:{number}"
        match = USE.match(line)
        if match and match.group(1) in NODE24_PINNED:
            name, sha = match.groups()
            if sha not in NODE24_PINNED[name]:
                problems.append(f"{label}: actions/{name} must use reviewed Node 24 SHA, found {sha}")
        version = NODE_VERSION.match(line)
        if version:
            value = version.group(1).split("#", 1)[0].strip()
            if value not in {"24", "'24'", '"24"'}:
                problems.append(f"{label}: workflow Node.js must be 24, found {value}")
        if "ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION" in line and not line.lstrip().startswith("#"):
            problems.append(f"{label}: deprecated Node runtime opt out is forbidden")
if problems:
    print("\n".join(problems), file=sys.stderr)
    raise SystemExit(1)
print(f"Node 24 action pins checked across {len(list(WORKFLOWS.glob('*.yml')))} workflows.")
