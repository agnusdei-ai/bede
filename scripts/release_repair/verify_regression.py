"""Trusted regression check: the new test must FAIL before the fix and PASS after.

Runs from the trusted checkout. It operates on a candidate repository it was
handed, overlaying the candidate's added or changed test files onto the base
SHA in a separate worktree. Candidate test outcomes are candidate-controlled
by nature, so the result is bound to the SHAs and never treated as more.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import policy as policy_mod  # noqa: E402
from release_repair import validate  # noqa: E402


def test_command(path: str) -> tuple[list[str], str] | None:
    if path.startswith("homeschool-api/") and path.endswith(".py"):
        return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", path.removeprefix("homeschool-api/")], "homeschool-api"
    for app in ("homeschool-tutor", "demo"):
        if path.startswith(app + "/") and path.endswith((".test.ts", ".test.tsx")):
            return ["npx", "vitest", "run", path.removeprefix(app + "/")], app
    return None


def run(cmd: list[str], cwd: Path, timeout: int) -> int:
    try:
        return subprocess.run(cmd, cwd=cwd, timeout=timeout).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 124


def verify(repo: Path, base: str, head: str, pol, timeout: int = 900, runner=run) -> dict:
    changed = [(c, pth) for c, pth, _ in validate.name_status(repo, base, head) if c in ("A", "M", "R")]
    tests = [pth for _, pth in changed if pol.is_test(pth) and test_command(pth)]
    report = {"base": base, "head": head, "tests": tests}
    if not tests:
        return {**report, "pre_fix_failed": False, "post_fix_passed": False, "adjacent_passed": False,
                "reason": "no_runnable_regression_test_in_change"}
    base_wt = repo.parent / (repo.name + "-base")
    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(base_wt)], capture_output=True)
    if base_wt.exists():
        shutil.rmtree(base_wt)
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"], check=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(base_wt), base], check=True)
    for t in tests:
        dst = base_wt / t
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(subprocess.run(["git", "-C", str(repo), "show", f"{head}:{t}"], check=True,
                                       capture_output=True).stdout)
    pre = {t: runner(*_split(test_command(t), base_wt), timeout) for t in tests}
    post = {t: runner(*_split(test_command(t), repo), timeout) for t in tests}
    return {**report, "pre_fix_exit": pre, "post_fix_exit": post,
            "pre_fix_failed": all(code not in (0, 124) for code in pre.values()),
            "post_fix_passed": all(code == 0 for code in post.values())}


def adjacent_passed(paths: list[str], head: str) -> bool:
    """Neighboring tests passed: every runner report exists, is for this head,
    and is not blocked. A missing report is not a pass."""
    if not paths:
        return False
    for p in paths:
        f = Path(p)
        if not f.exists():
            return False
        qa = json.loads(f.read_text())
        if qa.get("head") != head or qa.get("merge_status") == "blocked":
            return False
    return True


def _split(cmd_cwd, root: Path):
    cmd, sub = cmd_cwd
    return cmd, root / sub


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--adjacent-report", action="append", default=[],
                   help="scripts/qa/runner.py report(s) for the head; all must exist and pass")
    p.add_argument("--policy", default=str(policy_mod.DEFAULT_POLICY))
    p.add_argument("--out", required=True)
    a = p.parse_args()
    report = verify(Path(a.repo).resolve(), a.base, a.head, policy_mod.load(a.policy))
    report["adjacent_passed"] = adjacent_passed(a.adjacent_report, a.head)
    Path(a.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("pre_fix_failed", "post_fix_passed", "adjacent_passed")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
