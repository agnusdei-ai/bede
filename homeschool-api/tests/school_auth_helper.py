"""Opt a synthetic campus in to storing learner data, for fixtures that call
the pilot router functions directly rather than over HTTP.

Uses the REAL core.school_authorization.grant with the REAL current notice
hash. It never bypasses the gate; tests that exercise refusal build their own
unauthorized campus.
"""
from core import school_authorization


async def authorize_campus(db, campus_id: str, name: str = "Synthetic Administrator") -> None:
    await school_authorization.grant(
        db, campus_id, authorizer_role="administrator", authorizer_ref="administrator",
        authorizer_name=name, presented_notice_hash=school_authorization.notice_hash(),
    )
