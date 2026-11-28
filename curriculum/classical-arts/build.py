"""Original authoring -> existing factory manifest + explicit student projection.

Teacher models are required local inputs, never committed to this public
authoring adapter or copied to its student projection.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sys

from units import UNITS
from spanish import WEEKS
from verify_sources import verify, ROOT
from catalog_additions import art_entries, build_art_assets, music_reference, update_catalogs

FACTORY = ROOT / "curriculum/factory"
sys.path.insert(0, str(FACTORY))
from boundary import contract as c
from fixture import example, NOW
from schema import GATES, USES

OUT = ROOT / "generated-artifacts/curriculum-factory/classical-arts-authoring"
PRIVATE = ROOT / "generated-artifacts/classical-arts-private/teacher_models.json"
PUBLIC = ROOT / "homeschool-api/data/curriculum/classical-arts.json"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
PAIRED = {
    ("shakespeare-songs", 3): ["greenwood"],
    ("lamb-midsummer", 3): ["midsummer"],
    ("everyman-bridge", 2): ["merchant"],
    ("caesar-plutarch", 2): ["north"], ("caesar-plutarch", 3): ["north"],
    ("macbeth-deliberation", 3): ["merchant", "caesar"],
    ("tempest-release", 3): ["merchant"],
    ("elizabethan-music", 1): ["greenwood"],
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def asset(filename, raw):
    (OUT / filename).write_bytes(raw)
    return {"path": filename, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def rehearsal(source):
    """Keep source order and exact contiguous speech slices, including repeats."""
    text = source["text"]
    pattern = re.compile(r"(?m)^[ ]*([A-Z][A-Z '.-]{1,35})\.[ ]*(?:\n|(?=\S))")
    matches = list(pattern.finditer(text))
    result = []

    def add_speech(speaker, speech):
        run = []

        def flush():
            value = "".join(run).strip()
            if value:
                if value not in text:
                    raise ValueError("A rehearsal cue is not an exact contiguous source slice")
                result.append({"speaker": speaker, "text": value})
            run.clear()

        for line in speech.splitlines(keepends=True):
            if re.match(r"^\s*(?:Enter\s|Re-enter\s|Exit\b|Exeunt\b|\[|Burden\b|\(Burden\b|SONG\b)", line):
                flush()
                continue
            stage = re.search(r"\s{3,}(?:Exit|Exeunt)\b", line)
            if stage:
                run.append(line[:stage.start()])
                flush()
            else:
                run.append(line)
        flush()

    if not matches:
        add_speech("Reader", text)
    for index, match in enumerate(matches):
        end = matches[index+1].start() if index+1 < len(matches) else len(text)
        add_speech(match.group(1).strip(), text[match.end():end])
    return result


def localized(row, language):
    objective, teaching, discussion, independent, transfer = row
    es = language == "es"
    return {
        "title": objective, "objective": objective,
        "steps": [
            {"label": "Atención y lectura" if es else "Attention and reading", "instruction": teaching},
            {"label": "Diálogo" if es else "Discussion", "instruction": discussion},
            {"label": "Narración y práctica" if es else "Narration and practice",
             "instruction": ("Elige una parte, narra con tus palabras y vuelve al texto para comprobar. "
                             "Puedes hablar, escribir, señalar o trabajar con un escribiente. "
                             "Revelar las líneas es apoyo, no evidencia independiente."
                             if es else
                             "Choose a short part, narrate in your own words, and check against the source. "
                             "Speak, type, point or use a scribe. Revealed lines are support, not independent evidence.")},
        ],
        "assessments": [
            {"kind": "independent", "prompt": independent},
            {"kind": "delayed", "prompt": (
                "Dentro de 7–14 días, vuelve a responder sin modelo ni líneas reveladas: "
                if es else "After 7–14 days, revisit without a model or revealed role lines: ") + independent},
            {"kind": "transfer", "prompt": transfer},
        ],
        "support": {
            "guided": ("Divide el pasaje en partes pequeñas; explica vocabulario y registra los apoyos."
                       if es else "Chunk the passage, explain vocabulary, and record any support used."),
            "independent": ("Retira el modelo después de estudiar; conserva solo el apoyo de acceso acordado."
                            if es else "Remove the model after study; retain agreed access supports only."),
            "extension": ("Considera otra interpretación y señala qué evidencia adicional necesitarías."
                          if es else "Consider a counterreading and identify the additional evidence it would need."),
        },
    }


def build():
    build_art_assets()
    sources = verify()
    models = json.loads(PRIVATE.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    seed = example()
    bundle = deepcopy(seed)
    # The existing development factory requires this boundary constant even for
    # substantive authoring; it cannot confer institutional approval/activation.
    bundle.update(fixture_only=True, sources=[], objectives=[], lessons=[], units=[],
                  evidence=[], gates=[])
    public = {"release_id": "bede-classical-arts", "units": []}
    source_records = {}

    def register(source):
        if source["id"] in source_records:
            return source_records[source["id"]]
        original = source["rights"] == "original"
        entry = {
            "id": source["id"], "version": 1, "title": source["title"],
            "creator_editor_translator": "Bede" if original else (
                "Charles and Mary Lamb" if source["id"] == "lamb" else
                "Plutarch; Amyot; Sir Thomas North; C. F. Tucker Brooke (1909 editor)"
                if source["id"] == "north" else "William Shakespeare"),
            "edition": source["locator"], "url": source["url"],
            "retrieved_at": NOW, "asset": asset(source["id"]+".txt", source["text"].encode()),
            "rights": source["rights"], "territory": "United States; local law applies elsewhere",
            "license": "Bede proprietary original guidance" if original else "Underlying public-domain literary text; exact-source evidence retained",
            "attribution": source["title"]+"; "+source["locator"],
            "notices": ["Copyright 2026 Agnus Dei Technologies, LLC. All Rights Reserved."] if original else
                       ["No modern translation, image, score or recording is included."],
            "rights_evidence_refs": [json.dumps(source["verification_evidence"], ensure_ascii=False)],
            "permissions": {use: {"decision": "denied" if use == "training" else "allowed",
                                  "evidence_refs": ["Original text" if original else "Verified exact-source evidence"]}
                            for use in USES},
            "licensed_pathway_ref": None,
        }
        bundle["sources"].append(entry)
        source_records[source["id"]] = entry
        return entry

    for unit in UNITS:
        if len(unit["weeks"]) != 3 or len(WEEKS[unit["id"]]) != 3 or len(models[unit["id"]]) != 3:
            raise ValueError("Every adopted unit needs three complete weeks in both languages and private models")
        # The guide explicitly distinguishes its original procedures from the
        # adult's separately obtained source. No unverified Everyman text,
        # Michelangelo image, score or recording is inserted here.
        for identifier in set(unit["sources"]) - sources.keys():
            text = unit["note"]+"\n\n"+"\n\n".join(row[1] for row in unit["weeks"])
            sources[identifier] = {
                "id": identifier, "title": unit["title"]+" — original Bede guide",
                "url": ("https://archive.org/details/everymanwithothe00rhys" if identifier == "everyman" else
                        "https://agnusdei.ai/"),
                "locator": "Original guide, all three weekly procedures; external works are adult-provided, not reproduced",
                "text": text, "language": "en", "rights": "original",
                "text_sha256": sha256(text.encode()).hexdigest(),
                "verification_evidence": {"method": "Original Bede instruction; no third-party work reproduced",
                                          "scope": "Not a verified transcription, image, score or audio asset"},
            }
            if identifier == "michelangelo":
                sources[identifier]["url"] = art_entries()[0]["source_url"]
                sources[identifier]["text"] += (
                    "\n\nAdult preview: the following exact fresco reproductions include decorative artistic nudity. "
                    "Review each file page before selecting this unit. No reproduction is a 3D sculpture photograph.\n"
                    + "\n".join(item["title"]+": "+item["source_url"] for item in art_entries())
                )
                sources[identifier]["text_sha256"] = sha256(sources[identifier]["text"].encode()).hexdigest()
            if music_reference(identifier):
                sources[identifier]["text"] += music_reference(identifier)
                sources[identifier]["text_sha256"] = sha256(sources[identifier]["text"].encode()).hexdigest()
        original = {
            "id": unit["id"]+"-instruction", "title": unit["title"]+" — Bede-original teaching",
            "url": "https://agnusdei.ai/", "locator": "Three authored weekly instruction records",
            "text": json.dumps({"en": unit["weeks"], "es": WEEKS[unit["id"]]}, ensure_ascii=False),
            "rights": "original", "verification_evidence": {"method": "Bede-original authoring"},
        }
        original_record = register(original)
        lessons, public_lessons = [], []
        for index, row in enumerate(unit["weeks"], 1):
            source = sources[unit["sources"][index-1]]
            source_record = register(source)
            companion_sources = [sources[key] for key in PAIRED.get((unit["id"], index), [])]
            objective = deepcopy(seed["objectives"][0])
            objective.update(id=f"{unit['id']}-w{index}-objective", statement=row[0],
                             skill_ids=[], exercises_no_tracked_skill=True,
                             skill_mapping_rationale="Bounded literary/arts practice; no validated diagnostic skill or mastery claim.",
                             success_criteria="A relevant claim or observation, located evidence, a reason and an acknowledged limit.")
            bundle["objectives"].append(objective)
            lesson = deepcopy(seed["lessons"][0])
            lesson.update(
                id=f"{unit['id']}-w{index}", title=unit["title"]+f" — week {index}",
                subject=unit["subjects"][0], stage="3-5" if unit["min_grade"] < 6 else "6-8",
                objective_ids=[objective["id"]], skill_ids=[], exercises_no_tracked_skill=True,
                skill_mapping_rationale=objective["skill_mapping_rationale"],
                prerequisites=[], entry_evidence="Adult checks passage access, vocabulary, readiness and content note; no assumed prior exposure.",
                anti_twaddle=True,
                source_refs=[
                    {"source": c.ref(source_record), "locator": source["locator"], "uses": ["copy", "storage"],
                     "verbatim": source["rights"] != "original"},
                    {"source": c.ref(original_record), "locator": original["locator"], "uses": ["copy", "storage"], "verbatim": False},
                ],
            )
            lesson["source_refs"].extend(
                {"source": c.ref(register(companion)), "locator": companion["locator"],
                 "uses": ["copy", "storage", "retrieval", "model_processing", "tts", "distribution"],
                 "verbatim": companion["rights"] != "original"}
                for companion in companion_sources
            )
            for usage in lesson["source_refs"]:
                usage["uses"] = ["copy", "storage", "retrieval", "model_processing", "tts", "distribution"]
            instructions = [
                ("explicit_teaching", row[1]),
                ("worked_example", models[unit["id"]][index-1]),
                ("seminar", row[2]),
                ("studio", "Mark or draw a located observation; explain which part is inference."),
                ("practice", row[3]),
                ("exit", row[4]),
            ]
            lesson["steps"] = [
                {"mode": mode, "minutes": 3, "materials": ["Verified source or clearly scoped original guide", "Paper or keyboard"],
                 "instruction": instruction} for mode, instruction in instructions
            ]
            lesson["assessments"] = [
                {
                    "id": kind, "objective_id": objective["id"], "kind": kind,
                    "delay_days": 7 if kind == "delayed" else 0,
                    "prompt": row[2] if kind == "guided" else row[4] if kind == "transfer" else row[3],
                    "key_rubric": models[unit["id"]][index-1]+
                                  " Accept other defensible interpretations supported by the actual source. "
                                  "Do not accept unsupported claims or an answer copied from this model.",
                    "supports": ["Typed, spoken, pointing or scribed response", "Large print", "Agreed vocabulary access"],
                    "prompt_rescue_record": "Record actual prompt/reveal support separately; never relabel guided work as independent.",
                    "assessor_role": "Responsible adult", "success_criteria": objective["success_criteria"],
                } for kind in ("guided", "independent", "delayed", "transfer")
            ]
            lesson["access"].update(
                construct="Source-grounded interpretation, not memory span, accent, handwriting, faith or emotion.",
                supports=["Chunking", "Large print", "Vocabulary preview", "Partner reading"],
                alternative_response="Read silently and type, annotate, point, dictate or use a scribe; performing is optional.",
                privacy="No new recording or personal disclosure; learner practice stays in existing protected session routes.",
                retention_deletion="No rehearsal recording; clear transient draft responses when leaving this activity.",
            )
            lesson["safety"].update(
                hazards=[unit["note"]], supervision="Adult previews the exact passage and chooses the participation route.",
                stop_escalation="Stop distressing material and consult the adult; do not enact violence or target real people.",
                safer_alternative="Use a neutral original example or annotation; declare any reduced source coverage.",
            )
            for output in lesson["outputs"]:
                output["attribution_source_ids"] = [source_record["id"], original_record["id"],
                                                     *(companion["id"] for companion in companion_sources)]
            lesson["status"] = "draft"  # A successful factory build cannot self-approve.
            bundle["lessons"].append(lesson)
            lessons.append(c.ref(lesson))
            public_lessons.append({
                "week": index, "source": deepcopy(source),
                "companion_sources": deepcopy(companion_sources),
                "visual_previews": art_entries() if unit["id"] == "michelangelo-looking" else [],
                "localizations": {"en": localized(row, "en"), "es": localized(WEEKS[unit["id"]][index-1], "es")},
                "rehearsal": rehearsal(source) if source["rights"] != "original" else [],
            })
            if source["rights"] == "original":
                spanish_source = deepcopy(source)
                spanish_source.update(
                    title=unit["title_es"]+" — guía original de Bede",
                    text=unit["note_es"]+"\n\n"+"\n\n".join(item[1] for item in WEEKS[unit["id"]]),
                    language="es",
                )
                spanish_source["text_sha256"] = sha256(spanish_source["text"].encode()).hexdigest()
                if music_reference(source["id"]):
                    spanish_source["text"] += music_reference(source["id"], "es")
                    spanish_source["text_sha256"] = sha256(spanish_source["text"].encode()).hexdigest()
                if source["id"] == "michelangelo":
                    spanish_source["text"] += (
                        "\n\nRevisión adulta: estas reproducciones exactas contienen desnudos artísticos decorativos. "
                        "Revisa cada página antes de elegir la unidad.\n"
                        + "\n".join(item["title_es"]+": "+item["source_url"] for item in art_entries())
                    )
                    spanish_source["text_sha256"] = sha256(spanish_source["text"].encode()).hexdigest()
                public_lessons[-1]["source_es"] = spanish_source
        factory_unit = deepcopy(seed["units"][0])
        factory_unit.update(
            id=unit["id"], title=unit["title"], lesson_refs=lessons,
            objective_ids=[row["id"] for row in bundle["objectives"] if row["id"].startswith(unit["id"]+"-w")],
            culminating_task=unit["weeks"][-1][4],
            synthesis_reteaching="Adult examines source-specific evidence and adjusts access; no automatic mastery or credit.",
            adult_minutes=15,
        )
        bundle["units"].append(factory_unit)
        public["units"].append({
            "id": unit["id"], "min_grade": unit["min_grade"], "subjects": unit["subjects"],
            "weeks": 3, "lessons": public_lessons,
            "localizations": {
                "en": {"title": unit["title"], "summary": unit["weeks"][0][0], "content_note": unit["note"]},
                "es": {"title": unit["title_es"], "summary": WEEKS[unit["id"]][0][0], "content_note": unit["note_es"]},
            },
        })
    grade = deepcopy(seed["grade"])
    grade.update(
        id="cross-grade-classical-arts", grade=12, unit_refs=[c.ref(u) for u in bundle["units"]],
        domains=["Bounded cross-grade literature, art and music only"],
        calendar_weeks=36, learner_minutes_week=18, adult_minutes_week=15,
        coverage_decisions=["12 bounded three-week units, not a grade/year replacement; minimum grade and adult preview apply.",
                            "Everyman, art images, scores and recordings remain adult-provided; original guides only."],
        completion_criteria=["Evidence-grounded responses in each adopted bounded unit; not whole-grade completion."],
        transition_evidence="No effectiveness, retention, credit or readiness for another course is inferred.",
        complete=False,
    )
    bundle["grade"] = grade
    bundle["gates"] = [{"kind": kind, "target": c.ref(grade), "state": "pending", "receipt_ref": None} for kind in GATES]
    ledger = deepcopy(seed["ledger"])
    ledger.update(
        task_ref="classical-arts-source-bound", workspace="isolated-classical-arts",
        started_at=NOW, updated_at=NOW,
        inputs=[source["asset"] for source in bundle["sources"]],
        outputs=[], artifacts=[], blockers=["Separate exact-version review; no production activation"],
        validations=[{"command": "existing factory and exact-source verifier", "result": "not_run",
                      "evidence_ref": "pending factory output"}],
    )
    ledger["idempotency_key"] = c.idempotency(ledger)
    bundle["ledger"] = ledger
    (OUT / "bundle.json").write_bytes(c.canonical(bundle))
    # Explicit projection only; no source/lesson object from the private bundle
    # is spread or serialized into this student-facing result.
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.write_bytes(canonical(public)+b"\n")
    update_catalogs()
    print(json.dumps({
        "units": len(public["units"]), "weeks": len(bundle["lessons"]),
        "manifest": str(OUT / "bundle.json"),
        "student_projection_sha256": sha256(PUBLIC.read_bytes()).hexdigest(),
    }))


if __name__ == "__main__":
    build()
