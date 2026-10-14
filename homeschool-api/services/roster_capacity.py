"""Organization-aware roster capacity, independent of Locuto Pod fan-out.

The existing signed Bede license is the only *enforced* count of children
on this installation. Locuto's v1 messaging Pod cap (ten active human
members) is NOT a school/student-roster cap. Locuto's organizational
entitlement contract names negotiated max_children/max_households/max_seats
and max_organizations but defines NO global organizational maximum and
does not currently authorize a Bede roster through an API.

Until a verified entitlement bridge exists, never turn an unverified JSON
claim into more licensed seats or pretend that a Locuto organization
license was checked. This module only describes the current real state.
"""
from __future__ import annotations

from sqlalchemy import func, select

from core import license_state
from core.database import StudentConfig

# This is a *messaging* Pod cap, not a class or institution enrolment cap.
LOCUTO_V1_MESSAGING_POD_MAX_MEMBERS = 10


async def snapshot(db) -> dict:
    active = license_state.effective_info()
    enrolled = int((await db.execute(select(func.count()).select_from(StudentConfig))).scalar_one())
    licensed_children = active.seats if active else None
    return {
        "schema_version": 1,
        "enrolled_students": enrolled,
        "licensed_children": licensed_children,
        "remaining_licensed_children": (
            max(0, licensed_children - enrolled) if licensed_children is not None else None
        ),
        "capacity_authority": (
            "signed_bede_license" if active else "no_active_signed_student_limit"
        ),
        # The entitlement contract lives in a separate product. It is not
        # a Bede license and is NOT currently synchronized into this app.
        "locuto_organization_max_children": None,
        "locuto_entitlement_verified": False,
        "locuto_messaging_pod_max_members": LOCUTO_V1_MESSAGING_POD_MAX_MEMBERS,
        "messaging_limit_applies_to_student_roster": False,
        "roster_scope": "one_installation",
    }
