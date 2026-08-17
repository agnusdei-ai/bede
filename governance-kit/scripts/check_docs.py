#!/usr/bin/env python3
"""Documentation integrity checks for the kit itself.

    python scripts/check_docs.py

Two checks, both of which have caught real breakage:

  1. Every relative markdown link resolves. This kit cross-references heavily
     between prompts, reference modules, and docs, and a renamed file leaves a
     dead link that nothing else notices.
  2. Every JSON template parses. A template that does not load is worse than no
     template, since the first thing an adopter does is copy it.

Exits non-zero on failure so CI fails rather than warns.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
EXTERNAL = ("http://", "https://", "#", "mailto:")

ROOT = pathlib.Path(__file__).resolve().parent.parent


def check_links() -> list[str]:
    problems = []
    checked = 0
    for md in sorted(ROOT.rglob("*.md")):
        if ".pytest_cache" in md.parts:
            continue
        for match in LINK.finditer(md.read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith(EXTERNAL):
                continue
            checked += 1
            if not (md.parent / target.split("#")[0]).resolve().exists():
                problems.append(f"{md.relative_to(ROOT)} -> {target}")
    print(f"links: checked {checked} relative links")
    return problems


def check_templates() -> list[str]:
    problems = []
    templates = sorted((ROOT / "templates").glob("*.json"))
    if not templates:
        return ["templates/: no JSON templates found"]
    for path in templates:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path.relative_to(ROOT)}: {exc}")
    print(f"templates: checked {len(templates)} JSON files")
    return problems


def main() -> int:
    problems = check_links() + check_templates()
    if problems:
        print("\nFAILED:", *problems, sep="\n  ")
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
