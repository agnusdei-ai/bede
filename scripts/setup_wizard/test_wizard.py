"""
Regression tests for the browser-based setup wizard's actual server logic
(form rendering, validation, .env generation, resubmission/backup behavior,
and the exit-on-success signal the launcher scripts depend on).

This deliberately does NOT test the Docker packaging itself (building the
image, running the container, the launcher scripts) — that needs a real
Docker daemon and is covered instead by
.github/workflows/production-regression.yml, which runs in CI where a
daemon is actually available.
"""
import json
import os
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

import wizard


@pytest.fixture
def running_wizard(tmp_path, monkeypatch):
    monkeypatch.setattr(wizard, "REPO_DIR", str(tmp_path))
    monkeypatch.setattr(wizard, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setattr(wizard, "LAN_IP", "192.168.1.50")
    wizard._shutdown_event.clear()

    server = wizard.ThreadingHTTPServer(("127.0.0.1", 0), wizard.Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def _post(base_url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{base_url}/submit", data=data, method="POST")
    return urllib.request.urlopen(req)


def test_get_renders_form(running_wizard):
    resp = urllib.request.urlopen(f"{running_wizard}/")
    body = resp.read().decode()
    assert resp.status == 200
    assert "Let's set up Bede" in body
    assert 'name="anthropic_key"' in body


def test_get_renders_all_four_provider_choices(running_wizard):
    """No single vendor should be baked into the form — a family can pick
    any of the four adapters services/adapters/ supports, including the
    open, no-account local self-hosted option."""
    body = urllib.request.urlopen(f"{running_wizard}/").read().decode()
    for value in ("anthropic", "openai", "mistral", "local"):
        assert f'name="provider" value="{value}"' in body
    assert 'name="openai_key"' in body
    assert 'name="mistral_key"' in body
    assert 'name="local_base_url"' in body


def test_weak_pin_rejected_without_writing_env(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "anthropic_key": "sk-ant-test",
            "db_choice": "local",
            "parent_password": "parentpass123",
            "child_pin": "111111",
        })
    assert exc_info.value.code == 400
    assert "obvious pattern" in exc_info.value.read().decode()
    assert not os.path.exists(wizard.ENV_PATH)


def test_short_parent_password_rejected(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "anthropic_key": "sk-ant-test",
            "db_choice": "local",
            "parent_password": "short",
            "child_pin": "602656",
        })
    assert exc_info.value.code == 400
    assert "8 characters" in exc_info.value.read().decode()


def test_managed_db_without_url_rejected(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "anthropic_key": "sk-ant-test",
            "db_choice": "managed",
            "parent_password": "parentpass123",
            "child_pin": "602656",
        })
    assert exc_info.value.code == 400
    assert "connection string" in exc_info.value.read().decode()


def test_missing_license_key_rejected_without_writing_env(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "anthropic_key": "sk-ant-test",
            "db_choice": "local",
            "parent_password": "parentpass123",
            "child_pin": "602656",
        })
    assert exc_info.value.code == 400
    assert "license key" in exc_info.value.read().decode()
    assert not os.path.exists(wizard.ENV_PATH)


def test_valid_local_db_submission_writes_correct_env(running_wizard):
    resp = _post(running_wizard, {
        "anthropic_key": "sk-ant-real-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    assert resp.status == 200
    success_body = resp.read().decode()
    assert "All set" in success_body
    assert "192.168.1.50" in success_body

    assert os.path.exists(wizard.ENV_PATH)
    env = open(wizard.ENV_PATH).read()
    assert "ANTHROPIC_API_KEY=sk-ant-real-key" in env
    assert "COMPOSE_PROFILES=local-db" in env
    assert "POSTGRES_PASSWORD=" in env
    assert "@db:5432/bede" in env
    assert "PARENT_PASSWORD=parentpass123" in env
    assert "CHILD_PIN=602656" in env
    assert "LICENSE_KEY=eyJ.test-license-key" in env
    assert "CORS_ORIGINS=https://localhost,https://192.168.1.50,http://ui:80" in env

    mode = stat.S_IMODE(os.stat(wizard.ENV_PATH).st_mode)
    assert mode == 0o600


def test_valid_openai_submission_writes_correct_env(running_wizard):
    resp = _post(running_wizard, {
        "provider": "openai",
        "openai_key": "sk-proj-real-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    assert resp.status == 200
    env = open(wizard.ENV_PATH).read()
    assert "BEDE_ADAPTER_ORDER=openai" in env
    assert "OPENAI_API_KEY=sk-proj-real-key" in env
    assert "ANTHROPIC_API_KEY" not in env


def test_valid_mistral_submission_writes_correct_env(running_wizard):
    _post(running_wizard, {
        "provider": "mistral",
        "mistral_key": "real-mistral-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    env = open(wizard.ENV_PATH).read()
    assert "BEDE_ADAPTER_ORDER=mistral" in env
    assert "MISTRAL_API_KEY=real-mistral-key" in env
    assert "ANTHROPIC_API_KEY" not in env


def test_valid_local_submission_writes_correct_env(running_wizard):
    """The actual open, no-account path — no vendor credential at all."""
    _post(running_wizard, {
        "provider": "local",
        "local_base_url": "http://gpu-box.lan:8000/v1",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    env = open(wizard.ENV_PATH).read()
    assert "BEDE_ADAPTER_ORDER=local" in env
    assert "LOCAL_LLM_BASE_URL=http://gpu-box.lan:8000/v1" in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "MISTRAL_API_KEY" not in env


def test_missing_credential_for_chosen_provider_rejected(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "provider": "openai",
            "db_choice": "local",
            "parent_password": "parentpass123",
            "child_pin": "602656",
            "license_key": "eyJ.test-license-key",
        })
    assert exc_info.value.code == 400
    assert "OpenAI API key" in exc_info.value.read().decode()
    assert not os.path.exists(wizard.ENV_PATH)


def test_missing_local_server_url_rejected(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "provider": "local",
            "db_choice": "local",
            "parent_password": "parentpass123",
            "child_pin": "602656",
            "license_key": "eyJ.test-license-key",
        })
    assert exc_info.value.code == 400
    assert "model server" in exc_info.value.read().decode()
    assert not os.path.exists(wizard.ENV_PATH)


def _write_local_ai_marker(tmp_path, model="qwen3:8b", base_url="http://host.docker.internal:11434/v1"):
    (tmp_path / wizard.LOCAL_AI_MARKER_NAME).write_text(
        json.dumps({"base_url": base_url, "model": model})
    )


def test_local_auto_choice_hidden_without_marker(running_wizard):
    """The Windows-installer-only path is invisible everywhere else — no
    marker file means no "run on this computer" option at all, and the
    long-standing anthropic default is unchanged."""
    body = urllib.request.urlopen(f"{running_wizard}/").read().decode()
    assert 'value="local_auto"' not in body
    assert 'checked' in body  # something is still checked by default...
    assert 'value="anthropic" onclick="showProvider(\'anthropic\')" checked' in body


def test_local_auto_choice_shown_and_preselected_with_marker(running_wizard, tmp_path):
    """Setup-Bede.ps1 already installed Ollama and pulled a model before
    this container even started — the wizard should offer it as the
    recommended, pre-selected choice rather than making the family retype
    anything Setup-Bede.ps1 already figured out."""
    _write_local_ai_marker(tmp_path, model="qwen3:8b")
    body = urllib.request.urlopen(f"{running_wizard}/").read().decode()
    assert 'name="provider" value="local_auto"' in body
    assert 'value="local_auto" onclick="showProvider(\'local_auto\')" checked' in body
    assert "Using qwen3:8b" in body
    # No credential field, no URL to type — it's already configured.
    assert 'name="local_auto_' not in body


def test_valid_local_auto_submission_writes_correct_env_and_cleans_up_marker(running_wizard, tmp_path):
    _write_local_ai_marker(tmp_path, model="qwen3:8b", base_url="http://host.docker.internal:11434/v1")
    resp = _post(running_wizard, {
        "provider": "local_auto",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    assert resp.status == 200
    env = open(wizard.ENV_PATH).read()
    assert "BEDE_ADAPTER_ORDER=local" in env
    assert "LOCAL_LLM_BASE_URL=http://host.docker.internal:11434/v1" in env
    assert "LOCAL_LLM_MODEL=qwen3:8b" in env
    assert "ANTHROPIC_API_KEY" not in env

    # Transient install-time state — not something a family should find
    # lying around afterward.
    assert not (tmp_path / wizard.LOCAL_AI_MARKER_NAME).exists()


def test_local_auto_without_marker_rejected(running_wizard):
    """Defense-in-depth: even if provider=local_auto is submitted directly
    (stale form, direct POST) with no marker file backing it, this must be
    rejected rather than writing a broken LOCAL_LLM_BASE_URL=None."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "provider": "local_auto",
            "db_choice": "local",
            "parent_password": "parentpass123",
            "child_pin": "602656",
            "license_key": "eyJ.test-license-key",
        })
    assert exc_info.value.code == 400
    assert "Local AI setup" in exc_info.value.read().decode()
    assert not os.path.exists(wizard.ENV_PATH)


def test_choosing_a_cloud_provider_still_cleans_up_a_leftover_marker(running_wizard, tmp_path):
    """A family can still change their mind to a cloud provider even after
    Setup-Bede.ps1 set up local AI — the unused marker shouldn't linger."""
    _write_local_ai_marker(tmp_path)
    _post(running_wizard, {
        "provider": "anthropic",
        "anthropic_key": "sk-ant-test",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    env = open(wizard.ENV_PATH).read()
    assert "BEDE_ADAPTER_ORDER=anthropic" in env
    assert not (tmp_path / wizard.LOCAL_AI_MARKER_NAME).exists()


def test_omitted_provider_field_defaults_to_anthropic(running_wizard):
    """Backward-compat: a submission with no `provider` field at all (an
    old cached form, a direct API caller) still resolves to the
    long-standing default rather than erroring confusingly."""
    _post(running_wizard, {
        "anthropic_key": "sk-ant-default-path",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    env = open(wizard.ENV_PATH).read()
    assert "BEDE_ADAPTER_ORDER=anthropic" in env
    assert "ANTHROPIC_API_KEY=sk-ant-default-path" in env


def test_valid_managed_db_submission_has_no_local_db_settings(running_wizard):
    _post(running_wizard, {
        "anthropic_key": "sk-ant-test",
        "db_choice": "managed",
        "database_url": "postgresql://user:pass@neon.example/db",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    env = open(wizard.ENV_PATH).read()
    assert "COMPOSE_PROFILES" not in env
    assert "DATABASE_URL=postgresql://user:pass@neon.example/db" in env


def test_resubmission_backs_up_previous_env(running_wizard):
    _post(running_wizard, {
        "anthropic_key": "sk-ant-first",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    _post(running_wizard, {
        "anthropic_key": "sk-ant-second",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    assert os.path.exists(wizard.ENV_PATH + ".backup")
    assert "sk-ant-first" in open(wizard.ENV_PATH + ".backup").read()
    assert "sk-ant-second" in open(wizard.ENV_PATH).read()


def test_shutdown_signal_fires_after_success(running_wizard):
    _post(running_wizard, {
        "anthropic_key": "sk-ant-test",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    assert wizard._shutdown_event.wait(timeout=2) is True


def test_audio_serves_existing_file(running_wizard, tmp_path, monkeypatch):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "welcome.wav").write_bytes(b"RIFF....fake-wav-bytes")
    monkeypatch.setattr(wizard, "AUDIO_DIR", audio_dir)

    resp = urllib.request.urlopen(f"{running_wizard}/audio/welcome.wav")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "audio/wav"
    assert resp.read() == b"RIFF....fake-wav-bytes"


def test_audio_missing_file_404s_without_crashing(running_wizard, tmp_path, monkeypatch):
    monkeypatch.setattr(wizard, "AUDIO_DIR", tmp_path / "audio")  # doesn't exist
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_wizard}/audio/welcome.wav")
    assert exc_info.value.code == 404


def test_audio_rejects_unknown_filenames(running_wizard):
    """Only the fixed, known clip names are servable — closes off path
    traversal or probing for arbitrary files even though this is a
    short-lived, localhost-only container."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_wizard}/audio/../../../etc/passwd")
    assert exc_info.value.code == 404


def test_form_page_includes_narration_and_mic_controls(running_wizard):
    body = urllib.request.urlopen(f"{running_wizard}/").read().decode()
    assert "playNarration('welcome')" in body
    assert "toggleVoiceCommands" in body
    assert "always type your password, PIN, and provider credentials" in body
    # Voice commands must never target secret input fields by name.
    assert 'name=parent_password' not in body
    assert 'name=child_pin' not in body
    assert 'name=anthropic_key' not in body
    assert 'name=openai_key' not in body
    assert 'name=mistral_key' not in body
    assert 'name=local_base_url' not in body
    assert 'name=license_key' not in body


def test_success_page_includes_narration_but_no_mic(running_wizard):
    resp = _post(running_wizard, {
        "anthropic_key": "sk-ant-test",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    body = resp.read().decode()
    assert "playNarration('success')" in body
    assert "toggleVoiceCommands" not in body


def test_main_entrypoint_exits_after_successful_submission(tmp_path, monkeypatch):
    """The actual real entrypoint (not just the Handler class in isolation)
    — this is the exact exit signal the launcher scripts depend on to know
    the wizard finished and it's safe to proceed with `docker compose up`."""
    monkeypatch.setattr(wizard, "REPO_DIR", str(tmp_path))
    monkeypatch.setattr(wizard, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setattr(wizard, "PORT", 0)
    wizard._shutdown_event.clear()

    server_holder = {}
    original_server_cls = wizard.ThreadingHTTPServer

    class _CapturingServer(original_server_cls):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            server_holder["server"] = self

    monkeypatch.setattr(wizard, "ThreadingHTTPServer", _CapturingServer)

    main_thread = threading.Thread(target=wizard.main, daemon=True)
    main_thread.start()
    for _ in range(50):
        if "server" in server_holder:
            break
        time.sleep(0.05)
    port = server_holder["server"].server_address[1]

    _post(f"http://127.0.0.1:{port}", {
        "anthropic_key": "sk-ant-test",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    main_thread.join(timeout=5)
    assert main_thread.is_alive() is False


# ── Mastery retention (RETAIN_MASTERY_PROFILES) ──────────────────────────
#
# The setting exists so a family can run the full diagnostic without Bede
# keeping a lasting estimate of their child. It was reachable only by
# hand-editing .env, which the whole point of this wizard is to avoid — so
# for the people it was built for it may as well not have existed. These
# pin the choice reaching the file it has to reach.

def test_choosing_not_to_keep_mastery_writes_the_setting(running_wizard):
    resp = _post(running_wizard, {
        "anthropic_key": "sk-ant-real-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
        "keep_mastery": "no",
    })
    assert resp.status == 200
    env = open(wizard.ENV_PATH).read()
    assert "RETAIN_MASTERY_PROFILES=false" in env


def test_the_default_install_writes_nothing_about_retention(running_wizard):
    """Silence and "yes" have to agree: the code default is True, so an
    ordinary install's .env should stay free of a setting nobody picked
    rather than restating the default back at itself."""
    resp = _post(running_wizard, {
        "anthropic_key": "sk-ant-real-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
        "keep_mastery": "yes",
    })
    assert resp.status == 200
    env = open(wizard.ENV_PATH).read()
    assert "RETAIN_MASTERY_PROFILES" not in env


def test_an_older_form_with_no_answer_keeps_todays_behaviour(running_wizard):
    """A submission from before this question existed must not silently
    switch a family onto the stricter posture."""
    resp = _post(running_wizard, {
        "anthropic_key": "sk-ant-real-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": "602656",
        "license_key": "eyJ.test-license-key",
    })
    assert resp.status == 200
    env = open(wizard.ENV_PATH).read()
    assert "RETAIN_MASTERY_PROFILES" not in env


def test_the_question_is_actually_shown(running_wizard):
    body = urllib.request.urlopen(f"{running_wizard}/").read().decode()
    assert "mastered between sessions" in body
    assert 'name="keep_mastery" value="yes"' in body
    assert 'name="keep_mastery" value="no"' in body
