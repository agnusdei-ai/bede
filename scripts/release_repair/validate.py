"""The branch validator. Runs from the trusted checkout against a candidate's
git history as DATA: it reads diffs and never executes candidate code.

A violation either needs the owner's authorization (AWAITING_AUTHORIZATION)
or refuses the branch outright. Four classes of existing-test change are never
allowed silently: they always surface to the owner by name, and a repair agent
can never authorize its own exception.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import policy as policy_mod  # noqa: E402

ASSERTION = re.compile(r"\bassert\b|expect\(|assert[A-Z_]\w*\(|\.to(?:Be|Equal|Have|Contain|Match|Throw)\w*\(|self\.assert\w+\(|check\(")
SKIP = re.compile(r"pytest\.mark\.(?:skip|skipif|xfail)|pytest\.(?:skip|xfail)\(|\b(?:it|test|describe)\.(?:skip|todo)\(|\bx(?:it|describe)\(|unittest\.skip|@skip")
BAD_STATUS = re.compile(r"\b(?:FAIL|FAILED|BLOCKED|ABSENT|UNVERIFIED|NOT_RUN|NOT RUN|failure|ok\s*[:=]\s*(?:false|False))\b")
GOOD_STATUS = re.compile(r"\b(?:PASS|PASSED|success|ok\s*[:=]\s*(?:true|True))\b")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def name_status(repo: Path, base: str, head: str) -> list[tuple[str, str, str | None]]:
    out = []
    for line in _git(repo, "diff", "--name-status", "-M", base, head).splitlines():
        parts = line.split("\t")
        code = parts[0][0]
        if code == "R":
            out.append(("R", parts[2], parts[1]))
        else:
            out.append((code, parts[1], None))
    return out


def hunks(repo: Path, base: str, head: str, path: str, old: str | None = None) -> list[tuple[list[str], list[str]]]:
    args = ["diff", "-U0", base, head, "--"] + ([old, path] if old else [path])
    result, removed, added = [], [], []
    for line in _git(repo, *args).splitlines():
        if line.startswith("@@"):
            if removed or added:
                result.append((removed, added))
            removed, added = [], []
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    if removed or added:
        result.append((removed, added))
    return result


def classify_test_change(code: str, hunk_list) -> set[str]:
    """Never-silent classes found in one existing test file's change."""
    found: set[str] = set()
    if code == "D":
        return {"removed_acceptance_assertion"}
    for removed, added in hunk_list:
        r_assert = [x for x in removed if ASSERTION.search(x)]
        a_assert = [x for x in added if ASSERTION.search(x)]
        if r_assert and not a_assert:
            found.add("removed_acceptance_assertion")
        elif r_assert and a_assert:
            found.add("weakened_expected_result")
        if any(SKIP.search(x) for x in added):
            found.add("new_skip_for_unresolved_failure")
        if any(BAD_STATUS.search(x) for x in removed) and any(GOOD_STATUS.search(x) for x in added):
            found.add("failure_relabelled_as_success")
    return found


def validate(repo: Path, base: str, head: str, branch: str, pol, is_ancestor: bool | None = None) -> dict:
    violations: list[dict] = []

    def add(code, path=None, refuse=False, never_silent=False):
        violations.append({"code": code, "path": path, "refuse": refuse,
                           "requires_authorization": not refuse, "never_silent": never_silent})

    if not pol.branch_ok(branch):
        add("branch_name_outside_release_repair", refuse=True)
    if is_ancestor is None:
        is_ancestor = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base, head]).returncode == 0
    if not is_ancestor:
        add("base_is_not_an_ancestor_of_head", refuse=True)
        return {"ok": False, "refused": True, "needs_authorization": False, "violations": violations}

    for code, path, old in name_status(repo, base, head):
        for p in {path, old} - {None}:
            if pol.is_protected(p):
                add("protected_path_changed", p)
            elif pol.is_sensitive(p):
                add("sensitive_path_changed", p)
        if pol.is_test(path) or (old and pol.is_test(old)):
            if code == "A":
                skips = classify_test_change("A", hunks(repo, base, head, path))
                for cls in skips & {"new_skip_for_unresolved_failure"}:
                    add(cls, path, never_silent=True)
                continue
            add("existing_test_changed", path)
            for cls in sorted(classify_test_change(code, [] if code == "D" else hunks(repo, base, head, path, old))):
                add(cls, path, never_silent=True)

    refused = any(v["refuse"] for v in violations)
    return {"ok": not violations, "refused": refused,
            "needs_authorization": bool(violations) and not refused, "violations": violations}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--policy", default=str(policy_mod.DEFAULT_POLICY))
    p.add_argument("--out", required=True)
    a = p.parse_args()
    pol = policy_mod.load(a.policy)
    report = validate(Path(a.repo), a.base, a.head, a.branch, pol)
    report.update({"base": a.base, "head": a.head, "branch": a.branch, "policy_revision": pol.revision})
    Path(a.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "violations": [v["code"] for v in report["violations"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
