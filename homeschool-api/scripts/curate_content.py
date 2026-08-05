"""Run the constitutional curation gate over a batch of proposed content.

    python homeschool-api/scripts/curate_content.py submission.json

Exits 0 if every candidate passes, 1 otherwise, so it can be dropped into a
pre-commit hook or a CI step for a content PR.

The submission file is a JSON list of candidates:

    [
      {
        "id": "y4-parables",
        "title": "The Parables of Jesus",
        "subject": "scripture",
        "source": "checked against the KJV, public domain",
        "body": "Narrative retelling with discussion questions.",
        "skills": [],
        "exercises_no_tracked_skill": true
      }
    ]

`subject` must be a real Subject enum value; `stages` (optional) uses the
GradeStage values "K-2" / "3-5" / "6-8". Anything else in the object is
treated as an extra field and scanned — which is deliberate, since that is
where a smuggled faith metric would appear.

See services/content_curation.py for what each rule checks and why, and
docs/CONTENT_CONTRIBUTING.md for the sourcing standard this enforces.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# services.content_curation reaches services.diagnostic, which reaches
# core.config — the same fail-fast-at-import convention tests/conftest.py
# works around. Nothing here connects to anything.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 32)
os.environ.setdefault("MASTER_SECRET", "test-master-secret-" + "y" * 32)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")

from models.schemas import GradeStage, Subject  # noqa: E402
from services.content_curation import ContentCandidate, curate_all  # noqa: E402

_KNOWN_FIELDS = {
    "id", "title", "subject", "source", "verbatim_text", "public_domain",
    "anti_twaddle", "stages", "body", "skills", "exercises_no_tracked_skill",
}


def build_candidate(raw: dict) -> ContentCandidate:
    try:
        subject = Subject(raw["subject"])
    except (KeyError, ValueError) as exc:
        raise SystemExit(
            f"Entry {raw.get('id', '<no id>')!r}: 'subject' must be one of "
            f"{', '.join(s.value for s in Subject)} ({exc})"
        )
    try:
        stages = tuple(GradeStage(s) for s in raw.get("stages", ()))
    except ValueError as exc:
        raise SystemExit(
            f"Entry {raw.get('id', '<no id>')!r}: 'stages' must use "
            f"{', '.join(s.value for s in GradeStage)} ({exc})"
        )

    return ContentCandidate(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        subject=subject,
        source=raw.get("source"),
        verbatim_text=raw.get("verbatim_text"),
        public_domain=bool(raw.get("public_domain", False)),
        anti_twaddle=raw.get("anti_twaddle"),
        stages=stages,
        body=str(raw.get("body", "")),
        skills=tuple(raw.get("skills", ())),
        exercises_no_tracked_skill=bool(raw.get("exercises_no_tracked_skill", False)),
        # Everything unrecognized is kept and scanned rather than dropped.
        extra_fields={k: v for k, v in raw.items() if k not in _KNOWN_FIELDS},
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(__doc__ or "")
        return 2

    path = Path(argv[1])
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        sys.stderr.write(f"No such file: {path}\n")
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"{path} is not valid JSON: {exc}\n")
        return 2

    if not isinstance(raw, list):
        sys.stderr.write(f"{path} must contain a JSON list of candidates.\n")
        return 2

    verdicts = curate_all([build_candidate(entry) for entry in raw])

    blocked = 0
    for verdict in verdicts:
        if verdict.accepted and not verdict.findings:
            print(f"  [ok  ] {verdict.candidate_id}")
            continue
        if verdict.accepted:
            print(f"  [warn] {verdict.candidate_id}")
        else:
            blocked += 1
            print(f"  [BLOCK] {verdict.candidate_id}")
        for finding in verdict.findings:
            marker = "!" if finding.severity == "block" else "-"
            print(f"      {marker} {finding.rule}: {finding.message}")

    print()
    if blocked:
        print(f"{blocked} of {len(verdicts)} candidate(s) blocked.")
        return 1
    print(
        f"All {len(verdicts)} candidate(s) pass the mechanical checks. "
        "That is not the same as being good content — a human still reviews it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
