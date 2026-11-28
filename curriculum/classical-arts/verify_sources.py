"""Verify pinned mirror snapshots and extract bounded passages, never execute them.

Input downloads are deliberately separate from this offline verifier. A mirror
commit and its ebook header establish the archived edition, not byte parity
with Gutenberg's unavailable current server.
"""
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "generated-artifacts/classical-arts-sources"
OUTPUT = ROOT / "generated-artifacts/classical-arts-verified"
PINNED = {
    "shakespeare-100.txt": {
        "sha256": "17d47ae375676f7576feb3d931784223865403a18537707f9a567247015d6781",
        "ebook": "100",
        "url": "https://raw.githubusercontent.com/GITenberg/The-Complete-Works-of-William-Shakespeare_100/c6728ea4a6edd5f1bfabd31324dbd509b2c6f29a/100-0.txt",
        "header": "Last Updated: June 14, 2018",
    },
    "lamb-573.txt": {
        "sha256": "69921bcbf8d90a980807a8a40cf3bbb1ec7e6d9bea9326918a12fc4f91ffd475",
        "ebook": "573",
        "url": "https://raw.githubusercontent.com/GITenberg/Tales-from-Shakespeare_573/4c7cbbac669bfea38af48f2e20e033607e2ba2c5/573.txt",
        "header": "Posting Date: October 10, 2008",
    },
}


def snapshot(name):
    pin = PINNED[name]
    raw = (INPUT / name).read_bytes()
    if sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError(f"Unrecognized mirror bytes: {name}")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if pin["header"] not in text[:1800] or f"[EBook #{pin['ebook']}]" not in text[:1800]:
        raise ValueError(f"Wrong edition header: {name}")
    if "START OF THIS PROJECT GUTENBERG EBOOK" not in text[:2500]:
        raise ValueError("Maintenance/error page is not an ebook")
    return text


def between(text, start, end, after=0):
    a = text.index(start, after)
    b = text.index(end, a + len(start))
    return text[a:b].strip(), a, b


def record(identifier, text, a, b, book, locator, title):
    passage = text[a:b].strip()
    return {
        "id": identifier, "title": title, "url": PINNED[book]["url"],
        "locator": locator + f"; snapshot lines {text[:a].count(chr(10))+1}–{text[:b].count(chr(10))+1}",
        "text": passage, "language": "en", "rights": "public_domain_verified",
        "text_sha256": sha256(passage.encode()).hexdigest(),
        "verification_evidence": {
            "snapshot_sha256": PINNED[book]["sha256"], "ebook": PINNED[book]["ebook"],
            "method": "Contiguous UTF-8 passage from the immutable mirrored snapshot; CRLF normalized to LF only",
            "territory": "United States; no modern translation, annotation, image, score or recording cleared",
            "primary_site_byte_parity": "Not established while the primary service is unavailable",
        },
    }


def verify():
    shakespeare, lamb = snapshot("shakespeare-100.txt"), snapshot("lamb-573.txt")
    # PG's 2017 content note explicitly explains why the historical World Library
    # restriction is not its present copyright assessment. Preserve that evidence
    # rather than silently discarding the conflicting historical notice.
    content_note = shakespeare[shakespeare.rindex("* CONTENT NOTE (added in 2017) *"):]
    content_note = content_note[:content_note.index("* END CONTENT NOTE *")+len("* END CONTENT NOTE *")]
    required = "it is the opinion\nof Project Gutenberg that this eBook is in the public domain in the\nU.S."
    if required not in content_note:
        raise ValueError("Missing present copyright assessment for ebook 100")
    passages = [
        ("greenwood", "  AMIENS.    Under the greenwood tree", "  JAQUES.",
         "As You Like It II.5, Amiens's first song", "Amiens: woodland song"),
        ("fullfathom", "         Full fathom five thy father lies;", "  FERDINAND.",
         "The Tempest I.2, Ariel's sea song and chorus", "Ariel: sea song"),
        ("sonnet18", "Shall I compare thee to a summer’s day?", "                    19",
         "Sonnets, number 18, complete fourteen lines", "Sonnet 18"),
        ("midsummer", "  PROLOGUE. If we offend", "          Enter, with a trumpet before them",
         "A Midsummer Night's Dream V.1, first prologue and immediate audience responses", "Punctuation and a performed prologue"),
        ("merchant", "  PORTIA. The quality of mercy", "  SHYLOCK.",
         "The Merchant of Venice IV.1, Portia's mercy speech; not the whole trial outcome", "Portia's appeal"),
        ("caesar", "ANTONY.\nFriends, Romans, countrymen", "FIRST CITIZEN.",
         "Julius Caesar III.2, Antony's opening funeral speech", "Antony's public address"),
        ("macbeth", "  MACBETH. If it were done when", "  LADY MACBETH. What beast",
         "Macbeth I.7, opening deliberation and pressure through Macbeth's refusal; later violent imagery excluded", "Macbeth: reasons and pressure"),
        ("henryv", "  KING. What's he that wishes so?", "Re-enter SALISBURY",
         "Henry V IV.3, bounded St Crispin passage", "Henry V: membership and memory"),
        ("tempest", "  PROSPERO. Now does my project", "[Solem music]",
         "The Tempest V.1, Prospero and Ariel through the abjuration", "The Tempest: restraint and release"),
    ]
    sources = {}
    for identifier, start, end, locator, title in passages:
        _, a, b = between(shakespeare, start, end)
        sources[identifier] = record(identifier, shakespeare, a, b, "shakespeare-100.txt", locator, title)
    # Skip the table of contents: the selected heading is the actual tale.
    _, a, b = between(lamb, "\nA MIDSUMMER NIGHT'S DREAM\n", "\nTHE WINTER'S TALE\n", 6000)
    sources["lamb"] = record("lamb", lamb, a, b, "lamb-573.txt",
                             "Tales from Shakespeare, A Midsummer Night's Dream, complete prose tale",
                             "Charles and Mary Lamb: A Midsummer Night's Dream")
    # North is the already intended 1909 source, not a replacement translation.
    # Verify the bounded portrait against BOTH the preserved OLL web extraction
    # and its publisher-hosted PDF text. Select a clean ASCII sentence rather
    # than repairing the PDF's damaged typographic glyph extraction.
    north = (
        "the people loved him marvellously also, because of the courteous manner "
        "he had to speak to every man, and to use them gently, being more ceremonious "
        "therein than was looked for in one of his years."
    )
    for filename in ("north.md", "north-pdf.txt"):
        normalized = re.sub(r"\s+", " ", (INPUT / filename).read_text())
        if north not in normalized:
            raise ValueError(f"North's portrait does not match {filename}")
    pdf_hash = sha256((INPUT / "north.pdf").read_bytes()).hexdigest()
    if pdf_hash != "e17e022b96c996d9bc1cf40a80657dba8beda2e6796c594c39dc9a34d540d6ad":
        raise ValueError("North PDF changed")
    sources["north"] = {
        "id": "north", "title": "Plutarch, North translation; Tucker Brooke edition (1909)",
        "url": "https://oll.libertyfund.org/titles/north-shakespeare-s-plutarch-vol-i-containing-the-main-sources-of-julius-caesar",
        "locator": "Life of Julius Caesar, opening portrait; sentence within 'Now Caesar immediately wan' paragraph, printed pp. 5–6",
        "text": north, "language": "en", "rights": "public_domain_verified",
        "text_sha256": sha256(north.encode()).hexdigest(),
        "verification_evidence": {
            "method": "Exact sentence matched in OLL web text and publisher-hosted PDF extraction after whitespace normalization only",
            "pdf_sha256": pdf_hash,
            "rights": "OLL copyright statement: The text is in the public domain",
            "scope": "Original North text only; not new OLL editorial matter, illustrations or the entire PDF",
            "relationship": "North translation, not a claim of the identical printing Shakespeare owned",
        },
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2)+"\n")
    (OUTPUT / "ebook-100-rights-note.txt").write_text(content_note+"\n")
    for source in sources.values():
        (OUTPUT / (source["id"]+".txt")).write_text(source["text"])
    print(json.dumps({"passages": len(sources), "locators": {k: v["locator"] for k, v in sources.items()}}, indent=2))
    return sources


if __name__ == "__main__":
    verify()
