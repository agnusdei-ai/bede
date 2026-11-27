"""Exercise real delivery configuration without importing media/tutoring routers."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from tests.test_wizard_and_api_agree_on_credentials import _wizard_fields

ROOT = Path(__file__).resolve().parents[2]
FLAG = "BEDE_GRADE8_CURRICULUM_ENABLED"
spec = importlib.util.spec_from_file_location(
    "grade8_delivery_wizard", ROOT / "scripts/setup_wizard/wizard.py"
)
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)


def parse(text):
    return dict(line.split("=", 1) for line in text.splitlines()
                if "=" in line and not line.startswith("#"))


def test_delivery_defaults_match_the_shared_api():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert f"{FLAG}=${{{FLAG}:-true}}" in compose["services"]["api"]["environment"]
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text())
    demo = next(s for s in blueprint["services"] if s["name"] == "bede-demo-api")
    assert [e for e in demo["envVars"] if e["key"] == FLAG] == [
        {"key": FLAG, "value": "true"}
    ]
    assert all(e["key"] != "CURRICULUM_ENGINE_ENABLED" for e in demo["envVars"])
    for example in (ROOT / ".env.example", ROOT / "homeschool-api/.env.example"):
        assert example.read_text().count(f"# {FLAG}=true") == 1


@pytest.mark.parametrize("override", [None, "false", "0", "true"])
@pytest.mark.parametrize("curriculum", ["yes", "no"])
def test_wizard_preserves_course_override_independently(tmp_path, monkeypatch, override, curriculum):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(wizard, "ENV_PATH", str(env_path))
    if override is not None:
        env_path.write_text(f"{FLAG}={override}\n")
    for _ in range(2):
        text = wizard.build_env_file(_wizard_fields(curriculum=curriculum))
        assert text.count(f"{FLAG}=") == 1
        assert parse(text)[FLAG] == (override if override is not None else "true")
        assert parse(text).get("CURRICULUM_ENGINE_ENABLED") == (
            "true" if curriculum == "yes" else None
        )
        env_path.write_text(text)


@pytest.mark.parametrize("override", [None, "false", "0", "true"])
@pytest.mark.parametrize("curriculum", ["y", "n"])
def test_terminal_installer_preserves_course_override_independently(tmp_path, override, curriculum):
    shutil.copy(ROOT / "setup.sh", tmp_path / "setup.sh")
    data = tmp_path / "homeschool-api/data"
    data.mkdir(parents=True)
    shutil.copy(ROOT / "homeschool-api/data/consent_notice.txt", data)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("docker", "curl"):
        stub = stubs / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    path = tmp_path / ".env"
    if override is not None:
        path.write_text(f"{FLAG}={override}\n")
    for run in range(2):
        overwrite = "y\n" if path.exists() else ""
        # Provider, test key, skip voice, local database, test credentials,
        # license, Practice Coach default, institutional engine choice.
        answers = overwrite + (
            "1\nsk-ant-test\n\n\nparentpass123\n805274199\nlicense-value\n\n"
            f"{curriculum}\n"
        )
        result = subprocess.run(
            ["bash", "setup.sh", "--accept-consent-notice"], cwd=tmp_path,
            input=answers, text=True, capture_output=True, timeout=60,
            env={**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}"},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        text = path.read_text()
        assert text.count(f"{FLAG}=") == 1
        assert parse(text)[FLAG] == (override if override is not None else "true")
        assert parse(text).get("CURRICULUM_ENGINE_ENABLED") == (
            "true" if curriculum == "y" else None
        )
