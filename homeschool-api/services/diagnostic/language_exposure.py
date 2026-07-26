"""
Language-exposure mastery — a light, "setting the stage" read on how a
child responds to brief foreign-language moments that arise naturally out
of History, Saints, and Art & Music content (a Latin phrase tied to Rome, a
French word from the Revolution unit, an Italian musical term from composer
study, a saint's name or homeland phrase). Reuses MasteryProfile/
DiagnosticEvidenceLog exactly like services/diagnostic/{composition,
phonics}.py do (subject_area="language_exposure" — MasteryProfile's own
composite PK was explicitly designed for exactly this kind of extension),
with a third purpose-built update rule — see docs/diagnostic/
DIAGNOSTIC_ENGINE_DESIGN.md §13.3 for the full writeup.

This is explicitly NOT a language-learning app (no Duolingo-style spaced
repetition over a vocabulary bank, no per-word item tracking, no formal
lessons). It exists to build a coarse, honest signal — per language family,
not per word — of how readily a child picks up and recalls a brief foreign
phrase encountered in context, so a parent has real evidence (not a guess)
if they're later deciding whether to start formal instruction in a
particular language and roughly when a child seems ready for it. Bede does
NOT teach any language systematically; see _language_checkin_note in
ai_service.py for the actual pedagogical trigger — a teach-then-recall
moment woven into existing content, never a drill, never announced, and
entirely opportunistic (only when today's lesson naturally offers one,
unlike phonics' guaranteed-domain-list check-in).

LANGUAGES is grounded in what the bundled Mater Amabilis curriculum
(data/catalog/year1-8.json) actually surfaces: Latin and Greek from Roman/
Greek history and myth (and the classical-education tradition's own root-
word emphasis), French from composer/artist study (Delacroix, Monet) and
the Year 7 French Revolution unit, Italian from Renaissance art and
Italian composers (Vivaldi), German from the Austro-German composer
sequence that runs through nearly every year (Mozart, Haydn, Bach,
Schubert, Beethoven), and Spanish from the app's own existing Guadalupe/
Juan Diego saints content (see ai_service.py's _guadalupe_note) and the
many Spanish-speaking saints in the CM saints rotation. Unlike phonics'
DOMAINS, these six aren't a developmental sequence — a child isn't
"supposed" to secure Latin before German — so next_steps below sorts by
probability (composition's approach), not a fixed walk order.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.diagnostic.mastery import calibration_weight_for, classify_level

log = logging.getLogger(__name__)

MasteryVector = dict[str, float]

# Same placeholder spirit as mastery.CALIBRATION_THRESHOLD's own
# "[to verify final N]" flag. Evidence here is opportunistic across THREE
# subjects (History, Saints, Art & Music) rather than gated to one the way
# phonics is, so it may arrive faster in practice than phonics' — but each
# individual moment is still content-dependent, never guaranteed the way a
# phonics check-in's fixed domain list is, so this stays at phonics'
# threshold rather than composition's lower one.
CALIBRATION_THRESHOLD = 3

# Same outcome vocabulary and scores as phonics.py/record_skill_evidence,
# for consistency across the codebase.
_OUTCOME_SCORES: dict[str, float] = {
    "correct": 1.0,
    "partial": 0.65,
    "hint_dependent": 0.35,
    "incorrect": 0.0,
}

LANGUAGES: tuple[str, ...] = (
    "latin",
    "greek",
    "french",
    "italian",
    "german",
    "spanish",
)

LANGUAGE_LABELS: dict[str, str] = {
    "latin": "Latin",
    "greek": "Greek",
    "french": "French",
    "italian": "Italian",
    "german": "German",
    "spanish": "Spanish",
}

# Bede-facing description of the kind of curriculum moment that naturally
# offers each language — threaded into the prompt (ai_service.py's
# _language_checkin_note) so Bede recognizes a real opening rather than
# forcing one. Not exhaustive; Bede should still use judgment for content
# these examples don't cover.
LANGUAGE_CHECKIN_HINTS: dict[str, str] = {
    "latin": "a Roman history topic, a Church Latin phrase, or a Latin root behind an English word",
    "greek": "a Greek myth, a term from Greek history, or a Greek root behind an English word",
    "french": "French history (the Revolution, Napoleon), or a French composer or artist being studied",
    "italian": "Italian Renaissance art, an Italian composer, or an Italian musical term (allegro, forte)",
    "german": "a German or Austrian composer being studied (Mozart, Haydn, Bach, Schubert, Beethoven)",
    "spanish": "a Spanish-speaking saint's name or homeland phrase, or Spanish-language history/geography content",
}


def new_vector() -> MasteryVector:
    """Cold start: flat 0.5 across all six languages. No real prior data
    exists yet to justify weighting toward any one language — that would
    presume an aptitude before any evidence has been observed."""
    return {language: 0.5 for language in LANGUAGES}


@dataclass
class LanguageUpdate:
    language: str
    prior: float
    posterior: float
    observed_at: str


def apply_evidence(
    vector: MasteryVector,
    language: str,
    outcome: str,
    calibration_weight: float = 1.0,
) -> tuple[MasteryVector, list[LanguageUpdate]]:
    """
    One check-in's worth of evidence for exactly one language — mirrors
    phonics.apply_evidence's single-domain-per-call shape (one teach-then-
    recall moment is evidence for one language, not all six at once). Same
    blend formula as mastery.bayesian_update/composition.apply_assessment/
    phonics.apply_evidence: prior + weight*(observed-prior), clamped to
    [0,1]. An unrecognized language or outcome is a true no-op — never
    raises on hallucinated model output.
    """
    if language not in LANGUAGES or outcome not in _OUTCOME_SCORES:
        return dict(vector), []

    observed = _OUTCOME_SCORES[outcome]
    prior = vector.get(language, 0.5)
    blended = prior + calibration_weight * (observed - prior)
    blended = max(0.0, min(1.0, blended))

    updated = dict(vector)
    updated[language] = blended
    update = LanguageUpdate(
        language=language, prior=prior, posterior=blended,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    return updated, [update]


def build_summary_view(
    vector: MasteryVector,
    student_name: str,
    evidence_count: int,
    updated_at: str,
) -> dict:
    """MasteryProfileSummary-shaped dict — same contract as composition/
    phonics build_summary_view. next_steps sorts by probability ascending
    (composition's approach), unlike phonics' fixed developmental walk —
    languages here have no real prerequisite order, so the most honest
    "what's worth noticing next" is simply whichever language has shown
    the least confident recall so far."""
    domains = []
    gaps = []
    for language in LANGUAGES:
        probability = vector.get(language, 0.5)
        level = classify_level(probability)
        label = LANGUAGE_LABELS[language]
        skill_view = {
            "skill_id": f"language_exposure.{language}",
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

    all_skill_views = [d["skills"][0] for d in domains]
    next_steps = sorted(
        (v for v in all_skill_views if v["level"] != "secure"),
        key=lambda v: v["probability"],
    )[:3]

    return {
        "student_name": student_name,
        "subject_area": "language_exposure",
        "evidence_count": evidence_count,
        "calibration": evidence_count < CALIBRATION_THRESHOLD,
        "domains": domains,
        "gaps": gaps,
        "next_steps": next_steps,
        "updated_at": updated_at,
    }


async def process_evidence(db, student_name: str, language: str, outcome: str) -> Optional[MasteryVector]:
    """
    Persistence-backed entry point — mirrors phonics.process_evidence and
    services.diagnostic.__init__.process_evidence's load/update/store shape
    exactly, against MasteryProfile(subject_area="language_exposure").
    Called from ai_service.py's _record_language_evidence. Best-effort:
    every exception is caught and logged, never raised, so a diagnostic
    hiccup never breaks the child's tutoring turn.
    """
    from sqlalchemy import select

    from core.database import MasteryProfile
    from core.encryption import decrypt_json, encrypt_json

    row = None
    vector_is_cold_start = False

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == "language_exposure",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            vector = new_vector()
            vector_is_cold_start = True
        else:
            vector = decrypt_json(row.profile_enc)
    except Exception as exc:
        log.warning("Language-exposure mastery load failed for %s, treating as cold-start: %s", student_name, exc)
        vector = new_vector()
        vector_is_cold_start = True

    evidence_count_before = 0 if vector_is_cold_start else row.evidence_count
    updated_vector, updates = apply_evidence(
        vector, language, outcome,
        calibration_weight=calibration_weight_for(evidence_count_before, CALIBRATION_THRESHOLD),
    )

    if not updates:
        await db.rollback()
        return None

    try:
        profile_enc = encrypt_json(updated_vector)
        if row is None:
            db.add(MasteryProfile(
                student_name=student_name,
                subject_area="language_exposure",
                evidence_count=1,
                profile_enc=profile_enc,
            ))
        else:
            row.profile_enc = profile_enc
            row.evidence_count += 1
        await db.commit()
    except Exception as exc:
        await db.rollback()
        log.warning("Language-exposure mastery persist failed for %s: %s", student_name, exc)
        return None

    return updated_vector


async def get_language_summary(db, student_name: str) -> Optional[dict]:
    """Render-only parent summary — same defensive load/None-on-missing
    contract as composition.get_composition_summary/phonics.get_phonics_summary."""
    from sqlalchemy import select

    from core.database import MasteryProfile
    from core.encryption import decrypt_json

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == "language_exposure",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        vector = decrypt_json(row.profile_enc)
    except Exception as exc:
        log.warning("Language-exposure mastery summary load failed for %s: %s", student_name, exc)
        return None

    return build_summary_view(
        vector, student_name, row.evidence_count, row.updated_at.replace(microsecond=0).isoformat(),
    )
