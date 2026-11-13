"""Reuse the actual curriculum curation rules, not a substitute safety/skill gate."""
import sys

from boundary import ROOT, Error, contract as c


def validate_bundle(bundle, base):
    c.check(bundle, base)
    api = str(ROOT / "homeschool-api")
    if api not in sys.path:
        sys.path.insert(0, api)
    from models.schemas import GradeStage, Subject
    from services.content_curation import ContentCandidate, curate_all, FAITH_METRIC_MARKERS

    # Original service reserves these in extra_fields; a manifest can also put
    # them in free text. Neither route may introduce a spiritual scoring task.
    if any(marker in c.canonical(bundle).decode().lower() for marker in FAITH_METRIC_MARKERS):
        raise Error("Existing content curation reserved faith metric requires resolution")

    candidates = [
        ContentCandidate(
            id=lesson["id"], title=lesson["title"], subject=Subject(lesson["subject"]),
            source=lesson["source_refs"][0]["source"]["id"],
            body=c.canonical(lesson).decode(),
            skills=tuple(lesson["skill_ids"]), stages=(GradeStage(lesson["stage"]),),
            exercises_no_tracked_skill=lesson["exercises_no_tracked_skill"],
        ) for lesson in bundle["lessons"]
    ]
    # Warnings also stop this development build for explicit disposition, rather
    # than allowing an unresolved activity hazard into even a review packet.
    findings = [f"{v.candidate_id}:{f.rule}" for v in curate_all(candidates) for f in v.findings]
    if findings:
        raise Error("Existing content curation requires resolution: " + ", ".join(findings))
