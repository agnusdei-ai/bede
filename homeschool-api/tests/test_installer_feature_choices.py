"""Installer choices for Practice Coach and Curriculum Intelligence (issue #763).

Practice Coach is on by default and Curriculum Intelligence is off. Both are
asked together by the browser wizard and by setup.sh, and each is written to
.env only when it differs from that default. These tests run the real wizard
code and the real setup.sh, construct Settings from what they write, and
drive the real practice router to show that "off" means its routes refuse.
"""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import config as config_module
from core.config import Settings, settings
from core.deps import require_auth, require_educator, require_parent, require_practice_coach_enabled
from core.security import create_access_token
from routers import practice as practice_router
from services.curriculum import flag as curriculum_flag
from tests.test_wizard_and_api_agree_on_credentials import _wizard_fields

ROOT = Path(__file__).resolve().parents[2]
_WIZARD = ROOT / "scripts" / "setup_wizard" / "wizard.py"


def _load_wizard():
    spec = importlib.util.spec_from_file_location("bede_setup_wizard_features", _WIZARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wizard = _load_wizard()

COMBOS = [("yes", "no"), ("yes", "yes"), ("no", "no"), ("no", "yes")]  # (coach, curriculum)


def _parse(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def _settings_from(env: dict) -> Settings:
    kwargs = {k.lower(): v for k, v in env.items() if k.lower() in Settings.model_fields}
    return Settings(**kwargs)


def _flag_from(env: dict, monkeypatch) -> bool:
    if "CURRICULUM_ENGINE_ENABLED" in env:
        monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", env["CURRICULUM_ENGINE_ENABLED"])
    else:
        monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
    return curriculum_flag.curriculum_engine_enabled()


# ── Defaults ─────────────────────────────────────────────────────────────

def test_code_defaults_are_coach_on_curriculum_off():
    assert Settings.model_fields["practice_coach_enabled"].default is True
    assert Settings.model_fields["curriculum_engine_enabled"].default is False


def test_a_default_wizard_install_writes_neither_line_and_means_coach_on_curriculum_off(monkeypatch):
    fields = _wizard_fields()
    assert wizard.validate(fields) == ""
    env = _parse(wizard.build_env_file(fields))
    assert "PRACTICE_COACH_ENABLED" not in env
    assert "CURRICULUM_ENGINE_ENABLED" not in env
    built = _settings_from(env)
    assert built.practice_coach_enabled is True
    assert built.curriculum_engine_enabled is False
    assert _flag_from(env, monkeypatch) is False


def test_the_form_preselects_coach_on_and_curriculum_off():
    page = wizard.render_form()
    assert 'name="practice_coach" value="yes" checked' in page
    assert 'name="curriculum" value="no" checked' in page
    assert 'name="practice_coach" value="no" checked' not in page
    assert 'name="curriculum" value="yes" checked' not in page


# ── All four explicit combinations ───────────────────────────────────────

@pytest.mark.parametrize("coach,curriculum", COMBOS)
def test_every_combination_reaches_settings_and_the_flag(coach, curriculum, monkeypatch):
    fields = _wizard_fields(practice_coach=coach, curriculum=curriculum)
    assert wizard.validate(fields) == ""
    env = _parse(wizard.build_env_file(fields))
    assert ("PRACTICE_COACH_ENABLED" in env) == (coach == "no")
    assert ("CURRICULUM_ENGINE_ENABLED" in env) == (curriculum == "yes")
    built = _settings_from(env)
    assert built.practice_coach_enabled is (coach == "yes")
    assert built.curriculum_engine_enabled is (curriculum == "yes")
    assert _flag_from(env, monkeypatch) is (curriculum == "yes")


# ── Persistence: running setup again keeps explicit choices ──────────────

@pytest.mark.parametrize("coach,curriculum", COMBOS)
def test_rerunning_the_wizard_starts_from_the_existing_choices(coach, curriculum, tmp_path):
    first = wizard.build_env_file(_wizard_fields(practice_coach=coach, curriculum=curriculum))
    env_path = tmp_path / ".env"
    env_path.write_text(first)
    remembered = wizard.existing_choices(str(env_path))
    assert remembered.get("practice_coach", "yes") == coach
    assert remembered.get("curriculum", "no") == curriculum
    page = wizard.render_form(values=remembered)
    assert f'name="practice_coach" value="{coach}" checked' in page
    assert f'name="curriculum" value="{curriculum}" checked' in page
    # Submitting the prefilled form unchanged writes the same choices again.
    again = _parse(wizard.build_env_file(_wizard_fields(**remembered)))
    assert again.get("PRACTICE_COACH_ENABLED") == _parse(first).get("PRACTICE_COACH_ENABLED")
    assert again.get("CURRICULUM_ENGINE_ENABLED") == _parse(first).get("CURRICULUM_ENGINE_ENABLED")


def test_hand_written_values_are_read_back_honestly(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("PRACTICE_COACH_ENABLED=False\nCURRICULUM_ENGINE_ENABLED=ON\nRETAIN_MASTERY_PROFILES=false\n")
    assert wizard.existing_choices(str(env_path)) == {
        "practice_coach": "no", "curriculum": "yes", "keep_mastery": "no",
    }


def test_no_existing_env_means_defaults(tmp_path):
    assert wizard.existing_choices(str(tmp_path / "missing.env")) == {}


# ── Fail closed ──────────────────────────────────────────────────────────

def test_an_unrecognised_existing_value_reads_as_off(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("PRACTICE_COACH_ENABLED=maybe\nCURRICULUM_ENGINE_ENABLED=t\n")
    assert wizard.existing_choices(str(env_path)) == {"practice_coach": "no", "curriculum": "no"}


@pytest.mark.parametrize("field,value", [("practice_coach", "maybe"), ("curriculum", "true")])
def test_the_wizard_refuses_a_choice_it_does_not_offer(field, value):
    assert wizard.validate(_wizard_fields(**{field: value}))


@pytest.mark.parametrize("value", ["maybe", "ture", "t", "y", "enabled"])
def test_a_misspelled_curriculum_value_stops_boot_instead_of_meaning_off(value):
    with pytest.raises(Exception):
        Settings(curriculum_engine_enabled=value)


def test_settings_and_the_curriculum_flag_read_every_accepted_word_the_same(monkeypatch):
    assert config_module.CURRICULUM_FLAG_TRUE_VALUES == curriculum_flag._TRUE_VALUES
    for word in config_module.CURRICULUM_FLAG_TRUE_VALUES | config_module.CURRICULUM_FLAG_FALSE_VALUES:
        for spelled in (word, word.upper()):
            monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", spelled)
            assert Settings(curriculum_engine_enabled=spelled).curriculum_engine_enabled is \
                curriculum_flag.curriculum_engine_enabled(), spelled


def test_an_unparseable_coach_value_stops_boot():
    with pytest.raises(Exception):
        Settings(practice_coach_enabled="maybe")


# ── No duplicate controls ────────────────────────────────────────────────

def test_each_choice_is_one_radio_pair_on_the_form():
    page = wizard.render_form()
    assert page.count('name="practice_coach"') == 2
    assert page.count('name="curriculum"') == 2
    assert page.index('name="practice_coach"') < page.index('name="curriculum"') < page.index('name="parent_password"')


def test_each_setting_is_passed_and_documented_exactly_once():
    compose = (ROOT / "docker-compose.yml").read_text()
    for name in ("PRACTICE_COACH_ENABLED", "CURRICULUM_ENGINE_ENABLED"):
        assert compose.count(f"- {name}=") == 1, name
        for example in (ROOT / ".env.example", ROOT / "homeschool-api" / ".env.example"):
            assert example.read_text().count(f"# {name}=") == 1, (example, name)


# ── setup.sh, the terminal installer ─────────────────────────────────────

# provider 1, api key, local db (default), parent password, child pin, licence
_ANSWERS = "1\nsk-ant-test\n\nparentpass123\n805274199\nlicense-value\n"


@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(ROOT / "setup.sh", tmp_path / "setup.sh")
    (tmp_path / "homeschool-api" / "data").mkdir(parents=True)
    shutil.copy(ROOT / "homeschool-api" / "data" / "consent_notice.txt",
                tmp_path / "homeschool-api" / "data" / "consent_notice.txt")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("docker", "curl"):
        (stubs / name).write_text("#!/bin/sh\nexit 0\n")
        (stubs / name).chmod(0o755)
    return tmp_path


def _run_setup(sandbox, stdin):
    env = {**os.environ, "PATH": f"{sandbox / 'stubs'}:{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", "setup.sh", "--accept-consent-notice"],
        cwd=sandbox, input=stdin, text=True, capture_output=True, env=env, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return _parse((sandbox / ".env").read_text()), result.stdout


def test_setup_sh_defaults_when_the_questions_are_skipped(sandbox):
    env, out = _run_setup(sandbox, _ANSWERS)
    assert "Practice Coach" in out and "Curriculum Intelligence" in out
    assert "PRACTICE_COACH_ENABLED" not in env
    assert "CURRICULUM_ENGINE_ENABLED" not in env


@pytest.mark.parametrize("coach,curriculum", COMBOS)
def test_setup_sh_every_combination(sandbox, coach, curriculum):
    env, _ = _run_setup(sandbox, _ANSWERS + f"{coach[0]}\n{curriculum[0]}\n")
    assert env.get("PRACTICE_COACH_ENABLED") == ("false" if coach == "no" else None)
    assert env.get("CURRICULUM_ENGINE_ENABLED") == ("true" if curriculum == "yes" else None)
    built = _settings_from(env | {"PRODUCTION": "false"})
    assert built.practice_coach_enabled is (coach == "yes")
    assert built.curriculum_engine_enabled is (curriculum == "yes")


def test_setup_sh_rerun_keeps_the_previous_choices_on_enter(sandbox):
    _run_setup(sandbox, _ANSWERS + "n\ny\n")
    # Overwrite the existing .env, pressing Enter at both feature questions.
    env, _ = _run_setup(sandbox, "y\n" + _ANSWERS + "\n\n")
    assert env.get("PRACTICE_COACH_ENABLED") == "false"
    assert env.get("CURRICULUM_ENGINE_ENABLED") == "true"


def test_setup_sh_keeping_the_existing_env_changes_nothing(sandbox):
    _run_setup(sandbox, _ANSWERS + "n\ny\n")
    before = (sandbox / ".env").read_text()
    env_vars = {**os.environ, "PATH": f"{sandbox / 'stubs'}:{os.environ['PATH']}"}
    subprocess.run(["bash", "setup.sh", "--accept-consent-notice"], cwd=sandbox, input="n\n",
                   text=True, capture_output=True, env=env_vars, timeout=60, check=True)
    assert (sandbox / ".env").read_text() == before


# ── The routes honour the switch ─────────────────────────────────────────

AUTH = {"role": "parent", "sub": "parent"}


@pytest.fixture
def http():
    app = FastAPI()
    app.include_router(practice_router.status_router)
    app.include_router(practice_router.router)
    app.dependency_overrides[require_parent] = lambda: AUTH
    app.dependency_overrides[require_educator] = lambda: {"role": "educator", "sub": "t"}
    app.dependency_overrides[require_auth] = lambda: AUTH
    with TestClient(app) as client:
        yield client


def _bearer():
    return {"Authorization": f"Bearer {create_access_token({'sub': 'parent', 'role': 'parent'})}"}


def test_every_practice_route_carries_the_switch():
    for route in practice_router.router.routes:
        calls = [d.call for d in route.dependant.dependencies]
        assert require_practice_coach_enabled in calls, route.path


def test_routes_answer_when_coach_is_on(http, monkeypatch):
    monkeypatch.setattr(settings, "practice_coach_enabled", True)
    assert http.get("/practice/packs", headers=_bearer()).status_code == 200
    assert http.get("/practice/status", headers=_bearer()).json() == {"enabled": True}


@pytest.mark.parametrize("method,path", [
    ("get", "/practice/packs"),
    ("get", "/practice/quiz-options"),
    ("get", "/practice/educator/quiz-options"),
    ("get", "/practice/Alice/delivery"),
    ("post", "/practice/Alice/assessments"),
    ("post", "/practice/educator/teacher-quiz/review"),
    ("get", "/practice/demo/packs"),
])
def test_routes_refuse_when_coach_is_off(http, monkeypatch, method, path):
    monkeypatch.setattr(settings, "practice_coach_enabled", False)
    resp = getattr(http, method)(path, headers=_bearer(), **({"json": {}} if method == "post" else {}))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "practice_coach_disabled"


def test_status_reports_off(http, monkeypatch):
    monkeypatch.setattr(settings, "practice_coach_enabled", False)
    assert http.get("/practice/status", headers=_bearer()).json() == {"enabled": False}


def test_the_switch_is_not_readable_without_signing_in(http, monkeypatch):
    monkeypatch.setattr(settings, "practice_coach_enabled", False)
    bad = http.get("/practice/packs", headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401
    missing = http.get("/practice/packs")
    assert missing.status_code == 401
    assert "practice_coach_disabled" not in missing.text
