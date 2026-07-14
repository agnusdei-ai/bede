#!/usr/bin/env python3
"""
One-time setup: generates the Ed25519 keypair Bede license keys are signed
with (see core/licensing.py). Run this once per deployment of the *business*
(not per customer) — every license you issue afterward is signed by the same
private key, and every Bede install verifies against the same public key.

Usage:
    python scripts/generate_license_keypair.py

The private key is printed once and never stored by this script. Copy it
somewhere safe and OFFLINE (a password manager, an encrypted USB drive) —
anyone who has it can mint valid Bede licenses for any tier/seat count.
NEVER commit it to this repo or any other.

The public key is not a secret. Paste it into core/licensing.py's
PUBLIC_KEY_PEM constant (replacing the placeholder there) and ship that
change normally — it's what every deployment uses to verify a license
without ever talking to a server.
"""
from Crypto.PublicKey import ECC


def main() -> None:
    key = ECC.generate(curve="ed25519")
    private_pem = key.export_key(format="PEM")
    public_pem = key.public_key().export_key(format="PEM")

    print("=" * 70)
    print("PRIVATE KEY — keep secret, store offline, NEVER commit")
    print("=" * 70)
    print(private_pem)
    print()
    print("=" * 70)
    print("PUBLIC KEY — paste into core/licensing.py's PUBLIC_KEY_PEM")
    print("=" * 70)
    print(public_pem)


if __name__ == "__main__":
    main()
