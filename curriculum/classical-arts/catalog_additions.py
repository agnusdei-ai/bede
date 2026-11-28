"""Original catalog notes with exact reproduction and bibliographic references."""
import json
import subprocess
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART = [
    ("erythraean", "Erythraean Sibyl", "Sibila eritrea", "6/65/Erythraean.jpg",
     "File:Erythraean.jpg", "Erythraean Sibyl"),
    ("jeremiah", "Jeremiah", "Jeremías", "e/e9/Michelangelo%2C_profeti%2C_Jeremiah_01.jpg",
     "File:Michelangelo,_profeti,_Jeremiah_01.jpg", "Jeremiah (Michelangelo)"),
    ("cumaean", "Cumaean Sibyl", "Sibila de Cumas", "8/8f/CumaeanSibylByMichelangelo.jpg",
     "File:CumaeanSibylByMichelangelo.jpg", "Cumaean Sibyl"),
    ("delphic", "Delphic Sibyl", "Sibila délfica", "b/b0/Michelangelo_-_Delphic_Sibyl.jpg",
     "File:Michelangelo_-_Delphic_Sibyl.jpg", "Delphic Sibyl"),
    ("persian", "Persian Sibyl", "Sibila persa", "1/10/Michelangelo_Buonarroti_036.jpg",
     "File:Michelangelo_Buonarroti_036.jpg", "Persian Sibyl"),
]
ART_INPUT_HASHES = [
    "c72a6c1ea497f9008364835545be09b8234633c27d345cac13173db029ee52e3",
    "249d2b94c34d9ce9609cf2bf1438e2ee1452a6d35ee289159c0fcf9ac0f00df3",
    "746e5afd9e7b1cb0c9dba2bf905a1e58b131245359d3331a226bfe53106b57ca",
    "5bed84d55d3931f96ff67fc13d89c5b90b64ba1c0af713a64366f69cbc3ea9a9",
    "1249e4b9b4ddda19c42b33a300d797209be4599b6916b7efe806189f4c076e1e",
]
ART_DIR = ROOT / "homeschool-api/data/curriculum/classical-arts-art"
BEETHOVEN = "https://imslp.org/wiki/Piano_Sonata_No.14%2C_Op.27_No.2_(Beethoven%2C_Ludwig_van)"
DOWLAND = "https://imslp.org/wiki/Flow_My_Tears_(Dowland,_John)"
BYRD = "https://imslp.org/wiki/The_Earl_of_Salisbury_Pavan_and_2_Galliards_(Byrd,_William)"

def music_reference(identifier, locale="en"):
    if identifier == "beethoven":
        return (
            "\n\nReferencia bibliográfica: Beethoven, Sonata para piano en do sostenido menor, op. 27, n.º 2; "
            "I. Adagio sostenuto; II. Allegretto; III. Presto agitato. " if locale == "es" else
            "\n\nBibliographic reference: Beethoven, Piano Sonata in C-sharp minor, Op. 27 No. 2; "
            "I. Adagio sostenuto; II. Allegretto; III. Presto agitato. "
        ) + BEETHOVEN + (
            "\nEsta referencia no aporta ni licencia una partitura o grabación. Estudiar una partitura no equivale a escuchar."
            if locale == "es" else
            "\nThis reference supplies or licenses no score or recording. Score study is not listening."
        )
    if identifier == "elizabethan":
        return (
            "\n\nReferencias bibliográficas: John Dowland, Flow My Tears, The Second Book of Songes, n.º 2 (1600), "
            "canción para voz y laúd: " if locale == "es" else
            "\n\nBibliographic references: John Dowland, Flow My Tears, The Second Book of Songes, no. 2 (1600), "
            "song for voice and lute: "
        ) + DOWLAND + (
            "\nWilliam Byrd, The Earl of Salisbury Pavan, pieza para teclado publicada en Parthenia (1613): "
            if locale == "es" else
            "\nWilliam Byrd, The Earl of Salisbury Pavan, keyboard piece published in Parthenia (1613): "
        ) + BYRD + (
            "\nLa coincidencia de época no demuestra colaboración con Shakespeare. No se aporta ninguna partitura, letra ni grabación."
            if locale == "es" else
            "\nShared chronology does not prove collaboration with Shakespeare. No score, lyrics or recording are supplied."
        )
    return ""


def art_entries():
    return [{
        "id": "michelangelo_"+identifier, "subject": "art_music", "category": "picture_study",
        "title": title, "title_es": title_es, "creator": "Michelangelo", "year": "1508–1512",
        "wiki_title": wiki,
        "image_url": "/catalog/classical-arts/assets/michelangelo_"+identifier+"/"
                     + sha256((ART_DIR / ("michelangelo_"+identifier+".jpg")).read_bytes()).hexdigest()+".jpg",
        "source_image_url": "https://upload.wikimedia.org/wikipedia/commons/"+image,
        "source_image_sha256": ART_INPUT_HASHES[index],
        "asset_sha256": sha256((ART_DIR / ("michelangelo_"+identifier+".jpg")).read_bytes()).hexdigest(),
        "source_url": "https://commons.wikimedia.org/wiki/"+page,
        "description": "A fresco detail, not a photograph of sculpture. Look at the seated figure's posture, the book or scroll, and the surrounding composition. Separate what you see from what you infer.",
        "description_es": "Detalle de un fresco, no fotografía de una escultura. Observa la postura, el libro o rollo y la composición. Distingue lo que ves de lo que infieres.",
        "adult_preview_required": True,
        "content_note": "Historical religious/classical subject matter and decorative artistic nudity; adult preview and explicit selection required. Not devotional assessment.",
        "rights": {
            "status": "public_domain_verified", "evidence_url": "https://commons.wikimedia.org/wiki/"+page,
            "basis": "Commons file-page PD-Art / faithful two-dimensional reproduction; Persian file additionally identifies the Yorck public-domain reproduction collection",
            "scope": "This exact reproduction only; not modern translations, museum images generally, recordings or 3D photographs",
        },
    } for index, (identifier, title, title_es, image, page, wiki) in enumerate(ART)]


def build_art_assets():
    """Small exact-source derivatives are bundled locally, never fetched in a lesson."""
    version = subprocess.check_output(["convert", "-version"], text=True).splitlines()[0]
    ART_DIR.mkdir(parents=True, exist_ok=True)
    for (identifier, *_), expected in zip(ART, ART_INPUT_HASHES, strict=True):
        source = ROOT / "generated-artifacts/classical-arts-verified" / ("michelangelo_"+identifier+".jpg")
        if sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Unverified art source: "+identifier)
        subprocess.run([
            "convert", str(source), "-auto-orient", "-resize", "1200x1600>",
            "-colorspace", "sRGB", "-strip", "-quality", "85",
            str(ART_DIR / ("michelangelo_"+identifier+".jpg")),
        ], check=True, timeout=30)
    (ART_DIR / "provenance.json").write_text(json.dumps({
        "derivation": version+"; EXIF orientation, sRGB, proportional max 1200x1600, stripped metadata, JPEG quality 85; no crop or content edit",
        "assets": art_entries(),
        "scope": "Five exact faithful two-dimensional reproductions; no museum-wide license or 3D photograph claim",
    }, ensure_ascii=False, indent=2)+"\n")


def composer(identifier, name, dates, title, movement, era, forces, biography, notes, source):
    return {
        "id": identifier, "subject": "art_music", "composer": name, "composer_dates": dates,
        "work_title": title, "movement": movement, "era": era, "forces": forces,
        "composer_bio": biography, "listening_notes": notes,
        "stage_notes": {
            "foundations": "If an adult has a lawful source, notice one repeated sound or contrasting part. A spoken original pattern is an alternative, not a performance of this work.",
            "core_mastery": "Identify a repeated idea and one change using a location in the actual source; distinguish a score from a recording.",
            "independent": "Support a formal interpretation with a located feature, an alternative reading and a limitation of the available source. Do not infer influence from chronology alone.",
        },
        "bibliographic_sources": [source],
        "rights_scope": "Original descriptive guidance only. No score, lyrics, recording or modern edition is reproduced or licensed.",
    }


def additions():
    works = [
        composer(
            "beethoven_op27_2_"+str(index), "Ludwig van Beethoven", "1770–1827",
            "Piano Sonata in C-sharp minor, Op. 27 No. 2", movement, "Classical / early nineteenth century",
            "solo piano", "Beethoven's sonata is titled Sonata quasi una fantasia. Treat the score, later nickname and a performance as different kinds of evidence.",
            notes, BEETHOVEN,
        ) for index, movement, notes in [
            (1, "I. Adagio sostenuto",
             "When a lawful recording is actually playing, listen for the persistent triplet accompaniment and a distinct melodic line. In a score, locate those layers instead; do not call that listening. Explain how recurrence can support continuity without requiring every listener to feel the same emotion."),
            (2, "II. Allegretto",
             "Compare this movement's pace and grouping with a located passage from movement I using an adult's source. Notice returning material and contrast; the movement label is a starting clue, not a complete analysis."),
            (3, "III. Presto agitato",
             "Use a short adult-selected section to examine changes in texture and energy. Avoid equating fast playing with better learning or requiring a piano performance. Mark actual locations for each observation."),
        ]
    ]
    works += [
        composer("dowland_flow_my_tears", "John Dowland", "1563–1626", "Flow My Tears",
                 "Song, The Second Book of Songes, no. 2 (1600)", "English Renaissance",
                 "voice and lute; original print also offers a bass part",
                 "Dowland's published songs belong to the musical world around Shakespeare. Shared time and place do not prove collaboration.",
                 "With an actual lawful source, notice how a sung phrase relates to its words and repeated musical material. Without a source, compare the documented printed-song setting with a song embedded in a play. No lyrics or recording are supplied.", DOWLAND),
        composer("byrd_salisbury_pavan", "William Byrd", "c.1540–1623",
                 "The Earl of Salisbury Pavan", "Pavan, in Parthenia (published by 1613)",
                 "English Renaissance / early seventeenth century", "keyboard",
                 "Byrd wrote vocal and keyboard music. This is an instrumental keyboard pathway; historical religious context is descriptive, not required assent.",
                 "With an actual lawful score or recording, locate a phrase and its return or alteration. Compare instrumental organization with Dowland's song only when both sources are present. A chronological overlap is not proof that Byrd set a particular Shakespeare lyric.", BYRD),
    ]
    return works


def update_catalogs():
    for name, key, rows in [
        ("visual_aids.json", "visual_aids", art_entries()),
        ("composer_catalog.json", "composer_works", additions()),
    ]:
        path = ROOT / "homeschool-api/data" / name
        data = json.loads(path.read_text())
        existing = {item["id"]: item for item in data[key]}
        existing.update({item["id"]: item for item in rows})
        data[key] = list(existing.values())
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    update_catalogs()
