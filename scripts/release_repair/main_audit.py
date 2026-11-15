"""Provenance audit for pushes to main. Detects; does not prevent.

For every commit a push newly introduces, ask GitHub which pull requests the
commit belongs to. A commit brought in by an approved integration method (the
merge commit or squash commit of a merged PR into main, or one of a merged
PR's own commits arriving with that PR's merge) passes. Anything else is a
finding, and the job fails loudly. This is provenance evidence, not proof
that anyone was authorized: a merged PR says how a commit arrived, not who
approved it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request

ZERO = "0" * 40


def introduced(repo_dir: str, before: str, after: str) -> list[str]:
    rng = after if before == ZERO else f"{before}..{after}"
    out = subprocess.run(["git", "-C", repo_dir, "rev-list", "--reverse", rng], check=True,
                         capture_output=True, text=True).stdout
    return out.split()


def classify(commit: str, prs: list[dict], head_commit: str) -> str | None:
    """Return None when the commit arrived by an approved method, else a finding code."""
    merged = [p for p in prs if p.get("merged_at") and p.get("base", {}).get("ref") == "main"]
    if not merged:
        return "no_merged_pull_request"
    if any(p.get("merge_commit_sha") == commit for p in merged):
        return None
    # a merged PR's own commits, arriving with that PR's merge commit (merge method)
    if any(p.get("merge_commit_sha") == head_commit for p in merged):
        return None
    return "commit_not_part_of_a_pr_merge"


def audit(commits: list[str], prs_for, head_commit: str) -> list[dict]:
    findings = []
    for c in commits:
        code = classify(c, prs_for(c), head_commit)
        if code:
            findings.append({"commit": c, "code": code})
    return findings


def _github_prs(repo: str, token: str):
    def fetch(sha: str) -> list[dict]:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{sha}/pulls",
                                     headers={"Authorization": f"Bearer {token}",
                                              "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    return fetch


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    a = p.parse_args()
    commits = introduced(a.repo_dir, a.before, a.after)
    findings = audit(commits, _github_prs(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"]), a.after)
    report = {"commits": len(commits), "findings": findings,
              "meaning": "provenance only: how each commit arrived, not whether anyone authorized it"}
    print(json.dumps(report, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fp:
            fp.write(f"### main provenance audit: {len(commits)} commit(s), {len(findings)} finding(s)\n\n")
            for f in findings:
                fp.write(f"- `{f['commit'][:12]}`: {f['code']} (a push to main outside a merged PR)\n")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
