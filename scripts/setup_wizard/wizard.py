#!/usr/bin/env python3
"""
Bede's browser-based setup wizard — the non-technical alternative to
setup.sh's terminal prompts. Runs inside a small Docker container (see
Dockerfile in this directory); a launcher script on the host (setup-gui.command
/ setup-gui.sh / setup-gui.bat, repo root) starts this container, opens the
parent's browser to it, waits for it to exit, then runs the actual
`docker compose up -d --build` on the host — this container's only job is to
collect answers and write a correct .env file to the mounted repo directory.

Deliberately pure standard library — no Flask/FastAPI — so the Docker image
stays tiny and there's nothing to explain about extra dependencies for what
is, functionally, one short-lived form.
"""
import html
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

# Inside the real Docker image (see Dockerfile in this directory), the
# Dockerfile COPYs core/pin_policy.py to /app/homeschool-api/core/. For
# tests running directly against this file (no Docker), fall back to the
# actual repo layout (../../homeschool-api relative to this file) instead
# of requiring a fake /app directory to exist on the test machine.
_CONTAINER_PATH = "/app/homeschool-api"
_REPO_PATH = str(Path(__file__).resolve().parent.parent.parent / "homeschool-api")
sys.path.insert(0, _CONTAINER_PATH if os.path.isdir(_CONTAINER_PATH) else _REPO_PATH)
from core.pin_policy import pin_is_strong  # noqa: E402
# Deliberately NOT importing core.licensing here — real signature
# verification needs pycryptodome, and this container stays pure-stdlib on
# purpose (see module docstring). This form only checks the field is
# non-empty; core/config.py does the real cryptographic/expiry check when
# the actual API container boots — if that rejects it, `make logs` shows
# why (see docs/PRODUCTION_SETUP.md#licensing).

REPO_DIR = "/repo"
ENV_PATH = os.path.join(REPO_DIR, ".env")
PORT = int(os.environ.get("WIZARD_PORT", "8765"))
LAN_IP = os.environ.get("HOST_LAN_IP", "").strip()

# Optional spoken narration, in Bede's own configured voice (OpenAI TTS,
# fable) — generated once by scripts/setup_wizard/generate_narration.py and
# committed as static assets, never called live. If a family never ran that
# script, AUDIO_DIR is empty and _serve_audio() below 404s; the page's JS
# treats that as "no narration available" and just hides the controls —
# the wizard functions identically either way.
AUDIO_DIR = Path(__file__).resolve().parent / "audio"
_AUDIO_FILES = {"welcome.wav", "success.wav"}

_shutdown_event = threading.Event()

_PAGE_HEAD = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Set up Bede</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f7f3ec; color: #2d3142; max-width: 640px; margin: 0 auto;
         padding: 32px 20px; line-height: 1.5; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  .sub { color: #6b7280; margin-top: 0; margin-bottom: 28px; }
  label { display: block; font-weight: 600; margin-top: 20px; margin-bottom: 6px; }
  .hint { font-weight: 400; color: #6b7280; font-size: 13px; margin-top: 2px; }
  input[type=text], input[type=password] {
    width: 100%; box-sizing: border-box; padding: 10px 12px; font-size: 15px;
    border: 1px solid #d1d5db; border-radius: 8px;
  }
  .choice { border: 2px solid #e5e7eb; border-radius: 10px; padding: 14px 16px;
            margin-top: 10px; cursor: pointer; }
  .choice.selected { border-color: #2b4c7e; background: #eef2f8; }
  .choice input { margin-right: 8px; }
  .choice-title { font-weight: 600; }
  .choice-desc { color: #6b7280; font-size: 13px; margin-top: 2px; }
  button { margin-top: 28px; width: 100%; padding: 14px; font-size: 16px;
           font-weight: 600; color: white; background: #2b4c7e; border: none;
           border-radius: 10px; cursor: pointer; }
  button:hover { background: #1f3a63; }
  .error { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b;
           padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; }
  .success { text-align: center; padding: 40px 20px; }
  a { color: #2b4c7e; }
  .narration-bar { display: none; align-items: center; gap: 10px; flex-wrap: wrap;
                    background: #eef2f8; border-radius: 10px; padding: 10px 14px;
                    margin-bottom: 20px; }
  .narration-btn, .mic-btn { padding: 8px 14px; font-size: 14px; font-weight: 600;
    border: 1px solid #2b4c7e; border-radius: 20px; background: white;
    color: #2b4c7e; cursor: pointer; }
  .narration-btn:hover, .mic-btn:hover { background: #e0e7f2; }
  .mic-btn.on { background: #2b4c7e; color: white; }
  .mic-status { font-size: 13px; color: #6b7280; flex-basis: 100%; }
  .voice-hint { font-size: 12px; color: #6b7280; flex-basis: 100%; }
</style>
</head>
<body>
"""
_PAGE_TAIL = "</body></html>"


def _narration_block(clip: str, enable_mic: bool) -> str:
    """Spoken narration (bookends only — welcome/success, not every field)
    plus, on the form page, opt-in voice commands for CHOICES and
    NAVIGATION only. Voice input is never wired to the password, PIN, or
    API key fields — those must always be typed, both for privacy (nobody
    wants their password spoken aloud near a listening microphone) and
    because speech recognition mishears exactly the kind of arbitrary
    strings those fields hold.
    """
    mic_markup = ""
    mic_script = ""
    if enable_mic:
        mic_markup = (
            '<button type="button" id="mic-toggle" class="mic-btn" '
            'style="display:none" onclick="toggleVoiceCommands()">'
            '🎤 Voice commands: off</button>'
            '<div class="voice-hint">Voice commands only control choices and '
            'navigation (e.g. "on this computer", "submit") — always type '
            'your password, PIN, and API key.</div>'
        )
        # Deliberately built as a separate string, included only when
        # enable_mic is True — omitted entirely (not just runtime-guarded)
        # on pages like the success screen with nothing left to command.
        mic_script = f"""
      var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      var micBtn = document.getElementById('mic-toggle');
      var micStatus = document.getElementById('mic-status');
      if (Recognition) {{
        micBtn.style.display = 'inline-block';

        var listening = false;
        var recognition = null;

        var handleCommand = function(text) {{
          var t = text.toLowerCase();
          if (/local|this computer/.test(t)) {{
            var el = document.querySelector('input[name=db_choice][value=local]');
            if (el) el.click();
            micStatus.textContent = 'Heard: "' + text + '" — selected "on this computer."';
          }} else if (/cloud|managed|my own database/.test(t)) {{
            var el2 = document.querySelector('input[name=db_choice][value=managed]');
            if (el2) el2.click();
            micStatus.textContent = 'Heard: "' + text + '" — selected "cloud database."';
          }} else if (/replay|repeat|say that again/.test(t)) {{
            micStatus.textContent = 'Heard: "' + text + '" — replaying.';
            playNarration('{clip}');
          }} else if (/submit|set up bede|continue|go ahead/.test(t)) {{
            micStatus.textContent = 'Heard: "' + text + '" — submitting.';
            var form = document.querySelector('form');
            if (form) form.requestSubmit();
          }} else {{
            micStatus.textContent = 'Didn\\'t catch a command in: "' + text + '"';
          }}
        }};

        window.toggleVoiceCommands = function() {{
          listening = !listening;
          if (listening) {{
            recognition = new Recognition();
            recognition.lang = 'en-US';
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.onresult = function(e) {{ handleCommand(e.results[0][0].transcript); }};
            recognition.onerror = function() {{ micStatus.textContent = "Didn't catch that."; }};
            recognition.onend = function() {{ if (listening) recognition.start(); }};
            recognition.start();
            micBtn.textContent = '🎤 Voice commands: on';
            micBtn.classList.add('on');
            micStatus.textContent = 'Listening for "on this computer", "cloud database", "submit"...';
          }} else {{
            if (recognition) recognition.stop();
            micBtn.textContent = '🎤 Voice commands: off';
            micBtn.classList.remove('on');
            micStatus.textContent = '';
          }}
        }};
      }}
        """

    return f"""
    <audio id="narration-audio" style="display:none"></audio>
    <div class="narration-bar" id="narration-bar">
      <button type="button" id="narration-replay" class="narration-btn"
        onclick="playNarration('{clip}')">🔊 Hear this from Bede</button>
      {mic_markup}
      <div class="mic-status" id="mic-status"></div>
    </div>
    <script>
    (function() {{
      var audio = document.getElementById('narration-audio');
      var bar = document.getElementById('narration-bar');
      var available = true;

      audio.addEventListener('error', function() {{
        available = false;
        bar.style.display = 'none';
      }});
      audio.addEventListener('loadeddata', function() {{
        bar.style.display = 'flex';
      }});

      function playNarration(name) {{
        if (!available) return;
        audio.src = '/audio/' + name + '.wav';
        audio.play().catch(function() {{
          // Autoplay blocked without a prior user gesture — the replay
          // button (shown once loadeddata fires) lets them start it manually.
        }});
      }}
      window.playNarration = playNarration;
      playNarration('{clip}');
      {mic_script}
    }})();
    </script>
    """


def render_form(error: str = "", banner: str = "", values: dict | None = None) -> str:
    v = values or {}
    db_choice = v.get("db_choice", "local")
    body = []
    body.append("<h1>Let's set up Bede</h1>")
    body.append(_narration_block("welcome", enable_mic=True))
    body.append('<p class="sub">Answer these, then click the button at the bottom — everything else happens automatically.</p>')
    if banner:
        body.append(f'<div class="error">{banner}</div>')
    if error:
        body.append(f'<div class="error">{html.escape(error)}</div>')
    body.append('<form method="POST" action="/submit">')

    body.append('<label>Anthropic (Claude) API key</label>')
    body.append('<div class="hint">Get one free at <a href="https://console.anthropic.com/" target="_blank">console.anthropic.com</a> — this is what powers Bede\'s tutoring.</div>')
    body.append(f'<input type="text" name="anthropic_key" value="{html.escape(v.get("anthropic_key", ""))}" placeholder="sk-ant-...">')

    body.append('<label>Where should Bede store its data?</label>')
    body.append(f"""
    <label class="choice {'selected' if db_choice == 'local' else ''}">
      <input type="radio" name="db_choice" value="local" onclick="showManaged(false)" {'checked' if db_choice == 'local' else ''}>
      <span class="choice-title">On this computer (recommended)</span>
      <div class="choice-desc">Nothing to sign up for. Runs alongside Bede — nothing ever leaves this machine. You'll want to back it up occasionally (there's a simple command for that).</div>
    </label>
    <label class="choice {'selected' if db_choice == 'managed' else ''}">
      <input type="radio" name="db_choice" value="managed" onclick="showManaged(true)" {'checked' if db_choice == 'managed' else ''}>
      <span class="choice-title">A cloud database I already have</span>
      <div class="choice-desc">If you've already signed up for Neon, Supabase, or similar and have a connection string. Gets automatic backups from them, but your (still encrypted) data leaves this machine.</div>
    </label>
    """)
    managed_style = "" if db_choice == "managed" else 'style="display:none"'
    body.append(f'<div id="managed_url" {managed_style}>')
    body.append('<label>Database connection string</label>')
    body.append(f'<input type="text" name="database_url" value="{html.escape(v.get("database_url", ""))}" placeholder="postgresql://user:pass@host/dbname">')
    body.append('</div>')

    body.append('<label>Parent password</label>')
    body.append('<div class="hint">At least 8 characters. This is what you\'ll use to log in as the parent/admin.</div>')
    body.append('<input type="password" name="parent_password">')

    body.append('<label>Student PIN</label>')
    body.append('<div class="hint">At least 6 digits, and not an obvious pattern like 111111 or 123456 — e.g. 602656 is a good one. Your child uses this to log in.</div>')
    body.append(f'<input type="text" name="child_pin" value="{html.escape(v.get("child_pin", ""))}" placeholder="602656">')

    body.append('<label>License key</label>')
    body.append('<div class="hint">The LICENSE_KEY you received when you purchased or started a trial of Bede. No internet connection is needed to use it.</div>')
    body.append(f'<input type="text" name="license_key" value="{html.escape(v.get("license_key", ""))}" placeholder="eyJ...">')

    body.append('<button type="submit">Set up Bede</button>')
    body.append('</form>')
    body.append("""
    <script>
    function showManaged(show) {
      document.getElementById('managed_url').style.display = show ? 'block' : 'none';
      document.querySelectorAll('.choice').forEach(function(el) { el.classList.remove('selected'); });
      document.querySelector('input[name=db_choice]:checked').closest('.choice').classList.add('selected');
    }
    </script>
    """)
    return _PAGE_HEAD + "".join(body) + _PAGE_TAIL


def render_success() -> str:
    body = _narration_block("success", enable_mic=False)
    body += f"""
    <div class="success">
      <h1>All set!</h1>
      <p>Starting Bede now — this can take a couple of minutes the first time.</p>
      <p>You can close this tab. Bede will be running at
        <a href="https://localhost">https://localhost</a>{f' or <a href="https://{html.escape(LAN_IP)}">https://{html.escape(LAN_IP)}</a> from tablets on your network' if LAN_IP else ''}.</p>
    </div>
    """
    return _PAGE_HEAD + body + _PAGE_TAIL


def build_env_file(fields: dict) -> str:
    secret_key = secrets.token_hex(32)
    master_secret = secrets.token_hex(32)

    if fields["db_choice"] == "local":
        postgres_password = secrets.token_hex(24)
        database_url = f"postgresql+asyncpg://sage:{postgres_password}@db:5432/bede"
        db_lines = f"COMPOSE_PROFILES=local-db\nPOSTGRES_PASSWORD={postgres_password}\n"
    else:
        database_url = fields["database_url"]
        db_lines = ""

    if LAN_IP:
        cors = f"https://localhost,https://{LAN_IP},http://ui:80"
    else:
        cors = "https://localhost,http://ui:80"

    return (
        "# Generated by Bede's setup wizard\n"
        "# DO NOT commit this file — it contains secrets.\n\n"
        f"ANTHROPIC_API_KEY={fields['anthropic_key']}\n"
        f"SECRET_KEY={secret_key}\n"
        f"MASTER_SECRET={master_secret}\n"
        f"PARENT_PASSWORD={fields['parent_password']}\n"
        f"CHILD_PIN={fields['child_pin']}\n"
        f"DATABASE_URL={database_url}\n"
        f"{db_lines}"
        f"CORS_ORIGINS={cors}\n"
        "DISABLE_API_DOCS=true\n"
        "PRODUCTION=true\n"
        f"LICENSE_KEY={fields['license_key']}\n"
    )


def validate(fields: dict) -> str:
    """Returns an error message, or empty string if everything's valid."""
    if not fields.get("anthropic_key", "").strip():
        return "Please enter your Anthropic API key."
    if fields.get("db_choice") == "managed" and not fields.get("database_url", "").strip():
        return "Please enter your database connection string, or choose \"On this computer\" instead."
    if len(fields.get("parent_password", "")) < 8:
        return "Parent password must be at least 8 characters."
    if not pin_is_strong(fields.get("child_pin", "")):
        return "Student PIN must be 6+ digits and not an obvious pattern (like 111111 or 123456) — e.g. 602656 works."
    if not fields.get("license_key", "").strip():
        return "Please enter your license key."
    return ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the parent's terminal quiet — errors still show via 500s

    def _send_html(self, body: str, status: int = 200):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _serve_audio(self, name: str):
        # Whitelist against a fixed, known set of filenames rather than
        # trusting the path — closes off traversal (`../..`) even though
        # this container is short-lived and localhost-only.
        if name not in _AUDIO_FILES:
            self.send_response(404)
            self.end_headers()
            return
        path = AUDIO_DIR / name
        if not path.is_file():
            self.send_response(404)
            self.end_headers()
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/audio/"):
            self._serve_audio(self.path[len("/audio/"):])
            return
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        banner = (
            "A configuration already exists. Submitting this form will "
            "overwrite it (the old one is saved as .env.backup first)."
            if os.path.exists(ENV_PATH) else ""
        )
        self._send_html(render_form(banner=banner))

    def do_POST(self):
        if self.path != "/submit":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw)
        fields = {k: v[0] for k, v in parsed.items()}
        fields.setdefault("db_choice", "local")

        error = validate(fields)
        if error:
            self._send_html(render_form(error=error, values=fields), status=400)
            return

        if os.path.exists(ENV_PATH):
            os.replace(ENV_PATH, ENV_PATH + ".backup")
        with open(ENV_PATH, "w") as f:
            f.write(build_env_file(fields))
        os.chmod(ENV_PATH, 0o600)

        self._send_html(render_success())
        # Give the response time to actually flush to the socket before the
        # process exits — the launcher script is waiting on this container
        # to stop as its signal that the wizard finished successfully.
        threading.Timer(0.5, _shutdown_event.set).start()


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"Wizard listening on http://localhost:{PORT}")
    _shutdown_event.wait()
    server.shutdown()


if __name__ == "__main__":
    main()
