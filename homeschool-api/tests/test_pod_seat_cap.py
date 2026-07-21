"""
Router-level tests for the license seat cap on POST /pod/configs (see
core/licensing.py, routers/pod.py). Real in-memory SQLite via the demo_db
fixture (tests/conftest.py) — same pattern as tests/test_admin_usage_router.py,
calling the router function directly rather than through a full TestClient
since require_parent's JWT plumbing isn't what's under test here.
"""
import base64
import json
import uuid
from datetime import date

import pytest
import pytest_asyncio
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa
from fastapi import HTTPException

from core import license_state, licensing
from core.config import settings
from models.schemas import GradeStage, PodConfigsRequest, SessionConfig
from routers.pod import save_pod_configs

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@pytest.fixture
def license_with_seats(monkeypatch):
    """Signs a license with the given seat count and makes it the EFFECTIVE
    license via core/license_state.py — the seat cap reads the effective
    license now (a DB-applied key can beat the env one), not
    settings.license_key directly."""
    def _make(seats: int) -> str:
        key = ECC.generate(curve="ed25519")
        monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", key.public_key().export_key(format="PEM"))
        licensing._cached_verify.cache_clear()
        payload = {
            "id": str(uuid.uuid4()), "licensee": "Test", "tier": "core",
            "seats": seats, "issued": date.today().isoformat(), "expires": None,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = eddsa.new(key, "rfc8032").sign(payload_bytes)
        lic = f"{_b64url(payload_bytes)}.{_b64url(signature)}"
        monkeypatch.setattr(settings, "license_key", lic)
        license_state.refresh(lic, None, required=False)
        return lic
    yield _make
    license_state.refresh("", None, required=False)


def _config(name: str) -> SessionConfig:
    return SessionConfig(student_name=name, grade="3", grade_stage=GradeStage.core_mastery)


async def test_save_within_seat_cap_succeeds(db_session, license_with_seats):
    license_with_seats(seats=3)
    req = PodConfigsRequest(configs=[_config("Emma"), _config("Liam")])
    await save_pod_configs(req, _={"role": "parent"}, db=db_session)


async def test_save_exceeding_seat_cap_is_rejected(db_session, license_with_seats):
    license_with_seats(seats=2)
    req = PodConfigsRequest(configs=[_config("Emma"), _config("Liam"), _config("Noah")])
    with pytest.raises(HTTPException) as exc_info:
        await save_pod_configs(req, _={"role": "parent"}, db=db_session)
    assert exc_info.value.status_code == 403
    assert "up to 2 students" in exc_info.value.detail


async def test_seat_cap_counts_existing_students_across_saves(db_session, license_with_seats):
    license_with_seats(seats=2)
    await save_pod_configs(
        PodConfigsRequest(configs=[_config("Emma"), _config("Liam")]),
        _={"role": "parent"}, db=db_session,
    )
    # A third, distinct student would push the pod to 3 — over the 2-seat cap.
    with pytest.raises(HTTPException) as exc_info:
        await save_pod_configs(
            PodConfigsRequest(configs=[_config("Noah")]),
            _={"role": "parent"}, db=db_session,
        )
    assert exc_info.value.status_code == 403


async def test_resaving_the_same_students_does_not_double_count(db_session, license_with_seats):
    license_with_seats(seats=2)
    req = PodConfigsRequest(configs=[_config("Emma"), _config("Liam")])
    await save_pod_configs(req, _={"role": "parent"}, db=db_session)
    # Same two names again — an update, not new seats, must not trip the cap.
    await save_pod_configs(req, _={"role": "parent"}, db=db_session)


async def test_no_license_key_skips_seat_enforcement(db_session, monkeypatch):
    """Unset LICENSE_KEY (dev/self-managed mode) must not itself impose a cap."""
    monkeypatch.setattr(settings, "license_key", "")
    req = PodConfigsRequest(configs=[_config(f"Student{i}") for i in range(10)])
    await save_pod_configs(req, _={"role": "parent"}, db=db_session)
