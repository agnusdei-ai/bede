"""
Reading & spelling mastery for grades 3-8 — the half of literacy Bede
could not see at all.

THE GAP THIS CLOSES. Before this module, literacy measurement stopped dead
at the end of 2nd grade. services/diagnostic/phonics.py covers decoding
(phonological awareness → letter sounds → CVC blending → blends and
digraphs → long vowel patterns → sight words) and is gated to
GradeStage.foundations in both the prompt and the recording code.
services/diagnostic/composition.py measures WRITING quality from narration
rubrics. Between them there was nothing at all for reading in grades 3-8 —
no fluency, no vocabulary, no morphology, no comprehension — and **no
spelling anywhere in the codebase at any grade**. A 5th grader could work
with Bede for a year and produce zero evidence about how they read.

DOMAINS IS A DEVELOPMENTAL SEQUENCE, NOT A CHECKLIST. Same choice
phonics.py made and for the same reason: reading has a real order, so
next_steps walks DOMAINS in that order rather than sorting by probability
the way composition.py and language_exposure.py do. Word-level work
(decoding longer words, spelling patterns, morphology) comes before
fluency, fluency before the comprehension strands, because a child who is
still sounding out `disappointment` has no attention left over for
inferring why a character said it.

The structure follows the Simple View of Reading and Scarborough's Reading
Rope — the international consensus model — with both strands represented:
word recognition (domains 1-5) and language comprehension (domains 6-10).
Spelling is explicit rather than assumed, across three of the ten domains,
because English is the reason it has to be.

WHY NOT SIMPLY COPY A HIGH-RANKING SYSTEM'S READING APPROACH. Finland is
the usual reference, and it is a poor template for English specifically —
not because its schools are weak, but because Finnish orthography is very
nearly transparent (close to one letter, one sound), so Finnish children
decode fluently within months and their curriculum can move to
comprehension almost immediately. English is deeply opaque: the same
letters say different things in `though`, `through`, `tough`, and meaning
is carried by morphology (`sign` → `signature`) that pronunciation
actively hides. A curriculum for English needs MORE explicit word study
than a Finnish one, not less — which is why morphology and spelling
patterns are load-bearing domains here rather than afterthoughts.

Worth recording plainly: Finland's own PISA reading score has fallen from
546 (2006) to 490 (2022), its lowest on record and the second-largest
decline in the OECD, though still above the OECD average of 476. Current
Finnish outcomes are not the benchmark to chase; the reading science is.

CALIBRATION_THRESHOLD matches phonics' 3 rather than mathematics' 5. Each
observation here is a genuine, deliberate check on one domain during
Language Arts or Living Books, not an incidental moment — so evidence is
scarcer per session than math's but individually more informative.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.diagnostic.mastery import calibration_weight_for, classify_level

log = logging.getLogger(__name__)

MasteryVector = dict[str, float]

SUBJECT_AREA = "literacy"

# Same reasoning as phonics.CALIBRATION_THRESHOLD — see the module
# docstring. Also a placeholder pending real-session tuning, exactly like
# mastery.CALIBRATION_THRESHOLD's own documented "[to verify final N]".
CALIBRATION_THRESHOLD = 3

# Same outcome vocabulary and scores as every other diagnostic in this
# package, so a "partial" means the same thing to a parent everywhere.
_OUTCOME_SCORES: dict[str, float] = {
    "correct": 1.0,
    "partial": 0.65,
    "hint_dependent": 0.35,
    "incorrect": 0.0,
}

# Developmental order. next_steps walks this sequence — see the docstring.
DOMAINS: tuple[str, ...] = (
    # ── Word recognition (Scarborough's lower strand) ──────────────────
    "decoding_multisyllable",
    "spelling_patterns",
    "morphology",
    "spelling_homophones",
    "fluency",
    # ── Language comprehension (upper strand) ──────────────────────────
    "vocabulary",
    "literal_comprehension",
    "inference",
    "text_structure",
    "author_craft",
)

DOMAIN_LABELS: dict[str, str] = {
    "decoding_multisyllable": "Reading Longer Words",
    "spelling_patterns": "Spelling Patterns & Rules",
    "morphology": "Prefixes, Suffixes & Word Roots",
    "spelling_homophones": "Homophones & Tricky Spellings",
    "fluency": "Reading Smoothly & With Expression",
    "vocabulary": "Word Meanings",
    "literal_comprehension": "Retelling What the Text Said",
    "inference": "Reading Between the Lines",
    "text_structure": "How a Text Is Built",
    "author_craft": "The Author's Craft & Purpose",
}

# Bede-facing description of what a genuine observation in each domain
# looks like, threaded into the prompt (ai_service.py's
# _literacy_checkin_note) so Bede recognizes real evidence in ordinary
# conversation instead of inventing a test.
DOMAIN_CHECKIN_HINTS: dict[str, str] = {
    "decoding_multisyllable":
        "the child reads a long unfamiliar word aloud — whether they break it into syllables or stall",
    "spelling_patterns":
        "a spelling comes up in their writing or copywork — whether the pattern (dropping the e, doubling, ie/ei) held",
    "morphology":
        "a word's parts are noticed — what `un-`, `-tion`, or a root like `port` does to the meaning",
    "spelling_homophones":
        "their/there, its/it's, to/too and similar pairs — whether the right one was chosen and why",
    "fluency":
        "the child reads a passage aloud — pace, accuracy, and whether the phrasing carries the sense",
    "vocabulary":
        "an unfamiliar word in the reading — whether they can work out or already hold its meaning",
    "literal_comprehension":
        "a narration or retelling — whether the actual events, order, and details are accurate",
    "inference":
        "something the text implies but never states — a character's motive, an unspoken cause",
    "text_structure":
        "how the piece is organized — story shape, sequence, compare/contrast, cause and effect",
    "author_craft":
        "why the author chose a word, an image, or an ending — tone, purpose, figurative language",
}


def new_vector() -> MasteryVector:
    """Cold start: flat 0.5 across all ten domains. No prior data exists to
    justify weighting toward any one of them — that would presume something
    about a child before observing anything."""
    return {domain: 0.5 for domain in DOMAINS}


@dataclass
class LiteracyUpdate:
    domain: str
    prior: float
    posterior: float
    observed_at: str


def apply_evidence(
    vector: MasteryVector,
    domain: str,
    outcome: str,
    calibration_weight: float = 1.0,
) -> tuple[MasteryVector, list[LiteracyUpdate]]:
    """
    One check-in's evidence for exactly one domain — mirrors
    phonics.apply_evidence's single-domain-per-call shape. Same blend
    formula as every other diagnostic here: prior + weight*(observed -
    prior), clamped to [0,1]. An unrecognized domain or outcome is a true
    no-op, never a raise — hallucinated model output must not break a
    child's turn.
    """
    if domain not in DOMAINS or outcome not in _OUTCOME_SCORES:
        return dict(vector), []

    observed = _OUTCOME_SCORES[outcome]
    prior = vector.get(domain, 0.5)
    blended = max(0.0, min(1.0, prior + calibration_weight * (observed - prior)))

    updated = dict(vector)
    updated[domain] = blended
    return updated, [LiteracyUpdate(
        domain=domain, prior=prior, posterior=blended,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )]


def build_summary_view(
    vector: MasteryVector,
    student_name: str,
    evidence_count: int,
    updated_at: str,
) -> dict:
    """
    MasteryProfileSummary-shaped dict — same contract as the sibling
    modules'. next_steps walks DOMAINS in developmental order (phonics'
    approach) rather than sorting by probability: the earliest unsecured
    domain is the honest next thing to work on, because the later ones
    depend on it. A child weak in decoding is not helped by being pointed
    at author's craft, however low that number happens to be.
    """
    domains = []
    gaps = []
    for domain in DOMAINS:
        probability = vector.get(domain, 0.5)
        level = classify_level(probability)
        label = DOMAIN_LABELS[domain]
        skill_view = {
            "skill_id": f"literacy.{domain}",
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
    Persistence-backed entry point — mirrors phonics.process_evidence and
    language_exposure.process_evidence's load/update/store shape exactly,
    against MasteryProfile(subject_area="literacy"). Called from
    ai_service.py's _record_literacy_evidence. Best-effort: every exception
    is caught and logged, never raised, so a diagnostic hiccup never breaks
    the child's tutoring turn.
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
                MasteryProfile.subject_area == SUBJECT_AREA,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            vector = new_vector()
            vector_is_cold_start = True
        else:
            # Backfilled against the CURRENT domain list, same reasoning as
            # mastery.ensure_complete: a vector stored before a domain was
            # added would otherwise never report or offer it.
            stored = decrypt_json(row.profile_enc)
            vector = new_vector()
            for domain_id, probability in stored.items():
                if domain_id in vector:
                    vector[domain_id] = probability
    except Exception as exc:
        log.warning("Literacy mastery load failed for %s, treating as cold-start: %s", student_name, exc)
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
        profile_enc = encrypt_json(updated_vector)
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
        log.warning("Literacy mastery persist failed for %s: %s", student_name, exc)
        return None

    return updated_vector


async def get_literacy_summary(db, student_name: str) -> Optional[dict]:
    """Render-only parent summary — same defensive load/None-on-missing
    contract as the sibling get_*_summary functions."""
    from sqlalchemy import select

    from core.database import MasteryProfile
    from core.encryption import decrypt_json

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
        stored = decrypt_json(row.profile_enc)
        vector = new_vector()
        for domain_id, probability in stored.items():
            if domain_id in vector:
                vector[domain_id] = probability
    except Exception as exc:
        log.warning("Literacy mastery summary load failed for %s: %s", student_name, exc)
        return None

    return build_summary_view(
        vector, student_name, row.evidence_count,
        row.updated_at.replace(microsecond=0).isoformat(),
    )
