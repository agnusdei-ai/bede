"""Fail CI on CodeQL error-level findings even without GitHub Code Security.

Read every SARIF file from the CodeQL output directory. Fail closed when
analysis results are missing, malformed, or contain error-level findings.
Warnings/notes are retained in workflow artifacts and job summaries.
"""
import json
import pathlib
import sys


def check(root: pathlib.Path) -> int:
    files = sorted(root.rglob("*.sarif"))
    if not files:
        print(f"ERROR: no SARIF reports found under {root}", file=sys.stderr)
        return 2
    errors = warnings = 0
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            runs = data["runs"]
            if not isinstance(runs, list) or not runs:
                raise ValueError("SARIF contains no runs")
            for run in runs:
                rules = {}
                for index, rule in enumerate(run.get("tool", {}).get("driver", {}).get("rules", [])):
                    rules[index] = rule.get("defaultConfiguration", {}).get("level", "warning")
                for result in run.get("results", []):
                    level = result.get("level")
                    if not level:
                        level = rules.get(result.get("ruleIndex"), "warning")
                    message = result.get("message", {}).get("text", "")
                    rule_id = result.get("ruleId", "unknown-rule")
                    print(f"{file.name}: {level}: {rule_id}: {message[:300]}")
                    if level == "error":
                        errors += 1
                    elif level == "warning":
                        warnings += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"ERROR: invalid CodeQL SARIF: {file}: {exc}", file=sys.stderr)
            return 2
    print(f"CodeQL results: {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/check_codeql_sarif.py <results_dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(check(pathlib.Path(sys.argv[1])))
