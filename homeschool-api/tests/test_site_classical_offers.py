"""The two public offers must not imply one scope or proven acceleration.

Static content guards run without starting an API or touching student data.
Browser layout, CSP, and interaction checks are documented in the PR.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
PAGES = [SITE / p for p in ("index.html", "homeschool/index.html", "schools/index.html")]


class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_each_offer_has_a_unique_heading_main_and_audience_navigation():
    for page in PAGES:
        markup = Markup(page.read_text())
        assert sum(tag == "h1" for tag, _ in markup.tags) == 1, page
        assert sum(tag == "main" for tag, _ in markup.tags) == 1, page
        ids = [a["id"] for _, a in markup.tags if "id" in a]
        assert len(ids) == len(set(ids)), page
        hrefs = {a.get("href") for t, a in markup.tags if t == "a"}
        assert {"/schools/", "/homeschool/", "#main-content"} <= hrefs, page
        assert "main-content" in ids, page


def test_hero_photos_are_local_described_and_sized():
    for page in PAGES:
        markup = Markup(page.read_text())
        photos = [a for t, a in markup.tags if t == "img" and "/photos/" in a.get("src", "")]
        assert photos, page
        for photo in photos:
            assert photo.get("alt") and photo.get("width") and photo.get("height"), page
            target = SITE / photo["src"].lstrip("/")
            assert target.exists() and target.stat().st_size < 300_000, photo["src"]
        assert any(a.get("fetchpriority") == "high" for a in photos), page


def test_new_resources_do_not_require_third_party_fonts_images_or_scripts():
    for page in PAGES:
        for tag, attrs in Markup(page.read_text()).tags:
            if tag in {"script", "img", "link"}:
                url = attrs.get("src", attrs.get("href", ""))
                if attrs.get("rel") == "canonical":
                    continue
                assert not url.startswith(("http:", "https:", "//")), (page, url)
    css = (SITE / "assets/classical-offers.css").read_text()
    assert "@import" not in css and "https://" not in css
    assert "prefers-reduced-motion" in css and ":focus-visible" in css


def test_application_is_adult_led_and_not_a_measured_acceleration_claim():
    home, family, school = [p.read_text() for p in PAGES]
    assert "Using it is the point." in home
    assert "not automated Bede features or measured results" in home
    assert "not an automated project feature or a measured learning result" in family
    assert "not an automated pilot feature" in school
    for source in (home, family, school):
        assert "independent" in source and "study" in source
        assert not re.search(r"\b\d+\s*[%×]\s*(faster|improvement)", source, re.I)
    assert "What evidence would change your mind?" in home
    assert "delayed check" in home
    assert "delayed application in a new context" in school


def test_school_scope_is_not_confused_with_the_family_tutor():
    school = PAGES[2].read_text()
    assert "No direct student tutoring." in school
    assert "Teachers deliver instruction; Bede does not tutor learners directly" in school
    assert "separate institutional, security, and deployment qualification" in school
    assert "nondevotional academic scope" in school
    assert "disabling an optional subject alone does not establish suitability" in school
    assert "No charter approval or compliance certification is implied" in school
    assert "Illustrative stock photography" in PAGES[0].read_text()


def test_homeschool_links_to_existing_checkout_and_does_not_duplicate_prices():
    family = PAGES[1].read_text()
    assert 'href="/#membership"' in family
    assert 'href="/educators/"' in family
    assert "up to six children" in family
    assert "Enable either, both, or neither" in family
    assert "a child's faith or character is never scored" in family
    assert "$" not in family
    assert "https://agnusdei.ai/homeschool/" in (SITE / "sitemap.xml").read_text()


def test_cross_device_copy_keeps_connectivity_and_pilot_limits():
    home, family, school = [p.read_text() for p in PAGES]
    assert "MOBILE. TABLET. DESKTOP." in home
    assert "not a promise of offline tutoring" in home
    assert "automatic session handoff" in home
    assert "home-network host" in family
    assert "not an offline tutoring" in family
    assert "does not enable student mobile tutoring" in school
    assert "design goals—not claims" in school


def test_all_local_offer_links_and_fragments_resolve():
    for page in PAGES:
        for tag, attrs in Markup(page.read_text()).tags:
            href = attrs.get("href", "") if tag == "a" else ""
            if not href.startswith(("/", "#")) or href.startswith("/bede/"):
                continue  # /bede/ is mounted from demo/dist by the existing build.
            path, _, fragment = href.partition("#")
            target = SITE / path.lstrip("/") if path else page
            if target.is_dir():
                target /= "index.html"
            assert target.exists(), (page, href)
            if fragment:
                assert fragment in {
                    a.get("id") for _, a in Markup(target.read_text()).tags
                }, (page, href)


def test_ci_covers_the_new_page_styles_and_photographs():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    filters = [line for line in workflow.splitlines() if "grep -qE" in line]
    for path in ("site/homeschool/index.html", "site/assets/classical-offers.css",
                 "site/assets/photos/children-reading.jpg"):
        assert any(re.search(line.split("'")[1], path) for line in filters), path


def test_marketing_pages_only_load_feedback_script_when_a_form_exists():
    for page in PAGES:
        text = page.read_text()
        if 'src="/assets/feedback-form.js"' in text:
            assert re.search(r"<form\b", text), page
