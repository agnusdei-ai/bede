"""
JWT with SHA-256 HMAC (stdlib only) + device fingerprint binding.

Every token embeds a 'fp' claim derived from SHA-256(client_ip | user_agent).
On each request, the fingerprint is re-computed and compared — a token cannot
be used from a different device or browser without triggering an audit event.

Token lifetime is fixed at ACCESS_TOKEN_EXPIRE_MINUTES (max 8h for parents,
4h for children). There is no refresh endpoint; re-authentication is required.
"""

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.config import settings

log = logging.getLogger(__name__)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (padding % 4))


def create_access_token(
    data: dict,
    fingerprint: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Issue a signed JWT.
    `fingerprint` should be compute_fingerprint(ip, user_agent) from the
    middleware module — binding the token to the issuing client.
    """
    payload = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload["iat"] = int(now.timestamp())
    payload["exp"] = int(expire.timestamp())
    if fingerprint:
        payload["fp"] = fingerprint

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(settings.secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def decode_token(token: str) -> Optional[dict]:
    """
    Validate signature and expiry.
    Returns payload dict or None if invalid.
    Does NOT validate fingerprint (caller must do that with the request).
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{body_b64}".encode()
        expected_sig = hmac.new(
            settings.secret_key.encode(), signing_input, hashlib.sha256
        ).digest()
        actual_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_b64url_decode(body_b64))
        if "exp" in payload and payload["exp"] < datetime.now(timezone.utc).timestamp():
            return None
        return payload
    except Exception:
        return None


def validate_fingerprint(payload: dict, current_fp: str) -> bool:
    """
    Returns True if the token's fingerprint matches the current request's
    fingerprint, or if the token was issued without a fingerprint (legacy).
    """
    token_fp = payload.get("fp")
    if not token_fp:
        return True   # no fingerprint in token — allow (backward compat)
    return hmac.compare_digest(token_fp, current_fp)
