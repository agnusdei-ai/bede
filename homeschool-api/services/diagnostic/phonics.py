"""
Phonics/reading-foundations mastery — K-2 (GradeStage.foundations) only.
Reuses MasteryProfile/DiagnosticEvidenceLog exactly like services/diagnostic/
composition.py does (subject_area="phonics" — MasteryProfile's own composite
PK was explicitly designed for this kind of extension), with the same kind
of purpose-built update rule rather than math's full CDM/IRT/KST pipeline —
see docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md §13.2 for the full writeup.

Unlike composition, phonics evidence does NOT arrive as a side effect of
something Bede already does constantly. Bede's own tutoring deliberately
does not teach phonics/decoding directly — see data/catalog/year1.json's
language_arts guidance: "Phonemic awareness and reading practice happen
alongside, not through this tutoring session." Before this module, the
only phonics signal in the system was whatever a parent-authored
CORE_AREAS "phonics_language" term-mastery topic happened to surface
incidentally (models.schemas.SUBJECT_CORE_AREAS, services/ai_service.py's
_term_outcomes_note) — nothing generated evidence on its own.

This module is paired with a real, if light, pedagogical change: Bede now
occasionally weaves ONE quick, playful phonics check into a K-2
language_arts session (see _phonics_checkin_note in ai_service.py) —
never a drill, never announced, gated to exactly the stage/subject where
the family's own separate phonics program is the primary instruction and
Bede's role stays reinforcement, not instruction. That check-in is what
actually generates the evidence this module rolls up.

DOMAINS is a standard K-2 systematic-phonics scope and sequence
(phonological awareness before the alphabetic principle, before blending,
before blends/digraphs, before long-vowel patterns, before sight words) —
the same rough progression most explicit phonics programs (the kind a
Charlotte Mason family typically pairs with Bede for, per that catalog
guidance above) teach in. Order matters here in a way it doesn't for
composition's five independent rubric dimensions: next_steps below
surfaces the EARLIEST domain that isn't yet secure, respecting that real
developmental sequence, rather than composition's plain lowest-probability
sort.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.diagnostic.mastery import calibration_weight_for, classify_level

log = logging.getLogger(__name__)

MasteryVector = dict[str, float]

# Three check-ins, not five (math) or two (composition) — phonics evidence
# is scarcer than either: it's gated to K-2 language_arts sessions
# specifically (not every subject, unlike composition), and each check-in
# is deliberately light/occasional, not a per-session guarantee. Still a
# placeholder in the same spirit as mastery.CALIBRATION_THRESHOLD's own
# "[to verify final N]" flag.
CALIBRATION_THRESHOLD = 3

# Same outcome vocabulary and scores as record_skill_evidence/qmatrix.py's
# math engine, for consistency across the codebase — a phonics check-in and
# a math probe are reported through the same shape of judgment.
_OUTCOME_SCORES: dict[str, float] = {
    "correct": 1.0,
    "partial": 0.65,
    "hint_dependent": 0.35,
    "incorrect": 0.0,
}

DOMAINS: tuple[str, ...] = (
    "phonological_awareness",
    "letter_sound",
    "cvc_blending",
    "blends_digraphs",
    "long_vowel_patterns",
    "sight_words",
)

DOMAIN_LABELS: dict[str, str] = {
    "phonological_awareness": "Rhyming & Sound Play",
    "letter_sound": "Letter Sounds",
    "cvc_blending": "Blending Simple Words",
    "blends_digraphs": "Blends & Digraphs (sh, ch, bl...)",
    "long_vowel_patterns": "Long Vowel Patterns",
    "sight_words": "Sight Words",
}

# Bede-facing description of each domain — what a "quick, playful check" for
# it actually looks like. Threaded into the prompt (ai_service.py's
# _phonics_checkin_note) so Bede picks a real, concrete domain rather than
# guessing from the id alone.
DOMAIN_CHECKIN_HINTS: dict[str, str] = {
    "phonological_awareness": "ask for a rhyme, or which word in a pair starts with the same sound",
    "letter_sound": "ask what sound a single letter makes",
    "cvc_blending": "ask them to sound out a simple three-letter word like cat or sun",
    "blends_digraphs": "ask what sound a blend or digraph (sh, ch, th, bl, st) makes, or have them sound out a word with one",
    "long_vowel_patterns": "ask them to sound out a word with a silent e or a vowel team (rain, boat, cake)",
    "sight_words": "ask them to read a common irregular word (the, was, said, of) they can't sound out phonetically",
}


def new_vector() -> MasteryVector:
    """Cold start: flat 0.5 across all six domains. No real prior data
    exists yet to justify weighting the vector toward the natural
    developmental order — that order is used for next_steps below, not for
    seeding starting confidence."""
    return {domain: 0.5 for domain in DOMAINS}


@dataclass
class PhonicsUpdate:
    domain: str
    prior: float
    posterior: float
    observed_at: str


def apply_evidence(
    vector: MasteryVector,
    domain: str,
    outcome: str,
    calibration_weight: float = 1.0,
) -> tuple[MasteryVector, list[PhonicsUpdate]]:
    """
    One check-in's worth of evidence for exactly one domain — unlike
    composition (one assess_narration call scores all five dimensions at
    once), a single phonics check-in targets one specific thing, same as a
    math probe. Same blend formula as mastery.bayesian_update/composition.
    apply_assessment: prior + weight*(observed-prior), clamped to [0,1].
    An unrecognized domain or outcome is a true no-op — never raises on
    hallucinated model output, matching qmatrix.q_row's own contract.
    """
    if domain not in DOMAINS or outcome not in _OUTCOME_SCORES:
        return dict(vector), []

    observed = _OUTCOME_SCORES[outcome]
    prior = vector.get(domain, 0.5)
    blended = prior + calibration_weight * (observed - prior)
    blended = max(0.0, min(1.0, blended))

    updated = dict(vector)
    updated[domain] = blended
    update = PhonicsUpdate(
        domain=domain, prior=prior, posterior=blended,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    return updated, [update]


def build_summary_view(
    vector: MasteryVector,
    student_name: str,
    evidence_count: int,
    updated_at: str,
) -> dict:
    """MasteryProfileSummary-shaped dict — same contract as composition.
    build_summary_view. next_steps walks DOMAINS in their real
    developmental order and returns the first ones that aren't yet secure,
    rather than sorting by probability — a child who hasn't secured
    letter-sound correspondence yet should see that before blends and
    digraphs, even if a lucky guess left blends_digraphs technically
    higher."""
    domains = []
    gaps = []
    for domain in DOMAINS:
        probability = vector.get(domain, 0.5)
        level = classify_level(probability)
        label = DOMAIN_LABELS[domain]
        skill_view = {
            "skill_id": f"phonics.{domain}",
            "label": label,
            "domain": label,
            "grade_band": "K-2",
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

    next_steps = []
    for domain in DOMAINS:
        level = classify_level(vector.get(domain, 0.5))
        if level != "secure":
            next_steps.append({
                "skill_id": f"phonics.{domain}",
                "label": DOMAIN_LABELS[domain],
                "domain": DOMAIN_LABELS[domain],
                "grade_band": "K-2",
                "probability": vector.get(domain, 0.5),
                "level": level,
            })
        if len(next_steps) == 3:
            break

    return {
        "student_name": student_name,
        "subject_area": "phonics",
        "evidence_count": evidence_count,
        "calibration": evidence_count < CALIBRATION_THRESHOLD,
        "domains": domains,
        "gaps": gaps,
        "next_steps": next_steps,
        "updated_at": updated_at,
    }


async def process_evidence(db, student_name: str, domain: str, outcome: str) -> Optional[MasteryVector]:
    """
    Persistence-backed entry point — mirrors composition.process_assessment
    and services.diagnostic.__init__.process_evidence's load/update/store
    shape exactly, against MasteryProfile(subject_area="phonics"). Called
    from ai_service.py's _record_phonics_evidence. Best-effort: every
    exception is caught and logged, never raised, so a diagnostic hiccup
    never breaks the child's tutoring turn.
    """
    from sqlalchemy import select

    from core.database import MasteryProfile
    from core.encryption import decrypt_json, encrypt_json, student_aad

    row = None
    vector_is_cold_start = False

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == "phonics",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            vector = new_vector()
            vector_is_cold_start = True
        else:
            vector = decrypt_json(row.profile_enc, student_aad("mastery_profiles", "profile_enc", student_name, "phonics"))
    except Exception as exc:
        log.warning("Phonics mastery load failed for %s, treating as cold-start: %s", student_name, exc)
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
        profile_enc = encrypt_json(updated_vector, student_aad("mastery_profiles", "profile_enc", student_name, "phonics"))
        if row is None:
            db.add(MasteryProfile(
                student_name=student_name,
                subject_area="phonics",
                evidence_count=1,
                profile_enc=profile_enc,
            ))
        else:
            row.profile_enc = profile_enc
            row.evidence_count += 1
        await db.commit()
    except Exception as exc:
        await db.rollback()
        log.warning("Phonics mastery persist failed for %s: %s", student_name, exc)
        return None

    return updated_vector


async def get_phonics_summary(db, student_name: str) -> Optional[dict]:
    """Render-only parent summary — same defensive load/None-on-missing
    contract as composition.get_composition_summary."""
    from sqlalchemy import select

    from core.database import MasteryProfile
    from core.encryption import decrypt_json, student_aad

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == "phonics",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        vector = decrypt_json(row.profile_enc, student_aad("mastery_profiles", "profile_enc", student_name, "phonics"))
    except Exception as exc:
        log.warning("Phonics mastery summary load failed for %s: %s", student_name, exc)
        return None

    return build_summary_view(
        vector, student_name, row.evidence_count, row.updated_at.replace(microsecond=0).isoformat(),
    )
