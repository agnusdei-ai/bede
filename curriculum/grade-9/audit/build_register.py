"""Build a research register, never an approved runtime ingestion manifest."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "audit" / "source-register.json"
DATE = "2026-11-12"


def record(identifier, title, author, version, publisher, url, use, license_,
           evidence, disposition, reason, demand, profile, attribution,
           exclusions, territory="USA planning; other territories not cleared"):
    profiles = {
        "by": {
            "copying": "Conditional: CC BY 3.0 covers licensed text; preserve attribution/notices.",
            "distribution": "Conditional commercial reuse of covered text; not separately linked assets.",
            "adaptation": "Conditional: credit author, link license and identify changes.",
            "tts": "Conditional text adaptation/performance; voice/provider rights separately unresolved.",
            "storage": "Conditional licensed-text copy; no corpus storage authorized.",
            "indexing": "License-compatible in principle for covered text; no ingestion authorization or runtime eligibility.",
            "model_processing": "No use-specific ban observed in cited license; provider, rights-scope and output review required; not activated.",
        },
        "sa": {
            "copying": "Conditional: original prose only under CC BY-SA 4.0; excluded inserts not cleared.",
            "distribution": "Commercial reuse conditional on attribution/license; adapted material must satisfy ShareAlike.",
            "adaptation": "Conditional ShareAlike on adapted material; not proprietary relicensing of source prose.",
            "tts": "Conditional; adaptation/ShareAlike and voice/provider rights must be reviewed.",
            "storage": "Conditional covered-text copies; no corpus storage authorized.",
            "indexing": "HOLD: define licensed scope, excluded assets and ShareAlike implications before indexing.",
            "model_processing": "HOLD: intended transformation/output/license compatibility and provider terms not approved.",
        },
        "pd": {
            "copying": "Conditional underlying US-PD text; verify exact notice and territory; PG wrapper separate.",
            "distribution": "Conditional: select lawful PG trademark/wrapper route; paid branded ebook distribution not approved.",
            "adaptation": "Conditional underlying US-PD text; modern introductions/translations/media excluded.",
            "tts": "Conditional underlying text; modern recording/voice/provider rights not granted.",
            "storage": "Conditional underlying text; no Bede corpus storage authorized.",
            "indexing": "HOLD pending authenticated edition/territory/rights gate; catalog alone is not approval.",
            "model_processing": "HOLD pending exact-edition scope, provider and owner authorization; not activated.",
        },
        "external": {
            "copying": "UNKNOWN for intended asset/use; no copied expression authorized by this record.",
            "distribution": "UNKNOWN; external citation is not a distribution license.",
            "adaptation": "UNKNOWN for expression; independently expressed facts are not copied source prose.",
            "tts": "UNKNOWN for external expression/audio/provider; no TTS asset approved.",
            "storage": "HOLD: reference metadata only; no corpus copy authorized.",
            "indexing": "HOLD: no ingestion authorization; hosting is not a rights grant.",
            "model_processing": "HOLD: no processing authorization inferred from public access.",
        },
        "reject": {
            key: "REJECT for proposed Bede commercial corpus; no permission obtained; owner chose replacement."
            for key in ("copying", "distribution", "adaptation", "tts", "storage", "indexing", "model_processing")
        },
        "original": {
            key: "Bede proprietary author draft; internal review only, not approved distribution/delivery/activation."
            for key in ("copying", "distribution", "adaptation", "tts", "storage", "indexing", "model_processing")
        },
    }
    return dict(
        id=identifier, title=title, author_translator=author, edition_version=version,
        publisher=publisher, url=url, intended_use=use, license=license_,
        evidence=evidence, evidence_date=DATE, jurisdiction=territory,
        attribution=attribution, permissions=profiles[profile],
        model_training="NOT AUTHORIZED by default, regardless of copyright eligibility",
        prohibited_or_unknown_uses=exclusions,
        accessibility_reading_demand_currency_context=demand,
        equipment_cost="Browser/print or approved accessible reader; no purchase made; printing, devices, access adaptation and adult time unpriced.",
        reviewer="Replit Agent audit author; no independent rights approval. Prior review evidence is identified, not reissued.",
        disposition=disposition, rationale=reason, activation="NOT AUTHORIZED",
    )


records = []
records.append(record(
    "M01", "Beginning and Intermediate Algebra", "Tyler Wallace",
    "2010 copyright; ISBN 978-1-4583-7768-5; PDF hash 856bd81edc61c50496982ddc849138f4e0e56fd0ddf0edb53fee9bb0830d0678; do not assume retail 2nd edition",
    "Author / wallace.ccfaculty.org",
    "https://www.wallace.ccfaculty.org/book/Beginning_and_Intermediate_Algebra.pdf",
    "Bounded M01–M36 linked selections; not bundled exercise bank",
    "CC BY 3.0 Unported, https://creativecommons.org/licenses/by/3.0/legalcode",
    ["Author index freshly fetched: https://www.wallace.ccfaculty.org/book/book.html",
     "resources/REPLACEMENT-REGISTER.md: PDF copyright leaf and hash",
     "reviews/replacement-stem.md: final M28 exclusion/recheck"],
    "candidate", "Commercially compatible text license; teaching/access/runtime gates remain.",
    "Algebra prerequisites needed; math PDF reading order untested. Printed examples 460/461 excluded due to errors; final M28 uses original replacements.",
    "by", "Tyler Wallace; title; source URL; CC BY 3.0 link; identify changes.",
    "Solutions manual, workbooks, videos and cover art excluded; no training or ingestion." ))
records.append(record(
    "H01", "World History: Cultures, States, and Societies to 1500",
    "Eugene Berger; George L. Israel; Charlotte Miller; Brian Parkinson; Andrew Reeves; Nadejda Williams",
    "2016 work; specific PDF filename 082817; hash d034e3b6900a8f533b10760d9796b3b32f5299acda6b7d0b326965a37b469340",
    "University System of Georgia / University of North Georgia Press",
    "https://web.ung.edu/media/university-press/World%20History%20Textbook-082817.pdf",
    "Bounded original prose H01–H36; no media or embedded source extracts",
    "CC BY-SA 4.0 for original content only, https://creativecommons.org/licenses/by-sa/4.0/legalcode",
    ["Institutional catalog freshly fetched: https://oer.galileo.usg.edu/history-textbooks/2/",
     "resources/REPLACEMENT-REGISTER.md: inspected PDF exclusions, hash and certificate limitation",
     "reviews/replacement-humanities.md"],
    "HOLD", "Compatible original prose license but secure learner PDF access and adaptation boundaries unresolved.",
    "College-survey prose, bounded paragraph/time caps; 2016 historical synthesis needs context and current scholarship checks. PDF/assistive access unverified; do not disable TLS.",
    "sa", "All six authors; title; USG/UNG Press; URL; CC BY-SA 4.0; identify changes and preserve adapted-content license.",
    "All media/maps, quotations, translations, boxes, linked audio and ancillary materials excluded." ))

classics = [
    ("P01", "The Odyssey", "Homer / Samuel Butler", "1900 prose translation", "1727", "Narrator/voice, violence and archaic prose; bounded scenes and supported rereading."),
    ("P02", "The History of Herodotus, Volume 1", "Herodotus / G. C. Macaulay", "1890 Macmillan source edition", "2707", "Greek outsider account of Persia; III.89–91 only as mapped, III.92 excluded; not a royal inscription."),
    ("P03", "Sophocles plays: Antigone selection", "Sophocles / Francis Storr", "1912 Loeb translation; ebook updated 2026-09-26", "31", "Verse, death/state/family conflict; select Antigone, not all plays."),
    ("P04", "The Analects", "Confucius / James Legge", "English translation portion; ebook updated 2021-01-08", "3330", "Historical translation and cultural context; not a contemporary voice for all Chinese traditions."),
    ("P05", "The Song Celestial / Bhagavad-Gita", "Edwin Arnold, rendering of the Bhagavad-Gita", "1900 New York printing; ebook updated 2013-06-23", "2388", "Victorian verse rendering of living religious tradition; contextual, nondevotional common academics."),
    ("P06", "The Aeneid", "Virgil / John Dryden", "Dryden verse translation; ebook updated 2024-12-05", "228", "Archaic verse, war and empire; reading demand/sensitive alternatives require review."),
    ("P07", "Latin for Beginners", "Benjamin L. D'Ooge", "Gutenberg ebook 18251; historical textbook, exact imprint to confirm before ingestion", "18251", "Macrons, tables and dated cultural framing; no certified audio/modern instructional alignment."),
]
for identifier, title, author, version, number, demand in classics:
    records.append(record(
        identifier, title, author, version, "Project Gutenberg; historical edition publishers as noted",
        f"https://www.gutenberg.org/ebooks/{number}",
        "Bounded mapped literature/history/Latin reading, linked externally",
        "Underlying text reported public domain in USA; PG license/trademark wrapper is separate, not CC0",
        ["ADOPTION-REVIEW.md: catalog checks", "resources/CLASSICS-EDITION-CHECK.md: additional exact-file headers/hashes",
         "resources/REPLACEMENT-REGISTER.md and reviews/replacement-humanities.md",
         "PG license freshly fetched: https://www.gutenberg.org/policy/license.html"],
        "external-only", "Continue bounded external reference; no redistribution or ingestion approval is issued.",
        demand + " Selectable HTML/EPUB availability does not certify reading order, comprehension or accessible audio.",
        "pd", f"{title}; {author}; exact edition/locator and URL; preserve applicable PG conditions for the selected distribution route.",
        "No modern editions, introductions, recordings, illustrations or worldwide PD assumption." ))

for identifier, slug, title in [
    ("X01", "elementary-algebra-2e", "Elementary Algebra 2e"),
    ("X02", "biology-2e", "Biology 2e"),
    ("X03", "world-history-volume-1", "World History Volume 1")]:
    records.append(record(
        identifier, title, "OpenStax contributors (see exact publisher edition credits; not republished here)",
        "Current web preface checked 2026-11-11 in prior review; Biology freshly rechecked 2026-11-12",
        "OpenStax / Rice University", f"https://openstax.org/books/{slug}/pages/preface",
        "Excluded former dependency; evidence of exclusion only",
        "Current prefaces state CC BY-NC-SA 4.0 plus commercial/AI reuse notice; historical CC BY file not authenticated",
        ["ADOPTION-REVIEW.md", "Current exact preface URL; no historical grant inferred"],
        "reject", "Owner chose replacement, not permission outreach; free access does not clear proprietary commercial ingestion.",
        "No current learner assignment; former textbook reading load not imported.",
        "reject", "If separately authorized in future, exact publisher/contributor attribution required; none approved here.",
        "No commercial corpus, prompts/embeddings/AI offering ingestion, distribution or training under this task." ))

records.append(record(
    "B00", "Biology reference notes", "Bede author run",
    "2026-11-12; SHA256 " + hashlib.sha256((ROOT / "resources/biology-reference-notes.md").read_bytes()).hexdigest(),
    "Bede", "../resources/biology-reference-notes.md", "Original concise concept models/checks; not full-year lessons",
    "Proprietary; no open license granted",
    ["resources/biology-reference-notes.md", "reviews/replacement-stem.md"],
    "candidate", "Existing scoped agent review; original authorship is not full-year, site-safety or release approval.",
    "Short original explanations; distinguish hypothetical models, actual observations and factual references; access tests pending.",
    "original", "Bede; preserve factual-source citations and third-party rights.",
    "No clinical/lab protocol inference, external media or model training." ))

# Each exact factual-reference URL gets its own record rather than an agency-wide grant.
# Keep the original bounded-selection/author citation as evidence, not copied source content.
notes = (ROOT / "resources/biology-reference-notes.md").read_text()
for line in notes.splitlines():
    match = re.match(r"- \*\*(S\d+) — (.+)", line)
    if not match:
        continue
    source_id = match[1]
    for index, (label, url) in enumerate(re.findall(r"\[([^\]]+)\]\((https://[^)]+)\)", line), 1):
        rec = record(
            f"B-{source_id}-{index:02}", label,
            "Exact agency/author citation and section in identity_evidence below",
            "Living HTML accessed 2026-11-12 unless article publication/DOI specified in identity_evidence",
            "Named agency or article publisher; Europe PMC is a repository, not rights owner",
            url, "Adult factual-source consultation for original Bede notes only; no learner article/media assignment",
            "UNCONFIRMED for this individual asset/use unless article-specific grant below; never inferred from government/repository hosting",
            ["resources/biology-reference-notes.md: " + source_id,
             "resources/REPLACEMENT-REGISTER.md", "reviews/replacement-stem.md"],
            "external-only", "Cite facts; no third-party expression copied or asset approval. Exact edition/provider clearance needed for expanded use.",
            "Technical adult reference, not Grade 9 independent reading. Written selection only; clinical methods/media excluded. Factual currency must be rechecked when revised.",
            "external", "Retain exact author/agency, title, DOI/URL, section and access date; any later reuse must satisfy its actual license.",
            "No media, diagrams, clinical advice, laboratory methods, linked assets, bulk ingestion or training.")
        rec["identity_evidence"] = line.removeprefix("- ")
        article_licenses = {"S12": "CC BY 4.0", "S14": "CC BY 4.0",
                            "S15": "CC BY 3.0", "S16": "CC BY 4.0", "S17": "CC BY 2.0"}
        if source_id in article_licenses:
            rec["license"] = article_licenses[source_id] + "; article-specific evidence in prior independently inspected XML/publisher links; no blanket PMC grant"
            for key in ("copying", "distribution", "adaptation"):
                rec["permissions"][key] = "License permits covered article expression conditionally with author/title/source/license attribution and change notices; excluded third-party assets need separate checks. This audit keeps use external-only."
            rec["permissions"]["tts"] = "Conditional covered text under article license; voice/provider rights and accessibility unverified; not approved."
        records.append(rec)

document = {
    "schema_version": 1, "date": DATE, "kind": "research-only-not-runtime-manifest",
    "rights_approvals": [], "training_authorized": False,
    "evidence_limits": "Freshly fetched index/catalog/PG/IES/Biology preface distinguished from prior independent source inspection. No candidate was approved by its author.",
    "records": records,
}
OUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
print(f"Wrote {len(records)} asset-specific research records; zero approvals.")
