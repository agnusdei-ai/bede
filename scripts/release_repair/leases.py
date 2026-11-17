"""Leases: one writer per task, and stale workers cannot land results."""
from __future__ import annotations

import uuid


def issue(task: dict, now: float, ttl: int) -> dict:
    return {"lease_id": uuid.uuid4().hex, "generation": int(task.get("lease_generation") or 0) + 1,
            "expires_at": now + ttl}


def check(task: dict, lease: dict | None, now: float) -> str | None:
    """Return a refusal reason, or None when the lease is current."""
    if not lease:
        return "no_lease"
    if lease.get("lease_id") != task.get("lease_id"):
        return "stale_lease"
    if int(lease.get("generation", -1)) != int(task.get("lease_generation") or 0):
        return "stale_lease_generation"
    if now > float(task.get("lease_expires_at") or 0):
        return "lease_expired"
    return None
