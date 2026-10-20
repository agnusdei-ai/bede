"""Guards for the site's AEO (answer-engine) surface.

Search and answer engines read three things we control: the crawl files
(robots.txt, sitemap.xml, llms.txt), the structured data (JSON-LD), and the
visible copy. These guards keep the three telling the same story:

  - every sitemap URL is a real page, and robots.txt points at the sitemap;
  - the FAQPage JSON-LD on /schools/ mirrors the visible questions and answers,
    because markup that says something the page does not is a misleading claim;
  - plan pricing is provided by email, with no public rates, or a claim the
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


def test_school_plans_require_email_pricing_and_preserve_scope():
    page = SCHOOLS.read_text(encoding="utf-8")
    launch = (SITE.parent / "demo" / "public" / "launch.html").read_text(encoding="utf-8")
    for source in (page, launch):
        assert not re.search(r"\$\s*\d|&#(?:36|x24);|&dollar;|USD\s*\d|\d+\s*%\s*off", source, re.I)
        assert "provided in response to an email request" in source
        assert "mailto:info@agnusdei.ai?subject=Bede%20school%20pricing%20request" in source
        assert "synthetic data only" in source or "synthetic-data-only" in source
        assert "mutually agreed written" in source
    assert "each additional campus" in page.lower()
    assert "site/assets/schools-pricing.css" not in page  # Website URLs are root-relative.
    assert '/assets/schools-pricing.css' in page
    assert '/assets/schools-print.js' not in page
    assert (SITE / "assets" / "schools-pricing.css").exists()



def test_school_inquiry_replaces_public_tables_and_uses_us_english():
    page = SCHOOLS.read_text(encoding="utf-8")
    assert '<html lang="en-US">' in page
    assert 'class="school-budget-table' not in page
    assert 'id="school-budget"' in page  # Preserve inbound anchor links.
    assert 'id="print-school-budget"' not in page
    assert 'school evaluation is not the current invite-only Valor pilot' in page
    assert 'onsite implementation and customization' in page.lower()
    assert 'certified hardware' in page
    assert 'No direct student tutoring' in page
    for british_spelling in ("licence", "enrolment", "organisation", "organisational",
                             "centre", "programme", "behaviour", "colour"):
        assert not re.search(rf"\b{british_spelling}\b", page, re.I), (
            f"US English copy regressed: {british_spelling}"
        )


def test_streamlined_inquiry_navigation_and_demo_beta_dates_remain_current():
    public_pages = ["index.html", "faq/index.html", "feedback/index.html",
                    "survey/index.html", "educators/index.html", "privacy/index.html"]
    for page in public_pages:
        text = (SITE / page).read_text(encoding="utf-8")
        assert 'class="beta-banner"' not in text, f"{page} reintroduced the redundant banner"
        assert '/assets/streamlined.css' in text, f"{page} omitted approved typography"
        assert 'mailto:bede@agnusdei.ai?' in text
        assert "Free to use through August 31" not in text
        assert "Fall Launch: September" not in text
    launch = (SITE.parent / "demo" / "public" / "launch.html").read_text(encoding="utf-8")
    assert "October&nbsp;31, 2026" in launch
    assert "September 30" not in launch
    demo = (SITE.parent / "demo" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "Public beta through October 31, 2026" in demo


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


def test_home_has_no_standalone_diagnostic_or_metered_tier():
    text = HOME.read_text(encoding="utf-8").lower()
    forbidden = ["$15 / diagnostic", "pay only for the diagnostics", "no annual fee", "tier-name\">metered"]
    for phrase in forbidden:
        assert phrase not in text, f"standalone diagnostic offer reintroduced: {phrase}"
    assert "homeschool" in text and "charter &amp; campus" in text
