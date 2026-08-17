"""governance-kit/ is staged here, not part of this product.

`governance-kit/` is a standalone, domain-neutral, Apache-2.0 agent-hardening
package that happens to be sitting in this repository until it is pushed to its
own. It is NOT a Bede feature: it names no product and no domain, which
`test_the_kit_names_no_product_or_domain` below asserts rather than trusts.

It is also the first top-level directory added next to `site/` since the public
deployment took its current shape, and it carries the two things that make a
directory dangerous to that deployment: a large amount of markdown, and a
`.github/workflows/` of its own.

Neither is a problem today. Both become one silently, which is why this file
exists rather than a note in a README.

WHAT COULD ACTUALLY GO WRONG
----------------------------
1. `build_pages_site.sh` grows a copy of `governance-kit/`. The kit's pages
   would then be served from agnusdei.ai, and `site/_headers`' analysis in
   test_site_headers.py — which reasons about which blocks match which paths —
   would be reasoning about a tree that no longer matches what is published.
   This mirrors the docs/ guard in test_coppa_compliance.py exactly.

2. The kit grows a `_headers` file. Cloudflare applies `_headers` from the
   published root; test_site_headers.py's whole conflict analysis rests on
   there being exactly one such file in the deployed tree. A second one that
   ever reached `publish/` would deliver a second policy for overlapping paths,
   which is the precise failure that took the demo offline once already.

3. The kit's workflow lands in the ROOT `.github/workflows/`. It is written to
   be inert until extraction (GitHub reads workflows only from a repository
   root), and test_release_quality_gates.py enumerates root workflows to decide
   which provide required checks. A stray copy there would change that answer.

4. The site-header guard becomes unreachable for kit changes. This is the one
   that was already true when the kit landed: `.github/workflows/test.yml`'s change
   filter computes `relevant=false` for a PR touching only `governance-kit/`,
   which skips `api-tests` — and `test_site_headers.py` lives in `api-tests`.
   Same failure mode test_decision_register.py documents for the register, and
   the reason `governance-kit/` is now named in that filter.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_KIT = _ROOT / "governance-kit"
_BUILD_SITE = _ROOT / "scripts" / "build_pages_site.sh"
_TEST_WORKFLOW = _ROOT / ".github" / "workflows" / "test.yml"
_ROOT_WORKFLOWS = _ROOT / ".github" / "workflows"

pytestmark = pytest.mark.skipif(
    not _KIT.is_dir(),
    reason="governance-kit/ has been extracted into its own repository",
)


def test_the_kit_is_never_copied_into_the_published_site():
    """Same shape as test_coppa_compliance.py's docs/ guard, and for a related
    reason: the kit carries its own LICENSE and NOTICE describing it as a
    separate Apache-2.0 project, which is a claim about where it is published.
    """
    build = _BUILD_SITE.read_text()
    copies = [
        line.strip()
        for line in build.splitlines()
        if re.match(r"\s*(cp|rsync)\b", line) and not line.strip().startswith("#")
    ]
    assert copies, (
        f"Found no copy commands in {_BUILD_SITE.name}. If that script was "
        "restructured, this test needs updating rather than deleting."
    )
    leaking = [c for c in copies if re.search(r"\bgovernance-kit/", c)]
    assert not leaking, (
        f"{_BUILD_SITE.name} copies governance-kit/ into the published site: "
        f"{leaking}. The kit is a separately-licensed carve-out, and publishing "
        "it puts pages on agnusdei.ai that site/_headers' own analysis never "
        "accounted for."
    )


def test_the_kit_declares_no_headers_file_of_its_own():
    """A second `_headers` anywhere that could reach `publish/` would deliver a
    second policy for overlapping paths — the exact failure test_site_headers.py
    exists to prevent, and the one that took the demo offline."""
    strays = [p.relative_to(_ROOT).as_posix() for p in _KIT.rglob("_headers")]
    assert not strays, (
        f"governance-kit/ contains a _headers file: {strays}. Cloudflare applies "
        "_headers from the published root; site/_headers must stay the only one."
    )


def test_the_kits_workflow_stays_out_of_the_root_workflows_directory():
    """The kit ships CI that is deliberately inert until extraction. A copy in
    the root directory would both run here and change which workflows
    test_release_quality_gates.py sees as providing required checks."""
    kit_workflows = sorted(p.name for p in (_KIT / ".github" / "workflows").glob("*.yml"))
    assert kit_workflows, (
        "governance-kit/.github/workflows/ is empty. The kit is meant to carry "
        "working CI so the extracted repository has it on its first push."
    )
    root_workflows = {p.name for p in _ROOT_WORKFLOWS.glob("*.yml")}
    collisions = sorted(set(kit_workflows) & root_workflows)
    assert not collisions, (
        f"A kit workflow name also exists in the root workflows directory: "
        f"{collisions}. Check it was not copied there — the kit's CI must stay "
        "inert until the directory is extracted."
    )


def test_the_site_header_guard_is_reachable_for_a_kit_only_change():
    """The gap this file was written for.

    test.yml's filter decides whether `api-tests` runs at all, and
    `test_site_headers.py` — the guard on the whole public deployment's security
    headers — lives in that job. Without `governance-kit/` in the pattern, a PR
    touching only the kit computes relevant=false and the header guard never
    runs.

    Read the `grep -qE` pattern line itself, never just the file. An earlier
    version of the equivalent test in test_decision_register.py asserted the
    filename appeared anywhere in the workflow and passed on the comment beside
    the filter, which is a vacuous pass.
    """
    pattern_lines = [
        line for line in _TEST_WORKFLOW.read_text().splitlines() if "grep -qE" in line
    ]
    assert len(pattern_lines) == 1, (
        f"Expected exactly one `grep -qE` filter line in {_TEST_WORKFLOW.name}, "
        f"found {len(pattern_lines)}. This test reads that line specifically."
    )
    assert "governance-kit/" in pattern_lines[0], (
        "governance-kit/ is missing from test.yml's change filter, so a PR "
        "touching only the kit skips api-tests — including test_site_headers.py, "
        "which guards the public site's security headers. Add it to the pattern."
    )


def test_the_kit_names_no_product_or_domain():
    """The kit is domain-neutral, and that has to be enforced rather than swept
    once.

    It was first written with this product as its worked case study, then
    rescoped to be generic. The failure mode after a rescope is re-entry: the
    next person adding a pattern reaches for the example they know, and the
    kit drifts back into being an artifact of one system. A grep is cheap and
    the drift is silent.

    `agnusdei.ai` is exempt: it is the copyright holder's own URL in NOTICE and
    the README's provenance line, which is attribution rather than domain
    content.
    """
    banned = (
        "bede", "catholic", "homeschool", "socratic", "mater amabilis",
        "narration", "catechism", "scripture", "parishioner",
    )
    offenders = []
    for path in sorted(_KIT.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".py", ".json", ".yml", ".yaml"}:
            continue
        if path.name == "LICENSE":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower().replace("agnusdei.ai", "")
            for term in banned:
                if term in lowered:
                    offenders.append(f"{path.relative_to(_ROOT).as_posix()}:{lineno} ({term})")
    assert not offenders, (
        "governance-kit/ names this product or its domain: "
        + "; ".join(offenders)
        + ". The kit is domain-neutral by design; use a generic example, or "
        "describe the incident as 'one production system' without naming it."
    )


def test_the_kit_does_not_import_from_the_application():
    """The carve-out is self-contained in both directions. An import either way
    would mean the kit cannot be extracted without breaking something, and that
    it is a second copy rather than a generalization."""
    offenders = []
    for path in _KIT.rglob("*.py"):
        text = path.read_text()
        for module in ("core.", "services.", "routers.", "models."):
            if re.search(rf"^\s*(from|import)\s+{re.escape(module)}", text, re.MULTILINE):
                offenders.append(f"{path.relative_to(_ROOT).as_posix()} imports {module}")
    assert not offenders, (
        "governance-kit/ imports from the application: "
        + "; ".join(offenders)
        + ". The kit must stay extractable."
    )
