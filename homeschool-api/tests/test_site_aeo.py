"""Guards for the site's AEO (answer-engine) surface.

Search and answer engines read three things we control: the crawl files
(robots.txt, sitemap.xml, llms.txt), the structured data (JSON-LD), and the
visible copy. These guards keep the three telling the same story:

  - every sitemap URL is a real page, and robots.txt points at the sitemap;
  - the FAQPage JSON-LD on /schools/ mirrors the visible questions and answers,
    because markup that says something the page does not is a misleading claim;
  - no page states a price the owner has not yet decided, or a claim the
    product does not make (percentile ranking, an expired beta date).

Each check was written to fail on the defect it names; see the PR for the
break-verification.
"""

import json
import re
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parents[2] / "site"
SCHOOLS = SITE / "schools" / "index.html"
HOME = SITE / "index.html"


def _jsonld(path: Path) -> list:
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
    return [json.loads(b) for b in blocks]


def _visible_faq(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    pairs = re.findall(
        r"<details>\s*<summary>(.*?)</summary>\s*<p>(.*?)</p>\s*</details>", text, re.S
    )
    return [(q.strip(), a.strip()) for q, a in pairs]


def test_sitemap_lists_only_real_pages():
    sitemap = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    urls = re.findall(r"<loc>https://agnusdei\.ai(/[^<]*)</loc>", sitemap)
    assert urls, "sitemap has no URLs"
    for path in urls:
        target = SITE / path.lstrip("/") if path != "/" else SITE / "index.html"
        if target.is_dir():
            target = target / "index.html"
        assert target.exists(), f"sitemap lists {path} but no page backs it"


def test_robots_points_at_the_sitemap():
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://agnusdei.ai/sitemap.xml" in robots


def test_schools_faq_jsonld_mirrors_the_visible_faq():
    faq = next(b for b in _jsonld(SCHOOLS) if b.get("@type") == "FAQPage")
    markup = [(e["name"], e["acceptedAnswer"]["text"]) for e in faq["mainEntity"]]
    visible = _visible_faq(SCHOOLS)
    assert markup == visible, "FAQPage JSON-LD and the visible FAQ have diverged"


def test_no_undecided_price_on_the_new_schools_page():
    # Charter/campus pricing is an OWNER decision (PR #579 is unmerged). The
    # new page must not publish a figure. The home page's existing "$15 per
    # diagnostic test" line is NOT covered here: it predates this change and is
    # flagged to the owner rather than silently edited.
    text = re.sub(r"<script.*?</script>", "", SCHOOLS.read_text(encoding="utf-8"), flags=re.S)
    assert not re.search(r"\$\s?\d", text), "the schools page publishes a dollar figure"


def test_home_has_no_expired_beta_date_or_percentile_claim():
    text = HOME.read_text(encoding="utf-8")
    assert "August 31" not in text, "the home banner promises a beta end that has passed"
    assert "percentile" not in text.lower(), "the product does not rank learners by percentile"


def test_the_new_page_is_in_the_change_filter():
    # Without this, a schools-only change computes relevant=false and skips the
    # guards above (the same trap test_decision_register.py documents).
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/test.yml").read_text(
        encoding="utf-8"
    )
    line = next(l for l in workflow.splitlines() if "grep -qE" in l and "site/index" in l)
    for needle in ["site/schools/", "site/robots\\.txt", "site/sitemap\\.xml", "site/llms\\.txt"]:
        assert needle in line, f"change filter is missing {needle}"
