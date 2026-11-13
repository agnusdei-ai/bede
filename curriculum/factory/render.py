"""Deterministic, nonexecutable allowlisted projections. Never interpret markup."""
import hashlib
import html
import io
import json
import zipfile

from boundary import contract as c

LIMITATIONS = [
    "DEVELOPMENT DRAFT — NOT APPROVED FOR STUDENT USE.",
    "Structure, hashes, references and declared rights are mechanically checked only.",
    "No mathematical correctness, primary-source truth, legal clearance, accessibility "
    "effectiveness or learning outcomes are certified by these checks.",
    "Independent academic evidence and authenticated human review remain separate gates.",
    "No model inference, training, learner records, publication or activation.",
    "Licensed sources require a separately reviewed pathway; verbatim requires verified public domain.",
    "Original source bytes are evidence, not inserted as instructional verbatim text.",
]


def readable(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def block(title, values):
    # Only text nodes; no source URL is used as an href/src and no external assets.
    return "<section><h2>" + html.escape(title) + "</h2>" + "".join(
        "<p>" + html.escape(str(v), quote=True) + "</p>" for v in values) + "</section>"


def page(bundle, teacher):
    body = block("Review-only draft", LIMITATIONS[:2])
    objectives = {o["id"]: o for o in bundle["objectives"]}
    sources = {s["id"]: s for s in bundle["sources"]}
    for lesson in bundle["lessons"]:
        body += block(lesson["title"], [
            f'Lesson {lesson["id"]}, version {lesson["version"]}',
            *(objectives[o]["statement"] for o in lesson["objective_ids"]),
            lesson["entry_evidence"],
        ])
        # Worked examples may contain a solution; keep those on the teacher side.
        for step in lesson["steps"]:
            if teacher or step["mode"] not in ("worked_example",):
                body += block(step["mode"], [
                    step["instruction"], f'{step["minutes"]} minutes',
                    *step["materials"],
                ])
        for a in lesson["assessments"]:
            body += block(a["kind"], [a["prompt"], *a["supports"],
                                      a["success_criteria"]])
            if teacher:
                body += block("Teacher key and evidence collection", [
                    a["key_rubric"], a["prompt_rescue_record"], a["assessor_role"],
                    f'Delay: {a["delay_days"]} days',
                ])
        body += block("Access", [lesson["access"]["construct"], *lesson["access"]["supports"],
                                    lesson["access"]["alternative_response"]])
        body += block("Safety", [*lesson["safety"]["hazards"],
                                    lesson["safety"]["supervision"],
                                    lesson["safety"]["stop_escalation"],
                                    lesson["safety"]["safer_alternative"]])
        if teacher:
            body += block("Privacy and retention", [lesson["access"]["privacy"],
                                                     lesson["access"]["retention_deletion"]])
        for usage in lesson["source_refs"]:
            s = sources[usage["source"]["id"]]
            body += block("Source attribution", [
                s["title"], s["creator_editor_translator"], s["edition"], s["url"],
                usage["locator"], s["asset"]["sha256"], s["license"],
                s["attribution"], *s["notices"],
            ])
    if teacher:
        for unit in bundle["units"]:
            body += block(unit["title"], [unit["culminating_task"], unit["synthesis_reteaching"],
                                              f'Adult workload: {unit["adult_minutes"]} minutes'])
    title = "Teacher review packet" if teacher else "Student-format review packet"
    return (
        '<!doctype html><html lang="en-US"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>"
        "body{font:18px/1.5 Georgia,serif;max-width:48rem;margin:2rem auto;padding:0 1rem;"
        "color:#171717;background:white}p{white-space:pre-wrap;overflow-wrap:anywhere}"
        "section{margin-bottom:1.5rem}h2{break-after:avoid}"
        "@media print{body{font-size:12pt;max-width:none;margin:0}section{break-inside:auto}"
        "@page{margin:18mm}}</style></head><body>"
        f"<h1>{title}</h1>{body}</body></html>"
    ).encode()


def artifacts(bundle, fingerprint, tool_manifest=None):
    coverage = {
        "complete": False, "grade": bundle["grade"]["grade"],
        "objectives": {o["id"]: {
            "lessons": [l["id"] for l in bundle["lessons"] if o["id"] in l["objective_ids"]],
            "assessment_kinds": sorted({a["kind"] for l in bundle["lessons"]
                                       for a in l["assessments"] if a["objective_id"] == o["id"]}),
        } for o in bundle["objectives"]},
        "noncoverage": bundle["grade"]["coverage_decisions"],
        "learning_evidence": "None collected; coverage is structural only.",
    }
    files = {
        "source.json": readable(c.export(bundle)),
        "student.html": page(bundle, False), "teacher.html": page(bundle, True),
        "coverage.json": readable(coverage),
        "evidence.json": readable(dict(
            fingerprint=fingerprint, independent_evidence=bundle["evidence"],
            gates=bundle["gates"], validations=[
                dict(check="approved specification contract", result="pass"),
                dict(check="math/source truth/legal/human/student readiness", result="not_verified")],
            usage=dict(tokens=None, cost=None, measurement_source=None),
            authorized_spend=0, human_review="pending",
        )),
        "LIMITATIONS.txt": ("\n".join(LIMITATIONS) + "\n").encode(),
        "CHANGELOG.txt": (
            "Draft content-addressed build " + fingerprint +
            "\nImmutable build; predecessor/stale history is in the development ledger.\n"
            "No human approval, pilot, publication, activation or complete grade.\n").encode(),
    }
    checksums = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files["build.json"] = readable(dict(
        fingerprint=fingerprint, status="review_only", outputs=checksums,
        schema=bundle["schema_version"], human_approval=False,
        tools=tool_manifest,
    ))
    files["checksums.sha256"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100600 << 16
            info.create_system = 3
            z.writestr(info, data)
    files["review.zip"] = archive.getvalue()
    return files
