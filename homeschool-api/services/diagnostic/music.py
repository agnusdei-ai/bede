"""
Music-knowledge mastery — what a child has come to KNOW about the music
they have listened to, and deliberately never how they RESPONDED to it.

Reuses MasteryProfile/DiagnosticEvidenceLog exactly as
services/diagnostic/{composition,phonics,literacy,language_exposure}.py do
(subject_area="music_knowledge" — MasteryProfile's composite PK was
designed for this kind of extension, so this is a new row and not a new
table), with the same simple calibrated blend rather than the full
CDM/IRT/KST pipeline `skill_map.py` carries for mathematics.

## The line this module is built on, and why it is not negotiable

Mater Amabilis composer study is the contemplation of something beautiful:
`_SUBJECT_CONTEXT[Subject.art_music]` says "aesthetic sensibility and
appreciation, not technical critique". So there are two quite different
things one could measure here, and only one of them is ours to touch.

**Knowledge is measurable and is what this module holds.** That a largo is
slow, that a concerto sets one soloist against an ensemble, that Vivaldi
worked in Venice, that the Baroque ran to about 1750 — these are facts. A
child either has them or is still gathering them, and a parent deciding
what to teach next is genuinely helped by knowing which.

**A child's response is NOT measurable and must never appear here.**
Whether a child found a piece beautiful, whether they loved it, how deeply
they felt it, whether they would choose it again — none of that is Bede's
to score, and a number standing for it would be false precision about the
one part of this subject that belongs entirely to the child. This is the
same refusal CLAUDE.md already makes twice: a child's spiritual engagement
is governed qualitatively and never counted, and `_character_virtues_note`
has no `record_virtue_evidence` tool and must never grow one. Aesthetic
response belongs in that company. `FORBIDDEN_DOMAIN_SUBSTRINGS` below
states it in code so adding such a domain fails a test rather than passing
a review, and `tests/diagnostic/test_music.py` is where that bites.

The practical consequence worth stating plainly: this profile can tell a
parent their child reliably hears which instrument carries a tune, and it
can never tell them whether their child likes Bach. The second question is
a real and better one. It is answered by asking the child.

## Why the domains walk in order rather than sorting by probability

`phonics.py` walks its DOMAINS in a fixed developmental sequence because a
child still decoding is not helped by being pointed at a later skill;
`language_exposure.py` sorts by probability because its six languages have
no prerequisite order. Music is the first kind. Hearing that a piece is
fast or slow precedes naming its form, which precedes placing it in a
period, which precedes connecting it to the history around it — and that is
not an opinion here, it is the same progression each catalogue entry's own
`stage_notes` already encodes for K-2, 3-5 and 6-8. So `next_steps` walks
DOMAINS and reports the first unsecured ones.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.diagnostic.mastery import calibration_weight_for, classify_level

log = logging.getLogger(__name__)

MasteryVector = dict[str, float]

SUBJECT_AREA = "music_knowledge"

# Evidence here is sparser than any other engine's: one listening lesson a
# week inside one subject, at most one check-in per session. Three
# observations is therefore roughly three weeks of Art & Music, and a
# family will honestly see "still getting to know your learner" for the
# first fortnight or so. Kept at phonics'/language_exposure's threshold
# rather than lowered to flatter the card — the same placeholder spirit as
# mastery.CALIBRATION_THRESHOLD's own "[to verify final N]" flag.
CALIBRATION_THRESHOLD = 3

# Same outcome vocabulary and scores as phonics/language_exposure/
# record_skill_evidence, for consistency across the codebase.
_OUTCOME_SCORES: dict[str, float] = {
    "correct": 1.0,
    "partial": 0.65,
    "hint_dependent": 0.35,
    "incorrect": 0.0,
}

#: Developmental order — see the module docstring. Concrete and sensory
#: first, historical abstraction last, matching each catalogue entry's own
#: stage_notes rather than a second opinion about sequence.
DOMAINS: tuple[str, ...] = (
    "musical_elements",
    "instrumentation",
    "composer_knowledge",
    "form",
    "period_placement",
    "historical_connection",
)

DOMAIN_LABELS: dict[str, str] = {
    "musical_elements": "Tempo, dynamics and texture",
    "instrumentation": "Hearing the instruments",
    "composer_knowledge": "Who wrote it, and when",
    "form": "How the piece is built",
    "period_placement": "Placing it in its period",
    "historical_connection": "Connecting it to its time",
}

#: Bede-facing description of what each domain actually looks like in a
#: listening lesson — threaded into the prompt so a check-in is recorded
#: against the thing that really happened rather than the nearest label.
DOMAIN_CHECKIN_HINTS: dict[str, str] = {
    "musical_elements": (
        "Noticing and naming what the sound is doing — fast or slow, loud or soft, "
        "smooth or plucked, one line or many at once."
    ),
    "instrumentation": (
        "Hearing which instruments are playing, and which one carries the tune."
    ),
    "composer_knowledge": (
        "Recalling who wrote the piece, roughly when they lived, and where they worked."
    ),
    "form": (
        "Recognising how the piece is put together — a repeating theme, a contrast between "
        "sections, a soloist answered by the group."
    ),
    "period_placement": (
        "Placing a work in its musical period and giving a real reason from the sound itself, "
        "not a guess."
    ),
    "historical_connection": (
        "Connecting a work to what was happening around it, or to something already met in "
        "History, Saints, or Art."
    ),
}

#: A domain whose name contains any of these is refused, because it would
#: be a score of the child's own response rather than of anything they
#: know. See the module docstring — this is the code half of that refusal,
#: and a test scans DOMAINS against it.
FORBIDDEN_DOMAIN_SUBSTRINGS: frozenset[str] = frozenset({
    "enjoy", "prefer", "taste", "favourite", "favorite", "like",
    "emotion", "feeling", "appreciat", "engage", "devotion", "love",
    "beauty", "beautiful", "reaction", "response",
})


def new_vector() -> MasteryVector:
    """Cold start: flat 0.5 across every domain. Weighting toward any one of
    them would presume something about this child before a single lesson has
    been observed."""
    return {domain: 0.5 for domain in DOMAINS}


@dataclass
class MusicUpdate:
    domain: str
    prior: float
    posterior: float
    observed_at: str


def apply_evidence(
    vector: MasteryVector,
    domain: str,
    outcome: str,
    calibration_weight: float = 1.0,
) -> tuple[MasteryVector, list[MusicUpdate]]:
    """
    One check-in's worth of evidence for exactly one domain — the same
    single-domain-per-call shape as phonics/language_exposure, because one
    listening moment is evidence about one thing and not about all six.
    Same blend as every sibling engine: prior + weight*(observed-prior),
    clamped to [0,1]. An unrecognised domain or outcome is a true no-op and
    never raises, so hallucinated model output cannot corrupt a vector.
    """
    if domain not in DOMAINS or outcome not in _OUTCOME_SCORES:
        return dict(vector), []

    observed = _OUTCOME_SCORES[outcome]
    prior = vector.get(domain, 0.5)
    blended = max(0.0, min(1.0, prior + calibration_weight * (observed - prior)))

    updated = dict(vector)
    updated[domain] = blended
    return updated, [MusicUpdate(
        domain=domain, prior=prior, posterior=blended,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )]


def build_summary_view(
    vector: MasteryVector,
    student_name: str,
    evidence_count: int,
    updated_at: str,
) -> dict:
    """MasteryProfileSummary-shaped dict — same contract as every sibling
    engine's build_summary_view. next_steps walks DOMAINS in developmental
    order (phonics' approach) rather than sorting by probability, so a child
    still learning to hear fast from slow is never pointed at historical
    connection however low that number happens to be."""
    domains = []
    gaps = []
    for domain in DOMAINS:
        probability = vector.get(domain, 0.5)
        level = classify_level(probability)
        label = DOMAIN_LABELS[domain]
        skill_view = {
            "skill_id": f"{SUBJECT_AREA}.{domain}",
            "label": label,
            "domain": label,
            "grade_band": "",
            "probability": probability,
            "level": level,
        }
        domains.append({
            "domain": label,
            "average_probability": probability,
            "level": level,
            "skills": [skill_view],
        })
        if level == "gap":
            gaps.append(skill_view)

    next_steps = [
        d["skills"][0] for d in domains if d["skills"][0]["level"] != "secure"
    ][:3]

    return {
        "student_name": student_name,
        "subject_area": SUBJECT_AREA,
        "evidence_count": evidence_count,
        "calibration": evidence_count < CALIBRATION_THRESHOLD,
        "domains": domains,
        "gaps": gaps,
        "next_steps": next_steps,
        "updated_at": updated_at,
    }


async def process_evidence(db, student_name: str, domain: str, outcome: str) -> Optional[MasteryVector]:
    """
    Persistence-backed entry point — mirrors language_exposure/phonics
    process_evidence's load/update/store shape exactly, against
    MasteryProfile(subject_area="music_knowledge"). Called from
    ai_service.py's _record_music_evidence. Best-effort: every exception is
    caught and logged, never raised, so a diagnostic hiccup never breaks the
    child's tutoring turn.
    """
    from sqlalchemy import select

    from core import student_keys
    from core.database import MasteryProfile
    from core.encryption import decrypt_json, encrypt_json, student_aad

    row = None
    vector_is_cold_start = False
    aad = student_aad("mastery_profiles", "profile_enc", student_name, SUBJECT_AREA)

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == SUBJECT_AREA,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            vector = new_vector()
            vector_is_cold_start = True
        else:
            vector = decrypt_json(
                row.profile_enc, aad, await student_keys.get_existing(db, student_name),
            )
    except Exception as exc:
        log.warning("Music mastery load failed for %s, treating as cold-start: %s", student_name, exc)
        vector = new_vector()
        vector_is_cold_start = True

    evidence_count_before = 0 if vector_is_cold_start else row.evidence_count
    updated_vector, updates = apply_evidence(
        vector, domain, outcome,
        calibration_weight=calibration_weight_for(evidence_count_before, CALIBRATION_THRESHOLD),
    )

    if not updates:
        await db.rollback()
        return None

    try:
        profile_enc = encrypt_json(
            updated_vector, aad, await student_keys.get_or_create(db, student_name),
        )
        if row is None:
            db.add(MasteryProfile(
                student_name=student_name,
                subject_area=SUBJECT_AREA,
                evidence_count=1,
                profile_enc=profile_enc,
            ))
        else:
            row.profile_enc = profile_enc
            row.evidence_count += 1
        await db.commit()
    except Exception as exc:
        await db.rollback()
        log.warning("Music mastery persist failed for %s: %s", student_name, exc)
        return None

    return updated_vector


async def get_music_summary(db, student_name: str) -> Optional[dict]:
    """Render-only parent summary — same defensive load/None-on-missing
    contract as every sibling engine's get_*_summary."""
    from sqlalchemy import select

    from core import student_keys
    from core.database import MasteryProfile
    from core.encryption import decrypt_json, student_aad

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == SUBJECT_AREA,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        vector = decrypt_json(
            row.profile_enc,
            student_aad("mastery_profiles", "profile_enc", student_name, SUBJECT_AREA),
            await student_keys.get_existing(db, student_name),
        )
    except Exception as exc:
        log.warning("Music mastery summary load failed for %s: %s", student_name, exc)
        return None

    return build_summary_view(
        vector, student_name, row.evidence_count,
        row.updated_at.replace(microsecond=0).isoformat(),
    )
