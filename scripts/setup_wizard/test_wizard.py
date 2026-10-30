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
import base64
import os
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

import wizard

# Generated once per test run rather than written as a literal. The wizard
# now refuses any PIN this repository publishes as an example, which is what
# retired the old hardcoded 602656 here — see
# homeschool-api/tests/test_wizard_and_api_agree_on_credentials.py for why a
# well-shaped PIN can still be an unusable one.
TEST_PIN = wizard.suggest_pin()

def make_synthetic_entitlement(tier="trial", expiry="2099-12-31", location=None):
    obj = {"id": "unit-fixture", "licensee": "Mock", "tier": tier, "expires": expiry}
    if location:
        obj["location_id"] = location
    value = base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return value + ".unsigned-test-only"

MOCK_ENTITLEMENT = make_synthetic_entitlement()



@pytest.fixture
def running_wizard(tmp_path, monkeypatch):
    monkeypatch.setattr(wizard, "REPO_DIR", str(tmp_path))
    monkeypatch.setattr(wizard, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setattr(wizard, "LAN_IP", "192.168.1.50")
    wizard._shutdown_event.clear()
    wizard._cancel_event.clear()
    wizard._consent.clear()

    server = wizard.ThreadingHTTPServer(("127.0.0.1", 0), wizard.Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    # Every wizard test below is about what happens AFTER the family has
    # accepted the notice; the consent step itself is covered by the
    # fresh_wizard fixture and the consent tests at the end of this file.
    _accept(base)
    yield base
    server.shutdown()
    wizard._consent.clear()


@pytest.fixture
def fresh_wizard(tmp_path, monkeypatch):
    """A wizard nobody has accepted the consent notice on yet."""
    monkeypatch.setattr(wizard, "REPO_DIR", str(tmp_path))
    monkeypatch.setattr(wizard, "ENV_PATH", str(tmp_path / ".env"))
    wizard._shutdown_event.clear()
    wizard._cancel_event.clear()
    wizard._consent.clear()
    server = wizard.ThreadingHTTPServer(("127.0.0.1", 0), wizard.Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    wizard._consent.clear()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _raw_post(base_url, path, fields=None):
    """POST without following redirects; returns (status, body)."""
    data = urllib.parse.urlencode(fields or {}).encode()
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        resp = opener.open(urllib.request.Request(f"{base_url}{path}", data=data, method="POST"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    return resp.status, resp.read().decode()


def _accept(base_url):
    status, _ = _raw_post(base_url, "/consent", {"agree": "yes"})
    assert status == 303


def _post(base_url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{base_url}/submit", data=data, method="POST")
    return urllib.request.urlopen(req)


def test_get_renders_form(running_wizard):
    resp = urllib.request.urlopen(f"{running_wizard}/")
    body = resp.read().decode()
    assert resp.status == 200
    assert "Welcome to Bede" in body
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
            "child_pin": TEST_PIN,
        })
    assert exc_info.value.code == 400
    assert "12 characters" in exc_info.value.read().decode()


def test_managed_db_without_url_rejected(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "anthropic_key": "sk-ant-test",
            "db_choice": "managed",
            "parent_password": "parentpass123",
            "child_pin": TEST_PIN,
        })
    assert exc_info.value.code == 400
    assert "connection string" in exc_info.value.read().decode()


def test_missing_license_key_rejected_without_writing_env(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "anthropic_key": "sk-ant-test",
            "db_choice": "local",
            "parent_password": "parentpass123",
            "child_pin": TEST_PIN,
        })
    assert exc_info.value.code == 400
    assert "license key" in exc_info.value.read().decode()
    assert not os.path.exists(wizard.ENV_PATH)



def test_cancel_does_not_require_license_or_save_configuration(running_wizard):
    """An operator may exit before acquiring a license, without submitting secrets."""
    req = urllib.request.Request(
        f"{running_wizard}/cancel", data=b"", method="POST"
    )
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        assert "Setup stopped" in response.read().decode()
    assert wizard._cancel_event.is_set()
    assert not os.path.exists(wizard.ENV_PATH)


def test_form_has_separate_cancel_button_and_license_guidance(running_wizard):
    body = urllib.request.urlopen(f"{running_wizard}/").read().decode()
    assert '<form action="/cancel" method="post">' in body
    assert "Cancel setup for now" in body
    assert "Enter the activation code provided for your Bede pilot" in body


def test_main_entrypoint_returns_clean_browser_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(wizard, "REPO_DIR", str(tmp_path))
    monkeypatch.setattr(wizard, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setattr(wizard, "PORT", 0)
    wizard._shutdown_event.clear()
    wizard._cancel_event.clear()
    server_holder = {}
    original_server_cls = wizard.ThreadingHTTPServer

    class _CapturingServer(original_server_cls):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            server_holder["server"] = self

    monkeypatch.setattr(wizard, "ThreadingHTTPServer", _CapturingServer)
    result = {}
    thread = threading.Thread(
        target=lambda: result.setdefault("status", wizard.main()), daemon=True
    )
    thread.start()
    for _ in range(50):
        if "server" in server_holder:
            break
        time.sleep(0.05)
    assert "server" in server_holder
    port = server_holder["server"].server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/cancel", data=b"", method="POST"
    )
    with urllib.request.urlopen(request) as response:
        assert response.status == 200
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result["status"] == 130
    assert not (tmp_path / ".env").exists()


def test_main_entrypoint_suppresses_keyboard_interrupt_traceback(monkeypatch, capsys):
    """Simulate Ctrl+C on the main thread without sending an OS signal."""
    class FakeEvent:
        def wait(self):
            raise KeyboardInterrupt

        def clear(self):
            pass

    class FakeServer:
        def serve_forever(self):
            pass

        def shutdown(self):
            self.stopped = True

        def server_close(self):
            self.closed = True

    server = FakeServer()
    monkeypatch.setattr(wizard, "_shutdown_event", FakeEvent())
    monkeypatch.setattr(wizard, "ThreadingHTTPServer", lambda *args: server)
    assert wizard.main() == 130
    assert server.stopped and server.closed
    output = capsys.readouterr()
    assert "setup canceled" in output.out.lower()
    assert "Traceback" not in output.err


def test_valid_local_db_submission_writes_correct_env(running_wizard):
    resp = _post(running_wizard, {
        "anthropic_key": "sk-ant-real-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
    })
    assert resp.status == 200
    success_body = resp.read().decode()
    assert "Starting Bede" in success_body
    assert "https://localhost" in success_body

    assert os.path.exists(wizard.ENV_PATH)
    env = open(wizard.ENV_PATH).read()
    assert "ANTHROPIC_API_KEY=sk-ant-real-key" in env
    assert "COMPOSE_PROFILES=local-db" in env
    assert "POSTGRES_PASSWORD=" in env
    assert "@db:5432/bede" in env
    assert "PARENT_PASSWORD=parentpass123" in env
    assert f"CHILD_PIN={TEST_PIN}" in env
    assert f"LICENSE_KEY={MOCK_ENTITLEMENT}" in env
    assert "CORS_ORIGINS=https://localhost,https://192.168.1.50,http://ui:80" in env

    mode = stat.S_IMODE(os.stat(wizard.ENV_PATH).st_mode)
    assert mode == 0o600


def test_valid_openai_submission_writes_correct_env(running_wizard):
    resp = _post(running_wizard, {
        "provider": "openai",
        "openai_key": "sk-proj-real-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
            "child_pin": TEST_PIN,
            "license_key": MOCK_ENTITLEMENT,
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
            "child_pin": TEST_PIN,
            "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
            "child_pin": TEST_PIN,
            "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
    })
    env = open(wizard.ENV_PATH).read()
    assert "COMPOSE_PROFILES" not in env
    assert "DATABASE_URL=postgresql://user:pass@neon.example/db" in env


def test_resubmission_backs_up_previous_env(running_wizard):
    _post(running_wizard, {
        "anthropic_key": "sk-ant-first",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
    })
    _post(running_wizard, {
        "anthropic_key": "sk-ant-second",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
    })
    assert os.path.exists(wizard.ENV_PATH + ".backup")
    assert "sk-ant-first" in open(wizard.ENV_PATH + ".backup").read()
    assert "sk-ant-second" in open(wizard.ENV_PATH).read()


def test_shutdown_signal_fires_after_success(running_wizard):
    _post(running_wizard, {
        "anthropic_key": "sk-ant-test",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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

    _accept(f"http://127.0.0.1:{port}")
    _post(f"http://127.0.0.1:{port}", {
        "anthropic_key": "sk-ant-test",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
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
        "child_pin": TEST_PIN,
        "license_key": MOCK_ENTITLEMENT,
    })
    assert resp.status == 200
    env = open(wizard.ENV_PATH).read()
    assert "RETAIN_MASTERY_PROFILES" not in env


def test_the_question_is_actually_shown(running_wizard):
    body = urllib.request.urlopen(f"{running_wizard}/").read().decode()
    assert "mastered between sessions" in body
    assert 'name="keep_mastery" value="yes"' in body
    assert 'name="keep_mastery" value="no"' in body


# ── Published example credentials (the bug that turned main red) ─────────
#
# The wizard used to print "e.g. 602656 is a good one" as its own hint and
# use it as the input's placeholder, then accept it. The API refuses to boot
# on it, because a PIN published in this repository is not a secret. So the
# installer recommended a value that made the parent's stack fail to start,
# and reported the failure as their own insecure default. These pin the
# wizard half; the agreement between the two halves is asserted in
# homeschool-api/tests/test_wizard_and_api_agree_on_credentials.py.

def test_the_published_example_pin_is_refused(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "anthropic_key": "sk-ant-real-key",
            "db_choice": "local",
            "parent_password": "parentpass123",
            "child_pin": "602656",
            "license_key": MOCK_ENTITLEMENT,
        })
    assert exc_info.value.code == 400
    assert "published example" in exc_info.value.read().decode()
    assert not os.path.exists(wizard.ENV_PATH), (
        "the wizard wrote an .env the API would refuse to boot on"
    )


def test_the_form_recommends_a_generated_pin_not_a_published_one(running_wizard):
    body = urllib.request.urlopen(f"{running_wizard}/").read().decode()
    assert "602656" not in body
    assert wizard.SUGGESTED_CHILD_PIN in body


def test_the_suggested_pin_is_actually_accepted(running_wizard):
    """A suggestion the form then rejects would be the same defect wearing a
    different value."""
    resp = _post(running_wizard, {
        "anthropic_key": "sk-ant-real-key",
        "db_choice": "local",
        "parent_password": "parentpass123",
        "child_pin": wizard.SUGGESTED_CHILD_PIN,
        "license_key": MOCK_ENTITLEMENT,
    })
    assert resp.status == 200
    assert f"CHILD_PIN={wizard.SUGGESTED_CHILD_PIN}" in open(wizard.ENV_PATH).read()


def test_campus_pilot_location_is_written_only_when_approved(monkeypatch):
    """The site bound license must reach the API in campus mode."""
    monkeypatch.setattr(wizard, "DEPLOYMENT_CONTEXT", "campus")
    monkeypatch.setattr(wizard, "APPROVED_CAMPUS_ID", "bede-mac-pilot-2026")
    fields = {
        "db_choice": "local",
        "provider": "openai",
        "openai_key": "local-test-value",
        "parent_password": "pilot-test-password-unique",
        "child_pin": "648219",
        "license_key": MOCK_ENTITLEMENT,
        "location_id": "bede-mac-pilot-2026",
    }
    rendered = wizard.render_form()
    assert 'name="location_id"' in rendered
    assert 'name="child_pin"' in rendered
    assert 'type="hidden" name="child_pin"' in rendered
    assert 'Student PIN</label>' not in rendered
    fields["license_key"] = make_synthetic_entitlement(tier="campus_location", location="bede-mac-pilot-2026")
    assert wizard.validate(fields) == ""
    generated = wizard.build_env_file(fields)
    assert "BEDE_LOCATION_ID=bede-mac-pilot-2026\n" in generated
    assert "EDUCATOR_PILOT_ENABLED=true\n" in generated
    assert ("LICENSE_KEY=" + fields["license_key"] + "\n") in generated
    from pathlib import Path
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    assert "- BEDE_LOCATION_ID=${BEDE_LOCATION_ID:-}" in compose
    assert "- EDUCATOR_PILOT_ENABLED=${EDUCATOR_PILOT_ENABLED:-false}" in compose

    fields["location_id"] = ""
    assert "campus ID" in wizard.validate(fields)
    fields["location_id"] = "other-campus"
    assert "campus ID" in wizard.validate(fields)

    monkeypatch.setattr(wizard, "DEPLOYMENT_CONTEXT", "homeschool")
    fields["location_id"] = ""
    assert wizard.validate(fields) == ""
    assert "BEDE_LOCATION_ID" not in wizard.build_env_file(fields)
    assert "EDUCATOR_PILOT_ENABLED=true" not in wizard.build_env_file(fields)


def test_weak_administrator_password_rejected_without_configuration(running_wizard):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(running_wizard, {
            "anthropic_key": "sk-ant-test",
            "db_choice": "local",
            "parent_password": "Password",
            "child_pin": TEST_PIN,
            "license_key": MOCK_ENTITLEMENT,
        })
    assert exc_info.value.code == 400
    assert "12 characters" in exc_info.value.read().decode()
    assert not os.path.exists(wizard.ENV_PATH)


def test_wizard_waits_for_native_certificate_approval(running_wizard):
    html = wizard.render_success()
    assert 'href="https://localhost"' not in html
    assert "native installer verifies certificate trust" in html

def test_expired_pilot_entitlement_has_actionable_error():
    error = wizard.license_preflight_error(
        make_synthetic_entitlement(expiry="2025-01-01"), "homeschool", ""
    )
    assert "expired on 2025-01-01" in error

def test_wrong_campus_entitlement_is_rejected():
    error = wizard.license_preflight_error(
        make_synthetic_entitlement(tier="campus_location", location="elsewhere"),
        "campus", "approved-campus"
    )
    assert "different campus" in error

def test_invalid_entitlement_is_rejected():
    assert "format is invalid" in wizard.license_preflight_error(
        "not-an-entitlement", "homeschool", ""
    )


# ── Parental-consent step (install time) ──────────────────────────────────
#
# A self-hosting family gives consent at install, with the notice in front of
# them. Declining must leave NOTHING behind: no .env, no start. The hash the
# installer records must be the hash of the real notice file's bytes, because
# the API accepts the acknowledgement only on an exact match.

import hashlib
import re
from pathlib import Path

NOTICE_FILE = Path(__file__).resolve().parents[2] / "homeschool-api" / "data" / "consent_notice.txt"
VALID_FIELDS = {
    "anthropic_key": "sk-ant-test",
    "db_choice": "local",
    "parent_password": "parentpass123",
    "child_pin": TEST_PIN,
    "license_key": MOCK_ENTITLEMENT,
}


def test_first_page_is_the_notice_not_the_setup_form(fresh_wizard):
    body = urllib.request.urlopen(f"{fresh_wizard}/").read().decode()
    assert "Notice version:" in body
    assert "Parental Notice and Consent" in body
    assert "I Consent and Continue" in body
    assert "does not transmit a child" in body
    assert 'name="anthropic_key"' not in body


def test_accepting_writes_both_ack_lines_with_the_real_hash(fresh_wizard, tmp_path):
    _accept(fresh_wizard)
    _post(fresh_wizard, VALID_FIELDS)
    env = (tmp_path / ".env").read_text()
    expected = hashlib.sha256(NOTICE_FILE.read_bytes()).hexdigest()
    assert f"CONSENT_INSTALL_ACK_HASH={expected}\n" in env
    m = re.search(r"^CONSENT_INSTALL_ACK_AT=(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)$", env, re.M)
    assert m, env


def test_submit_without_consent_is_refused_and_writes_nothing(fresh_wizard, tmp_path):
    status, _ = _raw_post(fresh_wizard, "/submit", VALID_FIELDS)
    assert status == 403
    assert not (tmp_path / ".env").exists()


def test_unticked_checkbox_cannot_proceed(fresh_wizard, tmp_path):
    status, body = _raw_post(fresh_wizard, "/consent", {})
    assert status == 400 and "tick the consent box" in body
    status, _ = _raw_post(fresh_wizard, "/submit", VALID_FIELDS)
    assert status == 403
    assert not (tmp_path / ".env").exists()


def test_declining_shows_not_completed_and_writes_nothing(fresh_wizard, tmp_path):
    status, body = _raw_post(fresh_wizard, "/decline")
    assert status == 200 and "Installation not completed" in body
    assert wizard._cancel_event.is_set()
    status, _ = _raw_post(fresh_wizard, "/submit", VALID_FIELDS)
    assert status == 403
    assert not (tmp_path / ".env").exists()


def test_main_exits_nonzero_when_the_notice_is_declined(tmp_path, monkeypatch):
    monkeypatch.setattr(wizard, "REPO_DIR", str(tmp_path))
    monkeypatch.setattr(wizard, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setattr(wizard, "PORT", 0)
    wizard._shutdown_event.clear()
    holder = {}
    base_cls = wizard.ThreadingHTTPServer

    class _Capture(base_cls):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            holder["server"] = self

    monkeypatch.setattr(wizard, "ThreadingHTTPServer", _Capture)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("rc", wizard.main()), daemon=True)
    t.start()
    for _ in range(50):
        if "server" in holder:
            break
        time.sleep(0.05)
    _raw_post(f"http://127.0.0.1:{holder['server'].server_address[1]}", "/decline")
    t.join(timeout=5)
    assert not t.is_alive()
    assert result["rc"] != 0
    assert not (tmp_path / ".env").exists()


def test_wizard_image_ships_the_notice_file():
    dockerfile = (Path(__file__).parent / "Dockerfile").read_text()
    assert "COPY homeschool-api/data/consent_notice.txt /app/consent_notice.txt" in dockerfile
    assert wizard._CONSENT_NOTICE_CANDIDATES[0] == Path("/app/consent_notice.txt")
