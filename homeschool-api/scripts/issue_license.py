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

Every key issued is also recorded as one row in a local CSV ledger
(~/bede-license-ledger.csv, or $BEDE_LICENSE_LEDGER, or --ledger PATH), so
the record of who holds a key is a side effect of minting it rather than a
spreadsheet someone has to remember. The row carries a fingerprint of the
key, never the key itself. The ledger names customers, so it must live
outside this public repository; a path inside it is refused. If the row
cannot be written, no key is printed. See docs/SELLING_BEDE.md.
"""
import argparse
import base64
import csv
import hashlib
import json
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = Path.home() / "bede-license-ledger.csv"
LEDGER_COLUMNS = [
    "issued", "expires", "tier", "seats", "location_id",
    "licensee", "customer", "license_id", "key_fingerprint",
]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def key_fingerprint(license_str: str) -> str:
    """Identifies a key in the ledger without making the ledger a key store."""
    return hashlib.sha256(license_str.encode("ascii")).hexdigest()[:16]


def ledger_path(cli_value: "str | None") -> Path:
    raw = cli_value or os.environ.get("BEDE_LICENSE_LEDGER") or str(DEFAULT_LEDGER)
    return Path(raw).expanduser().resolve()


def append_ledger_row(path: Path, row: dict) -> None:
    if path == _REPO_ROOT or _REPO_ROOT in path.parents:
        raise ValueError(
            f"{path} is inside the repository, which is public. The ledger names "
            "customers; keep it outside the repository."
        )
    new = not path.exists() or path.stat().st_size == 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tier", required=True, choices=["trial", "core", "coop", "campus_location"])
    parser.add_argument(
        "--licensee", required=True,
        help="Family/organization name (or an opaque trial id) shown in the parent dashboard",
    )
    parser.add_argument("--seats", type=int, default=None, help="Max students (legacy tiers default 10; forbidden for campus_location)")
    parser.add_argument("--location-id", default=None,
                        help="Unique operator-assigned physical location ID; required for campus_location")
    parser.add_argument(
        "--days", type=int, default=None,
        help="Expires N days from today — required for --tier trial, optional otherwise (omit for perpetual)",
    )
    parser.add_argument(
        "--private-key", required=True,
        help="Path to the PEM private key from generate_license_keypair.py",
    )
    parser.add_argument(
        "--customer", default="",
        help="Who the key is going to (name or email), recorded in the ledger only, never in the key",
    )
    parser.add_argument(
        "--ledger", default=None,
        help=f"CSV ledger to append to (default $BEDE_LICENSE_LEDGER, else {DEFAULT_LEDGER})",
    )
    args = parser.parse_args()

    if args.tier == "trial" and args.days is None:
        parser.error("--days is required for --tier trial — a trial must expire")
    if args.days is not None and args.days < 1:
        parser.error("--days must be positive")
    if args.tier == "campus_location":
        from core.licensing import _LOCATION_ID
        if args.seats is not None:
            parser.error("campus_location uses an explicit unlimited learner entitlement; do not pass --seats")
        if not args.location_id or not _LOCATION_ID.fullmatch(args.location_id):
            parser.error("campus_location requires --location-id (3–64 letters/digits/dot/underscore/hyphen)")
        if args.days is None:
            parser.error("campus_location requires --days so the paid term expires")
    else:
        if args.location_id is not None:
            parser.error("--location-id only applies to campus_location")
        if args.seats is None:
            args.seats = 10
        if args.seats < 1:
            parser.error("--seats must be at least 1")

    key = ECC.import_key(Path(args.private_key).read_text())

    issued = date.today()
    expires = issued + timedelta(days=args.days) if args.days is not None else None

    payload = {
        "id": str(uuid.uuid4()),
        "licensee": args.licensee,
        "tier": args.tier,
        **({"learner_scope": "unlimited_at_location", "location_id": args.location_id}
           if args.tier == "campus_location" else {"seats": args.seats}),
        "issued": issued.isoformat(),
        "expires": expires.isoformat() if expires else None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(key, "rfc8032").sign(payload_bytes)

    license_str = f"{_b64url(payload_bytes)}.{_b64url(signature)}"

    ledger = ledger_path(args.ledger)
    try:
        append_ledger_row(ledger, {
            "issued": payload["issued"],
            "expires": payload["expires"] or "",
            "tier": args.tier,
            "seats": payload.get("seats", ""),
            "location_id": payload.get("location_id", ""),
            "licensee": args.licensee,
            "customer": args.customer,
            "license_id": payload["id"],
            "key_fingerprint": key_fingerprint(license_str),
        })
    except (OSError, ValueError) as exc:
        parser.error(f"could not record this key in the ledger, so it was not issued: {exc}")

    print(f"Licensee:  {args.licensee}")
    print(f"Tier:      {args.tier}")
    print(f"Seats:     {'unlimited enrolled learners' if args.tier == 'campus_location' else args.seats}")
    if args.tier == "campus_location":
        print(f"Location:  {args.location_id}")
    print(f"Issued:    {issued.isoformat()}")
    print(f"Expires:   {expires.isoformat() if expires else 'never'}")
    print(f"Recorded:  {ledger}")
    print()
    print("LICENSE_KEY=" + license_str)


if __name__ == "__main__":
    main()
