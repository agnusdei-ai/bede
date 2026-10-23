#!/usr/bin/env python3
"""Conservative, deterministic test selection for the Bede monorepo.

No GitHub API, credentials or third-party libraries. Both PR branches and
developer worktrees use the *merge base*, not the moving target branch tip.
An unmapped source, a missing test or an ambiguous import broadens scope.
The selected suite never replaces required G1/non-superuser PostgreSQL,
CodeQL, audit, packaging or release qualification gates.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from collections import defaultdict, deque
from pathlib import Path

PACKAGES = ("homeschool-tutor", "demo", "license-server")
SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")
CRITICAL = re.compile(
    r"(?:auth|webauthn|passkey|campus|learner|roster|grant|security|"
    r"policy|identity|encrypt|secret|license|entitlement|privacy|"
    r"authorization|permission|migration|recovery|retention|delete)", re.I
)
CROSS = (
    "render.yaml", "docker-compose.yml", "Makefile", "wrangler.jsonc",
    "scripts/build_pages_site.sh", "docs/DECISIONS.md",
    "docs/RETENTION_POLICY.md", "docs/DATA_RETENTION.md",
    "docs/INFORMATION_SECURITY_POLICY.md", "docs/SYNTHETIC_QUALIFICATION.md",
    "site/privacy/index.html", "demo/public/privacy.html",
    "site/index.html", "site/assets/site.css",
    "docs/LICENSE_SERVER_SETUP.md",
    "homeschool-api/core/licensing.py", "homeschool-api/core/tier_display.py",
    "homeschool-tutor/src/services/api.ts", "demo/src/api.ts",
)
DOC_TESTS = {
    "docs/DECISIONS.md": "test_decision_register.py",
    "docs/RETENTION_POLICY.md": "test_coppa_compliance.py",
    "docs/DATA_RETENTION.md": "test_coppa_compliance.py",
    "docs/INFORMATION_SECURITY_POLICY.md": "test_coppa_compliance.py",
    "docs/SYNTHETIC_QUALIFICATION.md": "test_qualification_workflow.py",
}
IGNORED_PREFIXES = ("docs/", "site/", ".github/", "assets/")
TEST_EXT = re.compile(r"(?:\.test\.[jt]sx?$|\.spec\.[jt]sx?$|(^|/)test_[^/]+\.py$)")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True,
                            capture_output=True, check=True)
    return result.stdout.strip()


def changed_files(root: Path, base: str, head: str) -> tuple[str, list[str]]:
    fork = git(root, "merge-base", base, head)
    raw = subprocess.run(
        ["git", "diff", "--name-status", "-z", "--find-renames", fork, head],
        cwd=root, stdout=subprocess.PIPE, check=True,
    ).stdout.decode("utf-8")
    parts = raw.split("\0")
    paths: set[str] = set()
    i = 0
    while i < len(parts) and parts[i]:
        status = parts[i]
        i += 1
        if status[0] not in "ACDMRTUXB":
            raise ValueError(f"Unknown Git change status: {status}")
        if status[0] in "RC":
            if i + 1 >= len(parts):
                raise ValueError("Incomplete rename record")
            paths.add(parts[i])
            paths.add(parts[i + 1])
            i += 2
        else:
            if i >= len(parts):
                raise ValueError("Incomplete Git diff")
            paths.add(parts[i])
            i += 1
    return fork, sorted(paths)


def source_imports(path: Path, package_root: Path) -> set[str]:
    """Resolved local dependency candidates; no imports execute."""
    if path.suffix == ".py":
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError):
            return {"__ambiguous__"}
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    rel = path.relative_to(package_root).with_suffix("").parts
                    prefix = rel[:-node.level]
                    if node.module:
                        prefix = (*prefix, *node.module.split("."))
                    imports.add(".".join(prefix))
                elif node.module:
                    imports.add(node.module)
                if node.module:
                    imports.update(node.module + "." + a.name for a in node.names)
        return imports
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {"__ambiguous__"}
    if re.search(r"\bimport\s*\(", body):
        return {"__ambiguous__"}
    targets: set[str] = set()
    pattern = r"(?:from\s*|import\s*|require\()['\"](\.[^'\"]+)['\"]"
    for relative in re.findall(pattern, body):
        target = (path.parent / relative).resolve()
        # Only local import edges; external packages are governed by lockfiles.
        if target.is_relative_to(package_root.resolve()):
            targets.add(str(target))
    return targets


def consumers(root: Path, scope: str, changed: set[str]) -> tuple[list[str], bool]:
    """Find transitive tests importing changed modules; unknown => full suite."""
    base = root / scope
    if not base.exists():
        return [], True
    all_sources = sorted(
        p for p in base.rglob("*") if p.is_file() and p.suffix in SUFFIXES
        and "node_modules" not in p.parts and "dist" not in p.parts
        and ".venv" not in p.parts
    )
    if scope == "homeschool-api":
        names = {
            ".".join(p.relative_to(base).with_suffix("").parts): p
            for p in all_sources if p.suffix == ".py"
        }
        lookup = {str(p.resolve()): p for p in all_sources}
    else:
        names = {}
        lookup = {str(p.resolve()): p for p in all_sources}
    reverse: dict[Path, set[Path]] = defaultdict(set)
    ambiguous = False
    for p in all_sources:
        edges = source_imports(p, base)
        if "__ambiguous__" in edges:
            # A source with an unparseable import graph cannot justify a
            # narrow selection when its own dependency may change.
            if str(p.relative_to(root)) in changed:
                ambiguous = True
            continue
        for imported in edges:
            if scope == "homeschool-api":
                dest = names.get(imported) or names.get(imported + ".__init__")
            else:
                dest = next((lookup.get(imported + ext) for ext in
                             (".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx")
                             if lookup.get(imported + ext)), None)
            if dest is not None:
                reverse[dest].add(p)
    initial = [root / name for name in changed if name.startswith(scope + "/")
               and (root / name).exists() and Path(name).suffix in SUFFIXES]
    if not initial:
        return [], ambiguous
    seen = set(initial)
    todo = deque(initial)
    while todo:
        for caller in reverse[todo.popleft()]:
            if caller not in seen:
                seen.add(caller)
                todo.append(caller)
    tests = sorted(str(p.relative_to(base)) for p in seen
                   if (p.name.startswith("test_") and p.suffix == ".py"
                       and "tests" in p.parts)
                   or TEST_EXT.search(p.name))
    return tests, ambiguous or not tests


def select(root: Path, files: list[str], *, full: bool = False) -> dict:
    scopes: dict[str, dict] = {
        "backend": {"full": bool(full), "tests": [], "reasons": []},
        **{p: {"full": bool(full), "tests": [], "reasons": []} for p in PACKAGES},
    }
    reasons: list[str] = []
    critical = False
    known = False
    changed = set(files)

    def broad(scope: str, why: str) -> None:
        scopes[scope]["full"] = True
        scopes[scope]["reasons"].append(why)

    for name in files:
        if name in DOC_TESTS:
            scopes["backend"]["tests"].append("tests/" + DOC_TESTS[name])
        if name.startswith("homeschool-api/"):
            known = True
            if name.endswith(("requirements.in", "requirements-dev.in",
                              "requirements.lock.txt", "requirements-dev.lock.txt")):
                broad("backend", "Python dependency boundary")
            if CRITICAL.search(name):
                critical = True
                broad("backend", "identity, privacy or persistence boundary")
            if name.startswith("homeschool-api/core/database") or name.startswith("homeschool-api/main."):
                broad("backend", "shared backend entry or persistence")
        elif any(name.startswith(p + "/") for p in PACKAGES):
            known = True
            p = name.split("/")[0]
            if name.endswith(("/package.json", "/package-lock.json")) or "/vite.config" in name or "/tsconfig" in name:
                broad(p, "dependency or build configuration")
            if CRITICAL.search(name):
                critical = True
                broad(p, "sensitive frontend or authorization boundary")
            if p == "license-server":
                broad("backend", "cross-language license verification")
                broad("license-server", "Worker runtime and license-signing contract")
                critical = True
        elif name in CROSS or name.startswith((
            "scripts/setup_wizard/", "scripts/trust_service/",
            "scripts/qualification/", "packaging/", "agent-governance/",
            ".github/workflows/", "scripts/qa/",
        )):
            known = True
            if name.startswith("scripts/qa/"):
                reasons.append("QA selector/self-test scope")
            else:
                broad("backend", "cross-cutting operational or contract file")
                for p in PACKAGES:
                    broad(p, "cross-cutting operational or contract file")
                critical = True
        elif name.startswith(IGNORED_PREFIXES) or name.endswith((".md", ".txt", ".svg", ".png", ".webp")):
            known = True
            # Marketing docs without application dependencies do not run
            # unit tests. They still pass source-map/self-test validation.
        else:
            # Unrecognized source is not a reason to skip every check.
            for p in scopes:
                broad(p, "unmapped path: " + name)
            critical = True
    if not files:
        for p in scopes:
            broad(p, "empty change set or missing diff")
        critical = True
    if not known and files:
        reasons.append("unrecognized change scope expanded")

    for scope in scopes:
        if scopes[scope]["full"]:
            continue
        prefix = "homeschool-api" if scope == "backend" else scope
        chosen, fallback = consumers(root, prefix, changed)
        # A deleted, renamed or unmaterialized changed module cannot be
        # analyzed via the working tree; the deletion may break its consumers.
        if any(n.startswith(prefix + "/") and Path(n).suffix in SUFFIXES
               and not (root / n).exists() for n in files):
            fallback = True
        scopes[scope]["tests"].extend(chosen)
        if fallback:
            broad(scope, "affected import graph has no provable tests")
        # Changes to non-source assets, localization or public interfaces
        # can affect runtime through dynamic references.
        if any(n.startswith(prefix + "/") and
               (n.endswith((".json", ".css", ".html", ".svg", ".webp"))
                or "/public/" in n) for n in files):
            broad(scope, "non-imported runtime asset or configuration")
        scopes[scope]["tests"] = sorted(set(scopes[scope]["tests"]))

    # Cross-language API and ownership boundaries are always broad.
    if any(n in CROSS for n in files):
        for scope in scopes:
            broad(scope, "shared cross-language contract")
        critical = True

    commands: list[dict] = []
    if scopes["backend"]["full"] or scopes["backend"]["tests"]:
        args = (["tests/"] if scopes["backend"]["full"]
                else scopes["backend"]["tests"])
        commands.append({"scope": "backend", "cwd": "homeschool-api",
                         "argv": ["python", "-m", "pytest", *args, "-q"]})
    for p in PACKAGES:
        s = scopes[p]
        if not s["full"] and not s["tests"]:
            continue
        commands.append({"scope": p, "cwd": p,
                         "argv": ["npx", "tsc", "--noEmit"]})
        if p == "license-server":
            commands.append({"scope": p, "cwd": p,
                             "argv": ["npx", "tsc", "--noEmit", "-p", "tsconfig.test.json"]})
        if s["full"]:
            commands.append({"scope": p, "cwd": p,
                             "argv": ["npm", "test"] if p != "license-server"
                             else ["npx", "vitest", "run"]})
        else:
            commands.append({"scope": p, "cwd": p,
                             "argv": ["npx", "vitest", "run", *s["tests"]]})
    return {"version": 1, "changed_modules": files, "scopes": scopes,
            "critical": critical, "commands": commands, "reasons": reasons,
            "mandatory_external_gates": [
                "G1 SQLite and non-superuser PostgreSQL",
                "CodeQL analysis", "existing security and dependency audits",
                "release/physical Mac gates when applicable",
            ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", help="PR base SHA/ref (merge base determined by git)")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--file", action="append", default=[], help="Explicit changed path (test helper)")
    parser.add_argument("--full", action="store_true", help="Full release or main branch test selection")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    try:
        if args.file:
            fork, changed = "explicit", sorted(set(args.file))
        elif args.full:
            fork, changed = "full", ["scripts/qa/selector.py"]
        else:
            if not args.base:
                parser.error("--base is required without --full or --file")
            fork, changed = changed_files(root, args.base, args.head)
        result = select(root, changed, full=args.full)
        result.update({"merge_base": fork, "head": args.head,
                       "input_sha256": hashlib.sha256(
                           json.dumps([fork, args.head, changed], sort_keys=True).encode()
                       ).hexdigest()})
    except (subprocess.CalledProcessError, ValueError, OSError) as exc:
        # Preserve the failure rather than silently reporting zero tests.
        print(f"QA selector blocked: {exc}", file=__import__("sys").stderr)
        return 2
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output == "-":
        print(encoded, end="")
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
