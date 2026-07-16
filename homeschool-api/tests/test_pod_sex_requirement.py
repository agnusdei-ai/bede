"""
Router-level tests for POST /pod/configs requiring `sex` on every student
config once LOCALE is a non-English deployment — see models/schemas.py's
SessionConfig.sex and services/ai_service.py's _locale_directive, which
needs it for grammatically correct address in a gendered language. Same
demo_db/db_session pattern as tests/test_pod_seat_cap.py.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException

from models.schemas import GradeStage, PodConfigsRequest, SessionConfig
from routers.pod import save_pod_configs

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


def _config(name: str, sex: "str | None" = None) -> SessionConfig:
    return SessionConfig(student_name=name, grade="3", grade_stage=GradeStage.core_mastery, sex=sex)


async def test_english_locale_never_requires_sex(db_session, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "locale", "en")
    req = PodConfigsRequest(configs=[_config("Emma"), _config("Liam", sex="male")])
    await save_pod_configs(req, _={"role": "parent"}, db=db_session)


async def test_non_english_locale_rejects_a_config_with_no_sex(db_session, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "locale", "es")
    req = PodConfigsRequest(configs=[_config("Emma", sex="female"), _config("Liam")])
    with pytest.raises(HTTPException) as exc_info:
        await save_pod_configs(req, _={"role": "parent"}, db=db_session)
    assert exc_info.value.status_code == 400
    assert "Liam" in exc_info.value.detail
    assert "Emma" not in exc_info.value.detail


async def test_non_english_locale_accepts_every_config_with_sex_set(db_session, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "locale", "es")
    req = PodConfigsRequest(configs=[_config("Emma", sex="female"), _config("Liam", sex="male")])
    await save_pod_configs(req, _={"role": "parent"}, db=db_session)
