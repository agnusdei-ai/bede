"""
JWT with SHA-256 HMAC (stdlib only) + device fingerprint binding.

Tokens are signed in one of two identity domains — the single-tenant family
deployment, and the multi-tenant public demo — so a demo token can never be
presented as a family one regardless of what any authorization check does or
forgets to do. See core/identity.py for why that seam exists and what it
does and does not protect against.

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

from core import identity
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

    The signing key is chosen from the token's own role (core/identity.py):
    a demo token is signed in the demo identity domain and a family token in
    the family domain, so neither can ever be presented as the other. The
    domain goes in the JWT *header*, which is covered by the signature —
    putting it in the payload would work too, but the header is where the
    verifier needs it before it has chosen a key, and an attacker editing it
    invalidates the signature either way.
    """
    payload = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload["iat"] = int(now.timestamp())
    payload["exp"] = int(expire.timestamp())
    if fingerprint:
        payload["fp"] = fingerprint

    domain = identity.domain_for_role(data.get("role"))
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT", "dom": domain}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(identity.signing_key(domain), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def decode_token(token: str, expected_domain: Optional[str] = None) -> Optional[dict]:
    """
    Validate signature, expiry, and identity domain.
    Returns payload dict or None if invalid.
    Does NOT validate fingerprint (caller must do that with the request).

    Three things have to hold, and the order matters:

    1. The signature verifies under the key for the domain the header
       claims. A forger who edits `dom` to pick a different key still needs
       that key.
    2. The payload's role is one that domain is permitted to issue. Without
       this, holding *any* validly-signed demo token would let you rewrite
       its role — the signature covers the role, so you couldn't, but the
       check also catches the reverse mistake: an issuing path that signs a
       privileged role in the wrong domain fails loudly here instead of
       working.
    3. `expected_domain`, when the caller knows which domain it serves.

    A token issued before domain separation has no `dom` header; it is
    verified against the legacy raw key and only while
    `LEGACY_TOKEN_GRACE` is on. See core/identity.py's MIGRATION note.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{body_b64}".encode()

        try:
            header = json.loads(_b64url_decode(header_b64))
        except Exception:
            return None
        if not isinstance(header, dict):
            return None
        domain = header.get("dom")

        if domain is None:
            if not settings.legacy_token_grace:
                return None
            key = identity.legacy_key()
        elif domain in (identity.FAMILY, identity.DEMO):
            key = identity.signing_key(domain)
        else:
            return None

        expected_sig = hmac.new(key, signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(_b64url_decode(body_b64))
        if not isinstance(payload, dict):
            return None
        if "exp" in payload and payload["exp"] < datetime.now(timezone.utc).timestamp():
            return None

        # A legacy token predates domains and is not held to (2) — it was
        # issued when there was only one domain, so there is no mismatch to
        # detect. It is still held to every other check, and to the role
        # checks in core/deps.py, exactly as before.
        if domain is not None:
            if identity.domain_for_role(payload.get("role")) != domain:
                log.warning(
                    "Rejected a token whose role %r does not belong to its signing domain %r",
                    payload.get("role"), domain,
                )
                return None
            if expected_domain is not None and domain != expected_domain:
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
