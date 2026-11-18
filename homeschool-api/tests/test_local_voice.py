"""
Bede's local voice (owner decisions 2026-11-18, docs/DECISIONS.md entry 46).

Four properties, each verified by breaking it:

1. The voice server (`voice-service/server.py`) speaks only in the voice for
   the requested language, keeps and logs no text, and has no route but
   /synthesize and /health (Piper's own server shows the last sentence at
   /info and downloads voices at /download).
2. LOCAL_TTS_URL is held to this machine or its private network, and bad
   voice settings are refused at boot.
3. With a local voice configured, a cloud voice is never used: not by
   default, and not when a local line fails.
4. /tutor/speak speaks in the session's own language and serves the local
   voice's WAV with its own media type.

The server is driven over real HTTP with a stand-in synthesizer, so no Piper
model is needed here.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import services.voice_synthesis as vs
from core.config import Settings, settings
from core.voice_url import VoiceUrlRefused, parse_voice_url

REPO = Path(__file__).resolve().parents[2]
SERVER_PY = REPO / "voice-service" / "server.py"
SECRET_LINE = "Remember the seven gifts, Wren"


def _load_server():
    spec = importlib.util.spec_from_file_location("bede_voice_server", SERVER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Fake:
    def __init__(self, tag: bytes, fail: bool = False):
        self.tag, self.fail, self.calls = tag, fail, 0

    def __call__(self, text: str) -> bytes:
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return b"RIFF" + self.tag


@pytest.fixture
def voice_server():
    mod = _load_server()
    started = []

    def start(voices):
        httpd = mod.serve("127.0.0.1", 0, voices)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for httpd in started:
        httpd.shutdown()
        httpd.server_close()


def _post(url, body, raw=None):
    data = raw if raw is not None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ── 1. The voice server ─────────────────────────────────────────────────────

def test_it_speaks_in_the_voice_for_the_requested_language(voice_server):
    en, es = _Fake(b"en"), _Fake(b"es")
    base = voice_server({"en": en, "es": es})
    status, ctype, body = _post(base + "/synthesize", {"text": "Hola", "locale": "es-MX"})
    assert (status, ctype, body) == (200, "audio/wav", b"RIFFes")
    assert (en.calls, es.calls) == (0, 1)


def test_a_language_with_no_voice_is_silent_never_another_languages_voice(voice_server):
    en = _Fake(b"en")
    base = voice_server({"en": en})
    status, _, body = _post(base + "/synthesize", {"text": "Hola", "locale": "es"})
    assert status == 404 and json.loads(body)["error"] == "no_voice_for_locale"
    assert en.calls == 0


def test_it_has_no_route_that_could_show_a_past_line_or_fetch_a_voice(voice_server):
    base = voice_server({"en": _Fake(b"en")})
    _post(base + "/synthesize", {"text": SECRET_LINE, "locale": "en"})
    for path in ("/", "/info", "/voices", "/all-voices"):
        status, body = _get(base + path)
        assert status == 404 and SECRET_LINE.encode() not in body
    assert _post(base + "/download", {"voice": "en_US-x"})[0] == 404
    assert json.loads(_get(base + "/health")[1]) == {"voices": ["en"]}


def test_no_text_is_logged_even_when_synthesis_fails(voice_server, caplog, capfd):
    base = voice_server({"en": _Fake(b"en", fail=True)})
    with caplog.at_level(logging.DEBUG):
        status, _, body = _post(base + "/synthesize", {"text": SECRET_LINE, "locale": "en"})
    assert status == 500 and json.loads(body)["error"] == "synthesis_failed"
    out, err = capfd.readouterr()
    assert SECRET_LINE not in caplog.text + out + err
    assert "RuntimeError" in caplog.text


def test_it_does_not_use_piper_s_own_http_server():
    src = SERVER_PY.read_text()
    assert "piper.http_server" not in src.replace("`piper.http_server`", "")
    assert "download" not in src.split("def make_handler", 1)[1].lower()


@pytest.mark.parametrize("body,raw,status", [
    ({"text": "", "locale": "en"}, None, 400),
    ({"text": "x" * 2001, "locale": "en"}, None, 400),
    ({"locale": "en"}, None, 400),
    ({"text": "hi", "locale": 7}, None, 400),
    (None, b"{not json", 400),
    (None, b"x" * (17 * 1024), 413),
])
def test_bad_requests_are_refused_without_speaking(voice_server, body, raw, status):
    fake = _Fake(b"en")
    base = voice_server({"en": fake})
    assert _post(base + "/synthesize", body, raw=raw)[0] == status
    assert fake.calls == 0


def test_voices_come_only_from_the_configured_paths():
    mod = _load_server()
    loaded = []
    voices = mod.load_voices({"BEDE_VOICE_EN": "/voices/en.onnx", "BEDE_VOICE_ES": " "},
                             factory=lambda p: loaded.append(p) or _Fake(b"x"))
    assert loaded == ["/voices/en.onnx"] and sorted(voices) == ["en"]
    with pytest.raises(SystemExit):
        mod.main({})


# ── 2. Where the voice may live, refused at boot ────────────────────────────

@pytest.mark.parametrize("url", ["http://voice:5000", "http://localhost:5000", "http://host.docker.internal:5000",
                                 "http://127.0.0.1:5000", "http://192.168.1.20:5000", "http://[::1]:5000"])
def test_local_addresses_are_accepted(url):
    assert parse_voice_url(url + "/") == url


@pytest.mark.parametrize("url", ["http://tts.example.com", "https://api.openai.com", "http://8.8.8.8:5000",
                                 "http://169.254.169.254", "http://0.0.0.0:5000", "ftp://voice",
                                 "http://u:p@voice:5000", "http://voice:5000?x=1", "voice:5000"])
def test_anything_that_could_leave_the_family_s_network_is_refused(url):
    with pytest.raises(VoiceUrlRefused):
        parse_voice_url(url)


@pytest.mark.parametrize("env,message", [
    ({"TTS_PROVIDER": "browser"}, "TTS_PROVIDER"),
    ({"LOCAL_TTS_URL": "https://tts.example.com"}, "LOCAL_TTS_URL"),
])
def test_bad_voice_settings_are_refused_at_boot(monkeypatch, env, message):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValueError, match=message):
        Settings()


def test_installed_bede_with_no_voice_set_up_boots_and_is_silent(monkeypatch):
    # TTS_PROVIDER=local is what docker-compose.yml pins; with no LOCAL_TTS_URL
    # that is installed Bede before Piper is set up, which must start and stay
    # silent rather than refuse to boot or reach for another voice.
    monkeypatch.setenv("TTS_PROVIDER", "local")
    monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
    assert Settings().tts_provider == "local"


# ── 3. Never a cloud voice when a local one is configured ───────────────────

@pytest.mark.parametrize("provider,local,key,expected", [
    ("", "http://voice:5000", "sk-test", "local"),   # local wins even with a cloud key
    ("", "", "sk-test", "openai"),                   # the demo, and families with no local voice
    ("", "", "", None),                              # no voice: silence
    ("local", "http://voice:5000", "sk-test", "local"),
    ("local", "", "sk-test", None),                  # installed Bede, Piper not set up: silence, never OpenAI
    ("openai", "http://voice:5000", "sk-test", "openai"),  # the explicit opt-in
    ("openai", "", "", None),
    ("none", "http://voice:5000", "sk-test", None),
])
def test_which_voice_speaks(monkeypatch, provider, local, key, expected):
    monkeypatch.setattr(settings, "tts_provider", provider)
    monkeypatch.setattr(settings, "local_tts_url", local)
    monkeypatch.setattr(settings, "openai_api_key", key)
    assert vs.active_provider() == expected
    assert vs.synthesis_configured() is (expected is not None)


@pytest.fixture
def local_voice(monkeypatch, voice_server):
    """A real voice server, LOCAL_TTS_URL pointing at it, an OpenAI key set,
    and OpenAI's path rigged to fail the test if it is ever reached."""
    def use(voices):
        base = voice_server(voices)
        monkeypatch.setattr(settings, "tts_provider", "")
        monkeypatch.setattr(settings, "local_tts_url", base)
        monkeypatch.setattr(settings, "openai_api_key", "sk-test")

        async def _never(text):
            raise AssertionError("a cloud voice was used while a local voice is configured")

        async def _no_sleep(_):
            return None

        monkeypatch.setattr(vs, "_synthesize_openai", _never)
        monkeypatch.setattr(vs.asyncio, "sleep", _no_sleep)
        vs._http_client = None
        return base

    yield use
    asyncio.run(vs.aclose_http_client())


def test_a_line_is_spoken_by_the_local_voice(local_voice):
    local_voice({"en": _Fake(b"en"), "es": _Fake(b"es")})
    spoken = asyncio.run(vs.synthesize_speech("Hola", locale="es"))
    assert spoken == vs.SpokenAudio(b"RIFFes", "audio/wav")


def test_a_failed_local_line_is_silent_and_never_goes_to_the_cloud(local_voice):
    fake = _Fake(b"en", fail=True)
    local_voice({"en": fake})
    assert asyncio.run(vs.synthesize_speech(SECRET_LINE, locale="en")) is None
    assert fake.calls == 2  # retried once, as the OpenAI path does


def test_a_language_with_no_local_voice_is_silent_too(local_voice):
    local_voice({"en": _Fake(b"en")})
    assert asyncio.run(vs.synthesize_speech("Hola", locale="es")) is None


# ── 4. The route a child's tablet calls ─────────────────────────────────────

def test_the_speak_route_uses_the_session_s_language_and_the_local_media_type(local_voice):
    from models.schemas import SpeakRequest
    from routers.tutor import speak

    local_voice({"en": _Fake(b"en"), "es": _Fake(b"es")})
    resp = asyncio.run(speak(SpeakRequest(text="Hola"), auth={"role": "child", "locale": "es"}))
    assert (resp.status_code, resp.media_type, resp.body) == (200, "audio/wav", b"RIFFes")
    assert resp.headers["X-TTS-Configured"] == "True"


def test_the_speak_route_is_silent_with_no_voice(monkeypatch):
    from models.schemas import SpeakRequest
    from routers.tutor import speak

    monkeypatch.setattr(settings, "tts_provider", "")
    monkeypatch.setattr(settings, "local_tts_url", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    resp = asyncio.run(speak(SpeakRequest(text="Hello"), auth={"role": "child", "locale": "en"}))
    assert resp.status_code == 204 and resp.headers["X-TTS-Configured"] == "False"


# ── 5. The container: off by default, no internet, no published port ──────

def test_the_voice_container_is_isolated_and_off_by_default():
    import yaml

    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    voice = compose["services"]["voice"]
    assert voice["profiles"] == ["local-voice"]
    assert "ports" not in voice and voice["networks"] == ["voice"]
    assert compose["networks"]["voice"]["internal"] is True
    assert "voice" in compose["services"]["api"]["networks"]
    assert voice["read_only"] is True and voice["cap_drop"] == ["ALL"]
    assert all(v.endswith(":ro") for v in voice["volumes"])
    # The API passes the voice settings through; nothing sets a default URL,
    # so no family gets the local voice until it is deliberately installed.
    api_env = compose["services"]["api"]["environment"]
    assert "LOCAL_TTS_URL=${LOCAL_TTS_URL:-}" in api_env
    # Installed Bede is Piper or silence: compose pins the provider to local.
    assert "TTS_PROVIDER=${TTS_PROVIDER:-local}" in api_env


def test_the_voice_image_installs_only_hash_locked_packages():
    dockerfile = (REPO / "voice-service" / "Dockerfile").read_text()
    assert "--require-hashes -r requirements.lock.txt" in dockerfile
    lock = (REPO / "voice-service" / "requirements.lock.txt").read_text()
    assert "piper-tts==1.8.0" in lock and "--hash=sha256:" in lock


def test_an_edit_to_the_voice_server_alone_still_runs_these_tests():
    wf = (REPO / ".github" / "workflows" / "test.yml").read_text()
    line = next(l for l in wf.splitlines() if "grep -qE" in l)
    assert "voice-service/" in line.split("'")[1].strip("^()").split("|")


@pytest.mark.parametrize("local,key,expected", [
    ("", "sk-test", {"configured": True, "where": "cloud", "available": True}),
    ("", "", {"configured": False, "where": None, "available": False}),
    ("http://127.0.0.1:9", "", {"configured": True, "where": "local", "available": False}),  # Piper down
])
def test_the_voice_status_route_says_whether_where_and_if_bede_can_speak(monkeypatch, local, key, expected):
    from routers.tutor import voice_status

    monkeypatch.setattr(settings, "tts_provider", "")
    monkeypatch.setattr(settings, "local_tts_url", local)
    monkeypatch.setattr(settings, "openai_api_key", key)
    vs._http_client = None
    try:
        assert asyncio.run(voice_status(auth={"role": "parent", "locale": "en"})) == expected
    finally:
        asyncio.run(vs.aclose_http_client())


def test_a_running_local_voice_is_available_only_in_languages_it_has(local_voice):
    from routers.tutor import voice_status

    local_voice({"en": _Fake(b"en")})
    assert asyncio.run(voice_status(auth={"role": "child", "locale": "en"}))["available"] is True
    assert asyncio.run(voice_status(auth={"role": "child", "locale": "es"}))["available"] is False


def test_checking_availability_sends_no_text_and_never_asks_the_cloud(local_voice, monkeypatch):
    calls = []
    real_get = vs._get_http_client().get

    async def spy_get(url, **kw):
        calls.append(url)
        return await real_get(url, **kw)

    local_voice({"en": _Fake(b"en")})
    monkeypatch.setattr(vs._get_http_client(), "get", spy_get)
    asyncio.run(vs.voice_available("en"))
    assert len(calls) == 1 and calls[0].endswith("/health")


def test_the_voice_server_keeps_piper_s_text_bearing_logs_out():
    # Piper logs "Missing phoneme from id map: <phoneme>" at WARNING, a piece
    # of the line being spoken. The server keeps only Piper's errors.
    mod = _load_server()
    logging.getLogger("piper").setLevel(logging.NOTSET)
    mod.quiet_piper()
    assert logging.getLogger("piper").getEffectiveLevel() == logging.ERROR
    assert logging.getLogger("piper.phoneme_ids").getEffectiveLevel() == logging.ERROR
    src = SERVER_PY.read_text()
    assert "quiet_piper()\n    voice = PiperVoice.load" in src
    assert "    quiet_piper()\n    voices = load_voices(env)" in src
