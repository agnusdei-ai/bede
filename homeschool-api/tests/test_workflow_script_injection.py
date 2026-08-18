"""
No workflow may paste a step's free-text output into a shell script.

## The bug this pins

`.github/workflows/lockfile-refresh.yml` ran `gh pr create --body "${{
steps.summary.outputs.body }}"`. GitHub Actions substitutes `${{ }}`
expressions into the script **text** before bash parses it, so the shell
then parses whatever the expression contained. That body is markdown and
contains backticks, so bash command-substituted them. On 2026-08-18 the
run logged:

    .github/workflows/lockfile-refresh.yml: Permission denied
    requirements*.in: command not found
    lockfile-freshness: command not found
    cuda-pathfinder==1.6.0: No such file or directory

— the pull request's own body, executing on the runner. The body reached
the PR mangled, and the daily refresh that exists to keep CI green was
itself broken.

This is the canonical GitHub Actions script-injection shape. It is worth a
standing guard rather than a one-off fix for two reasons: the failure is
invisible until something in the interpolated text happens to look like a
command, and the text here is partly **external** — the package names in
that body come from PyPI metadata, not from this repository.

The remedy is always the same and costs nothing: pass the value through
`env:` and reference it as `"$VAR"`, so bash receives it as data.

## What is deliberately still allowed

`${{ steps.<id>.outcome }}` and `.conclusion` — Actions defines those as a
closed set (`success`/`failure`/`cancelled`/`skipped`), so they cannot
carry a shell metacharacter. `.github/workflows/production-regression.yml`
uses one and is correct. Banning them too would flag working code and
teach people to ignore this test, which is how a guard dies.
"""
import re
from pathlib import Path

import pytest

_WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))

# Fixed-vocabulary expressions that cannot contain shell metacharacters.
_SAFE_SUFFIXES = (".outcome", ".conclusion")

_EXPR = re.compile(r"\$\{\{\s*(steps\.[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+)[^}]*\}\}")


def _run_block_lines(text: str):
    """Yield (line_number, line) for lines inside a `run:` block.

    Indentation-based rather than a YAML parse, deliberately: the property
    is about the raw script text a runner executes, and a parser would
    happily hand back the same string with no indication of where it sat.
    """
    lines = text.splitlines()
    in_run = False
    run_indent = 0
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(r"^-?\s*run:\s*[|>]", stripped) or stripped == "run: |":
            in_run = True
            run_indent = indent
            continue
        if in_run:
            # A line at or left of the `run:` key's own indentation ends it.
            if indent <= run_indent:
                in_run = False
                continue
            yield i, line


@pytest.mark.parametrize("path", _WORKFLOWS, ids=lambda p: p.name)
def test_no_step_output_is_interpolated_into_a_shell_script(path):
    offenders = []
    for lineno, line in _run_block_lines(path.read_text()):
        for match in _EXPR.finditer(line):
            expression = match.group(1)
            if expression.endswith(_SAFE_SUFFIXES):
                continue
            offenders.append(f"  {path.name}:{lineno}: ${{{{ {expression} }}}}")

    assert not offenders, (
        "A step output is interpolated directly into a shell script. Actions\n"
        "substitutes it into the script text before bash parses it, so any\n"
        "backtick, $(...) or ; in that value executes on the runner:\n\n"
        + "\n".join(offenders)
        + "\n\nPass it through `env:` instead and reference it as \"$VAR\"."
    )


def test_the_guard_would_actually_catch_the_original_bug():
    """A guard that does not fail on the thing it was written for is
    decoration. This reconstructs the exact line that broke the refresh."""
    reconstructed = (
        "jobs:\n  a:\n    steps:\n      - name: x\n        run: |\n"
        '          gh pr create --body "${{ steps.summary.outputs.body }}"\n'
    )
    found = [
        m.group(1)
        for _, line in _run_block_lines(reconstructed)
        for m in _EXPR.finditer(line)
        if not m.group(1).endswith(_SAFE_SUFFIXES)
    ]
    assert found == ["steps.summary.outputs.body"]


def test_the_guard_does_not_fire_on_the_env_var_remedy():
    """The fix must actually pass. `env:` lines are not inside `run:`, so an
    expression there is never seen by a shell."""
    remedied = (
        "jobs:\n  a:\n    steps:\n      - name: x\n"
        "        env:\n          BODY: ${{ steps.summary.outputs.body }}\n"
        "        run: |\n"
        '          gh pr create --body "$BODY"\n'
    )
    found = [
        m.group(1)
        for _, line in _run_block_lines(remedied)
        for m in _EXPR.finditer(line)
    ]
    assert found == []
