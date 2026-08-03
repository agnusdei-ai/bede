"""
Comprehensive per-student data deletion — the technical backbone of a
parent's right to delete their child's data (COPPA). Removing a student
used to only delete their StudentConfig row (routers/pod.py) and, via a
separate, never-actually-wired-into-the-UI endpoint, their VoiceProfile —
every other per-student table (narration history, learner profile,
mastery tracking, session transcripts, usage events) was silently
retained forever with no user-reachable deletion path at all. This module
is the single place that knows the full list of tables scoped to one
student, so that list can't drift out of sync between call sites the way
it already had.

Deliberately does NOT touch tables that are keyed differently on purpose:
ParentSecurityKey/ParentTotpConfig (the parent's own MFA, not the
child's), DemoCodeSession/DiagnosticPreviewUse/DemoInteractionSignal (the
public demo's ephemeral, pseudonymous data — see services/interaction_signals.py
for its own separate retention story), AuditLog (a security record kept
independent of any single student on purpose, per core/audit.py's own
docstring — deleting a student doesn't rewrite the security history of
what happened on this deployment).
"""
import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def delete_all_student_data(db: AsyncSession, student_name: str) -> dict[str, int]:
    """
    Deletes every row scoped to `student_name` across all per-student
    tables and commits once. Returns a count per table (for the audit log
    detail and the caller's own confirmation) — never student content,
    just how many rows of each kind were removed. Safe to call for a
    student with no data at all (every count is simply 0); the caller
    decides whether that's worth a 404.
    """
    from core.database import (
        ApiUsageEvent,
        DiagnosticEvidenceLog,
        SkillActivityLog,
        LearnerBehaviorCheck,
        LearnerProfile,
        LessonBookmark,
        MasteryProfile,
        NarrationAssessment,
        SessionTranscript,
        StudentConfig,
        VoiceProfile,
    )

    from core import student_keys

    counts: dict[str, int] = {}
    for label, model in (
        ("student_config", StudentConfig),
        ("voice_profile", VoiceProfile),
        ("narration_assessments", NarrationAssessment),
        ("learner_profile", LearnerProfile),
        ("learner_behavior_check", LearnerBehaviorCheck),
        ("lesson_bookmarks", LessonBookmark),
        ("mastery_profiles", MasteryProfile),
        ("diagnostic_evidence_log", DiagnosticEvidenceLog),
        ("skill_activity_log", SkillActivityLog),
        ("session_transcripts", SessionTranscript),
        ("api_usage_events", ApiUsageEvent),
    ):
        result = await db.execute(delete(model).where(model.student_name == student_name))
        counts[label] = result.rowcount or 0

    # Crypto-shred LAST, in the same transaction as the row deletes, so the
    # two cannot diverge: a partial failure can never leave the key destroyed
    # while rows remain (unreadable data with no way back) or the rows gone
    # while the key survives (backups still openable).
    #
    # This is what makes the deletion claim true beyond the live table.
    # DELETE alone leaves the rows in dead tuples until VACUUM, in WAL, and
    # in every backup taken beforehand — all decryptable indefinitely under a
    # DATA_KEY that never changes. Destroying the student's own key makes
    # every one of those copies permanently unopenable at once, including by
    # this deployment. See core/student_keys.py.
    shredded = await student_keys.destroy(db, student_name)
    counts["data_key_shredded"] = 1 if shredded else 0

    await db.commit()
    log.info("Deleted all data for student %r: %s", student_name, counts)
    return counts
