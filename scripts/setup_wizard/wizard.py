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

REPO_DIR = "/repo"
ENV_PATH = os.path.join(REPO_DIR, ".env")
PORT = int(os.environ.get("WIZARD_PORT", "8765"))
LAN_IP = os.environ.get("HOST_LAN_IP", "").strip()

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
</style>
</head>
<body>
"""
_PAGE_TAIL = "</body></html>"


def render_form(error: str = "", banner: str = "", values: dict | None = None) -> str:
    v = values or {}
    db_choice = v.get("db_choice", "local")
    body = []
    body.append("<h1>Let's set up Bede</h1>")
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
    body = f"""
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

    def do_GET(self):
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
