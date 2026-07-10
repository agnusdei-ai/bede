import io
import threading
import time
import urllib.error
import urllib.request

import pytest

import trust_service


@pytest.fixture
def running_service(tmp_path, monkeypatch):
    cert_path = tmp_path / "root.crt"
    cert_path.write_bytes(b"-----BEGIN CERTIFICATE-----FAKE-----END CERTIFICATE-----")
    monkeypatch.setattr(trust_service, "CA_CERT_PATH", str(cert_path))

    server = trust_service.ThreadingHTTPServer(("127.0.0.1", 0), trust_service.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    try:
        yield f"http://127.0.0.1:{port}", cert_path
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _get(url, host=None):
    headers = {"Host": host} if host else {}
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers))


def test_index_shows_instructions_and_host(running_service):
    base, _ = running_service
    resp = _get(base + "/", host="192.168.1.50")
    body = resp.read().decode()
    assert resp.status == 200
    assert "Add a tablet to Bede" in body
    assert "192.168.1.50" in body
    assert "/trust/qr.svg" in body


def test_qr_endpoint_returns_valid_svg(running_service):
    base, _ = running_service
    resp = _get(base + "/qr.svg")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/svg+xml"
    body = resp.read()
    assert b"<svg" in body


def test_cert_endpoint_streams_actual_file_with_download_headers(running_service):
    base, cert_path = running_service
    resp = _get(base + "/root-ca.crt")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "application/x-x509-ca-cert"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert resp.read() == cert_path.read_bytes()


def test_unknown_path_is_404(running_service):
    base, _ = running_service
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(base + "/nope")
    assert exc_info.value.code == 404


def test_index_returns_503_before_caddy_generates_the_cert(running_service, monkeypatch):
    base, _ = running_service
    monkeypatch.setattr(trust_service, "CA_CERT_PATH", "/does/not/exist.crt")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(base + "/")
    assert exc_info.value.code == 503
    body = exc_info.value.read().decode()
    assert "Almost there" in body


def test_cert_endpoint_returns_503_before_caddy_generates_the_cert(running_service, monkeypatch):
    base, _ = running_service
    monkeypatch.setattr(trust_service, "CA_CERT_PATH", "/does/not/exist.crt")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(base + "/root-ca.crt")
    assert exc_info.value.code == 503


def test_html_escapes_host_header_to_prevent_reflected_xss(running_service):
    base, _ = running_service
    resp = _get(base + "/", host='"><script>alert(1)</script>')
    body = resp.read().decode()
    assert "<script>alert(1)</script>" not in body
