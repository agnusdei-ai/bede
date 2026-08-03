#!/usr/bin/env python3
"""
Rotates MASTER_SECRET — re-wraps the stored DATA_KEY under a new master
secret without touching DATA_KEY itself or any data encrypted under it.
Every row in every table stays valid throughout and after this script runs;
only the encryption_config.data_key wrapper changes.

Use this after a suspected MASTER_SECRET leak. Before this script existed,
core/encryption.py's docstring and docs/INCIDENT_RESPONSE.md both said not
to rotate MASTER_SECRET at all — restarting with a new one and no matching
DATA_KEY wrapper meant initialize_encryption() would either refuse to boot
(there's an existing data_key row it can't unwrap) or, on a from-scratch
deployment, generate a brand new DATA_KEY that abandons whatever was
encrypted under the old one. This script is the actual fix: it re-wraps the
EXISTING DATA_KEY under the new secret, so nothing needs decrypting and
re-encrypting, and the whole operation takes about as long as typing two
secrets.

Requires:
  - DATABASE_URL in the environment, pointing at the SAME database this
    deployment's API container uses — this script talks to the DB
    directly, not through the running API.
  - The CURRENT MASTER_SECRET (to unwrap DATA_KEY) and a NEW one you've
    already generated (openssl rand -hex 32) — both entered interactively
    via a hidden prompt, never as a CLI argument, so neither one is left
    sitting in shell history or visible in a process list.

Procedure (see docs/INCIDENT_RESPONSE.md's MASTER_SECRET rotation entry for
the full incident-response context):

    1. Run this script:  python -m scripts.rotate_master_secret
    2. Update MASTER_SECRET in .env (or your secrets store) to the new
       value it prompted for.
    3. Restart the API container (`make restart`, or your deployment's
       equivalent).

The script makes exactly one write: replacing encryption_config.data_key's
stored bytes with the same DATA_KEY, re-wrapped under the new secret. It
verifies the new wrapping round-trips BEFORE committing, and leaves the old
wrapping untouched — i.e. does nothing — if verification fails or the
supplied old secret doesn't actually unwrap the current DATA_KEY.

Note on timing: it's fine if the API container is still running against the
OLD MASTER_SECRET when this script commits the new wrapper — the running
process already has DATA_KEY loaded in memory (core/encryption.py's
module-level _DATA_KEY) and keeps serving requests correctly; it simply
won't re-derive KEK again until its next restart. At that restart, the
deployment MUST already have the NEW MASTER_SECRET in place — restarting
with the OLD one at that point fails loudly (initialize_encryption() raises
rather than silently generating a fresh DATA_KEY over an existing row), so
there's no window where a stale secret quietly corrupts anything.
"""
import asyncio
import getpass
import sys


async def _run() -> None:
    from core.database import AsyncSessionLocal
    from core.encryption import rotate_master_secret

    print("MASTER_SECRET rotation")
    print("=" * 40)
    print("Re-wraps the stored DATA_KEY under a new master secret.")
    print("No user data is touched — see this script's own docstring for the full procedure.\n")

    old_secret = getpass.getpass("Current MASTER_SECRET (the value presently in .env): ")
    if not old_secret:
        print("Aborted — no current secret entered.", file=sys.stderr)
        sys.exit(1)

    new_secret = getpass.getpass(
        "New MASTER_SECRET (generate one first with: openssl rand -hex 32): "
    )
    if not new_secret:
        print("Aborted — no new secret entered.", file=sys.stderr)
        sys.exit(1)
    if len(new_secret) < 32:
        # Matches core/config.py's reject_weak_defaults_in_production floor
        # for this exact setting — no reason this script should accept a
        # secret production itself would refuse to boot with.
        print(
            f"Aborted — the new secret is only {len(new_secret)} characters; "
            "production requires at least 32.",
            file=sys.stderr,
        )
        sys.exit(1)
    if new_secret == old_secret:
        print("Aborted — the new secret is identical to the current one.", file=sys.stderr)
        sys.exit(1)

    confirm = getpass.getpass("Re-enter the new MASTER_SECRET to confirm: ")
    if confirm != new_secret:
        print("Aborted — the two entries of the new secret didn't match.", file=sys.stderr)
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        try:
            await rotate_master_secret(old_secret, new_secret, db)
        except (ValueError, RuntimeError) as exc:
            print(f"\nAborted — {exc}", file=sys.stderr)
            sys.exit(1)

    print("\nDATA_KEY successfully re-wrapped under the new MASTER_SECRET.")
    print("\nNext steps:")
    print("  1. Update MASTER_SECRET in .env (or your secrets store) to the new value.")
    print("  2. Restart the API container (`make restart` or your deployment's equivalent).")
    print("  3. Rotation is complete once that restart picks up the new value — the")
    print("     old MASTER_SECRET no longer unwraps anything from this point on.")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
