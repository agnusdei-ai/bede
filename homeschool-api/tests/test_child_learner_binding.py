"""Focused regression tests for the shared child-to-learner boundary (#761)."""
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch, MagicMock

from core.deps import require_learner_access
from core.database import ChildLearnerBinding


def _only(binding):
    """db.get that returns the binding for its own table and nothing for any
    other (no learner here has a per-child PIN; see test_child_pins.py)."""
    async def get(model, key):
        return binding if model is ChildLearnerBinding else None
    return get


@pytest.mark.asyncio
async def test_child_only_reads_bound_learner():
    binding = ChildLearnerBinding(device_id="tablet-1", student_name="Alice", nonce="v1")
    db = AsyncMock()
    db.get.side_effect = _only(binding)
    auth = {"role": "child", "device_id": "tablet-1", "learner_nonce": "v1"}
    with patch("core.deps.settings") as settings, patch("core.deps.device_registry") as devices:
        settings.hosted_profile = False
        devices.is_revoked.return_value = False
        await require_learner_access(auth, "Alice", db)
        for requested in ("Bob", "campus-other"):
            with pytest.raises(HTTPException) as exc:
                await require_learner_access(auth, requested, db)
            assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unbound_rotated_and_revoked_fail_closed():
    db = AsyncMock()
    db.get.side_effect = _only(ChildLearnerBinding(device_id="tablet-1", student_name="Alice", nonce="v2"))
    with patch("core.deps.settings") as settings, patch("core.deps.device_registry") as devices:
        settings.hosted_profile = False
        devices.is_revoked.return_value = False
        for auth in (
            {"role": "child", "device_id": "tablet-1"},
            {"role": "child", "device_id": "tablet-1", "learner_nonce": "v1"},
        ):
            with pytest.raises(HTTPException):
                await require_learner_access(auth, "Alice", db)
        devices.is_revoked.return_value = True
        with pytest.raises(HTTPException):
            await require_learner_access(
                {"role": "child", "device_id": "tablet-1", "learner_nonce": "v2"},
                "Alice", db,
            )


@pytest.mark.asyncio
async def test_parent_preserved():
    db = AsyncMock()
    await require_learner_access({"role": "parent"}, "Alice", db)
    db.get.assert_not_called()
