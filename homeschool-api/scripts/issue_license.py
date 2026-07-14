#!/usr/bin/env python3
"""
Issues a signed Bede license key — see core/licensing.py and
docs/PRODUCTION_SETUP.md#licensing.

Requires the private key from generate_license_keypair.py. Never commit
that key; pass its path with --private-key each time you run this.

Examples:

    # A purchased annual/perpetual family license
    python scripts/issue_license.py --tier core --licensee "The Smith Family" \\
        --seats 10 --private-key ~/.bede-license-private.pem

    # A co-op license covering more households
    python scripts/issue_license.py --tier coop --licensee "St. Cecilia Homeschool Co-op" \\
        --seats 40 --private-key ~/.bede-license-private.pem

    # A 21-day fully-featured trial
    python scripts/issue_license.py --tier trial --licensee "trial-a1b2c3" \\
        --seats 10 --days 21 --private-key ~/.bede-license-private.pem

Paste the printed LICENSE_KEY line into the customer's .env (or the
demo deployment's own env, if issuing one for the operator's public demo —
that deployment also runs PRODUCTION=true and needs a valid license).
"""
import argparse
import base64
import json
import uuid
from datetime import date, timedelta
from pathlib import Path

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tier", required=True, choices=["trial", "core", "coop"])
    parser.add_argument(
        "--licensee", required=True,
        help="Family/organization name (or an opaque trial id) shown in the parent dashboard",
    )
    parser.add_argument("--seats", type=int, default=10, help="Max students in the pod (default 10)")
    parser.add_argument(
        "--days", type=int, default=None,
        help="Expires N days from today — required for --tier trial, optional otherwise (omit for perpetual)",
    )
    parser.add_argument(
        "--private-key", required=True,
        help="Path to the PEM private key from generate_license_keypair.py",
    )
    args = parser.parse_args()

    if args.tier == "trial" and args.days is None:
        parser.error("--days is required for --tier trial — a trial must expire")
    if args.seats < 1:
        parser.error("--seats must be at least 1")

    key = ECC.import_key(Path(args.private_key).read_text())

    issued = date.today()
    expires = issued + timedelta(days=args.days) if args.days is not None else None

    payload = {
        "id": str(uuid.uuid4()),
        "licensee": args.licensee,
        "tier": args.tier,
        "seats": args.seats,
        "issued": issued.isoformat(),
        "expires": expires.isoformat() if expires else None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(key, "rfc8032").sign(payload_bytes)

    license_str = f"{_b64url(payload_bytes)}.{_b64url(signature)}"

    print(f"Licensee:  {args.licensee}")
    print(f"Tier:      {args.tier}")
    print(f"Seats:     {args.seats}")
    print(f"Issued:    {issued.isoformat()}")
    print(f"Expires:   {expires.isoformat() if expires else 'never'}")
    print()
    print("LICENSE_KEY=" + license_str)


if __name__ == "__main__":
    main()
