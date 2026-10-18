#!/usr/bin/env python3
"""Prepare one approved synthetic campus pilot entitlement without retaining a signing key.

Run this trusted script locally on the owner Mac only. The Ed25519 key exists
only during this process. A new public verifier replaces the source constant,
and a signed location entitlement is saved outside the Git checkout with
permissions 0600. This is NOT a recoverable commercial signing authority.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "homeschool-api" / "core" / "licensing.py"
PUBLIC_KEY_PATTERN = re.compile(
    r'PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----\n'
    r'[A-Za-z0-9+/=\n]+'
    r'-----END PUBLIC KEY-----"""'
)
LOCATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def write_private_file_once(path: Path, data: bytes) -> None:
    """Create a local license with no overwrite and no world readable bits."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
        out.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue one test campus license; discard the signing key")
    parser.add_argument("--location-id", default="bede-mac-pilot-2026")
    parser.add_argument("--licensee", default="Bede Mac G3 Pilot")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path.home() / "Library/Application Support/Bede Pilot/pilot-license.txt")
    args = parser.parse_args()
    if not LOCATION_PATTERN.fullmatch(args.location_id):
        parser.error("location ID must be 3 to 64 letters, digits, dot, underscore or dash")
    if not 1 <= args.days <= 90:
        parser.error("pilot term must be between 1 and 90 days")
    if args.output.exists():
        parser.error("an existing pilot license exists at this path; it will not be overwritten")
    if not VERIFIER.is_file():
        parser.error("run from a complete Bede repository checkout")
    if not (ROOT / ".git").exists():
        parser.error("Bede checkout must be a Git repository")
    content = VERIFIER.read_text(encoding="utf-8")
    if len(PUBLIC_KEY_PATTERN.findall(content)) != 1:
        parser.error("cannot identify exactly one embedded public key constant")

    try:
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa
    except ImportError:
        parser.error("install the local Bede license tool dependencies first")

    os.umask(0o077)
    private = ECC.generate(curve="Ed25519")
    public_pem = private.public_key().export_key(format="PEM").strip()
    issued = date.today()
    expires = issued + timedelta(days=args.days)
    payload = {
        "id": __import__("uuid").uuid4().hex,
        "licensee": args.licensee,
        "tier": "campus_location",
        "learner_scope": "unlimited_at_location",
        "location_id": args.location_id,
        "issued": issued.isoformat(),
        "expires": expires.isoformat(),
    }
    message = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(private, "rfc8032").sign(message)
    eddsa.new(private.public_key(), "rfc8032").verify(message, signature)
    license_key = b64url(message) + "." + b64url(signature)

    # Do not print license material, write the private key or leave it in Git.
    write_private_file_once(args.output, ("LICENSE_KEY=" + license_key + "\n" +
        "BEDE_LOCATION_ID=" + args.location_id + "\n").encode("utf-8"))

    updated = PUBLIC_KEY_PATTERN.sub("PUBLIC_KEY_PEM = \"\"\"" + public_pem + "\"\"\"", content)
    try:
        VERIFIER.write_text(updated, encoding="utf-8")
    except Exception:
        args.output.unlink(missing_ok=True)
        raise

    sys.path.insert(0, str(ROOT / "homeschool-api"))
    from core.licensing import verify_license, location_matches
    checked = verify_license(license_key)
    if checked.tier != "campus_location" or not location_matches(checked, args.location_id):
        args.output.unlink(missing_ok=True)
        raise RuntimeError("generated pilot entitlement did not verify")
    del private

    print("Pilot license generated and locally verified.")
    print(f"License ID: {payload['id']}")
    print(f"Campus ID: {args.location_id}")
    print(f"Expiration: {expires.isoformat()}")
    print(f"Private license file: {args.output} (owner read/write only)")
    print(f"PUBLIC verifier updated: {VERIFIER}")
    print("No private signing key was saved. The signing key is no longer available.")
    print("Commit and push ONLY the public verifier change. Never commit the private license file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
