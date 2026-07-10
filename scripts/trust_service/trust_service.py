#!/usr/bin/env python3
"""
Always-on "add a tablet" page — lets a parent onboard a new device's
certificate trust with zero CLI: open this page (or scan the QR code it
shows) on the new tablet, tap through, done. Complements `make caddy-trust`
(still there for anyone who prefers the terminal) rather than replacing it —
this one doesn't need the stack operator to run anything, and it stays
available for as long as the stack is up, not just during initial setup.

Deliberately pure standard library plus segno (a small, pure-Python, zero
-C-extension QR encoder — same reasoning as the setup wizard's "no
framework" choice, just with one tiny, well-tested dependency instead of
hand-rolling QR encoding, which is easy to get subtly wrong).

Served behind Caddy's plain-HTTP :80 listener at /trust — deliberately
plain HTTP, not HTTPS: a brand-new tablet hasn't trusted this server's
certificate yet, so serving the trust flow itself over HTTPS would hit the
exact untrusted-cert warning this page exists to avoid (chicken-and-egg).
The CA's public certificate has no confidentiality requirement (it's a
public key, same as any root cert), so plain HTTP here is safe on the LAN.
"""
import io
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import segno

PORT = int(os.environ.get("TRUST_SERVICE_PORT", "8080"))
# Mounted read-only from the same `caddy_data` volume Caddy itself writes
# to — see docker-compose.yml. This is where Caddy's `local_certs` PKI
# stores the CA it generates on first boot.
CA_CERT_PATH = os.environ.get("CA_CERT_PATH", "/data/pki/authorities/local/root.crt")

_PAGE_HEAD = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Add a tablet to Bede</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f7f3ec; color: #2d3142; max-width: 560px; margin: 0 auto;
         padding: 32px 20px; line-height: 1.55; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  h2 { font-size: 17px; margin-top: 32px; }
  .sub { color: #6b7280; margin-top: 0; margin-bottom: 24px; }
  .qr { text-align: center; margin: 24px 0; }
  .qr img { background: white; padding: 12px; border-radius: 12px; max-width: 240px; }
  .btn { display: inline-block; margin-top: 16px; padding: 14px 20px; font-size: 16px;
         font-weight: 600; color: white; background: #2b4c7e; border: none;
         border-radius: 10px; text-decoration: none; }
  .btn:hover { background: #1f3a63; }
  .error { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b;
           padding: 12px 16px; border-radius: 8px; }
  ol { padding-left: 20px; }
  li { margin-bottom: 8px; }
  a { color: #2b4c7e; }
</style>
</head>
<body>
"""
_PAGE_TAIL = "</body></html>"


def render_page(host: str) -> str:
    cert_url = f"http://{host}/trust/root-ca.crt"
    app_url = f"https://{host}/"
    body = f"""
    <h1>Add a tablet to Bede</h1>
    <p class="sub">Do this once per new device — after this step, the tablet
    stops showing certificate warnings for this server.</p>

    <p><strong>On the new tablet:</strong> scan this code with its camera app,
    or type <code>{html_escape(cert_url)}</code> into its browser.</p>
    <div class="qr"><img src="/trust/qr.svg" alt="QR code linking to the certificate download" width="240" height="240"></div>

    <h2>Then, on that tablet:</h2>
    <ol>
      <li>Tap the downloaded file (or the download notification).</li>
      <li><strong>Android:</strong> confirm "Install anyway" when asked — it may
      warn that a network administrator can monitor activity through this
      certificate, which is expected for your own home server; it does not mean
      an outside party gains access.</li>
      <li><strong>iPhone/iPad:</strong> Settings &rarr; Profile Downloaded &rarr;
      Install, then Settings &rarr; General &rarr; About &rarr; Certificate Trust
      Settings &rarr; enable full trust for "Bede LAN Root CA".</li>
      <li><strong>Windows/macOS:</strong> double-click the downloaded file &rarr;
      install it into the Trusted Root Certification Authorities store (Windows)
      or set it to "Always Trust" in Keychain Access (macOS).</li>
    </ol>

    <p style="text-align:center; margin-top: 28px;">
      <a class="btn" href="{html_escape(app_url)}">Continue to Bede &rarr;</a>
    </p>
    """
    return _PAGE_HEAD + body + _PAGE_TAIL


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_not_ready_page() -> str:
    body = """
    <h1>Almost there</h1>
    <div class="error">Bede's certificate isn't ready yet — this happens for a
    few seconds right after the stack starts. Refresh this page in a moment.</div>
    """
    return _PAGE_HEAD + body + _PAGE_TAIL


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the host's terminal quiet — errors still show via 5xx status

    def _send_html(self, body: str, status: int = 200):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        # Caddy's `handle_path /trust*` strips the /trust prefix before
        # forwarding here, so this container only ever sees "", "/",
        # "/qr.svg", "/root-ca.crt" — never a "/trust/..." path itself.
        path = self.path.split("?", 1)[0]

        if path in ("", "/"):
            self._handle_index()
        elif path == "/qr.svg":
            self._handle_qr()
        elif path == "/root-ca.crt":
            self._handle_cert()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_index(self):
        if not os.path.exists(CA_CERT_PATH):
            self._send_html(render_not_ready_page(), status=503)
            return
        host = self.headers.get("Host", "localhost")
        self._send_html(render_page(host))

    def _handle_qr(self):
        if not os.path.exists(CA_CERT_PATH):
            self.send_response(503)
            self.end_headers()
            return
        host = self.headers.get("Host", "localhost")
        cert_url = f"http://{host}/trust/root-ca.crt"
        qr = segno.make(cert_url, error="m")
        buf = io.BytesIO()
        qr.save(buf, kind="svg", scale=4, dark="#2d3142")
        encoded = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_cert(self):
        if not os.path.exists(CA_CERT_PATH):
            self.send_response(503)
            self.end_headers()
            return
        with open(CA_CERT_PATH, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-x509-ca-cert")
        self.send_header("Content-Disposition", 'attachment; filename="bede-root-ca.crt"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Trust service listening on http://0.0.0.0:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
