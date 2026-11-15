#!/usr/bin/env python3
"""Prepare a throwaway production stack for the capacity run.

    python stack_env.py --stub-url http://host.docker.internal:18401/v1 \
        [--db-pool-size N] [--db-max-overflow N] [--rate-limit-api-per-minute N]

Writes `.env` at the repository root (mode 600) and makes the checkout trust a
throwaway licence keypair minted here, the same approach as
production-regression.yml's full-stack-boot job: the public half replaces
PUBLIC_KEY_PEM in core/licensing.py in THIS CHECKOUT ONLY, and the signed key
goes into .env, so the stack boots licensed in production mode rather than
gated. Run only on a disposable CI runner; never commit what it writes.

Every secret is generated fresh. Sample data only: no real household, no
commercial model (the AI provider is the loopback stub), no mail.
Overrides are written only when given, so an unset one stays the shipped
default and the run is labelled default.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "homeschool-api"))


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_license(licensing_path: Path, seats: int = 10) -> str:
    """Sign a 30-day trial key with a fresh Ed25519 key and make the checkout
    trust that key, exactly as production-regression.yml does."""
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa
    key = ECC.generate(curve="ed25519")
    issued = date.today()
    payload = {"id": str(uuid.uuid4()), "licensee": "CI capacity run", "tier": "trial", "seats": seats,
               "issued": issued.isoformat(), "expires": (issued + timedelta(days=30)).isoformat()}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = eddsa.new(key, "rfc8032").sign(body)
    text = licensing_path.read_text(encoding="utf-8")
    pem = key.public_key().export_key(format="PEM")
    updated, n = re.subn(r'PUBLIC_KEY_PEM = """[\s\S]*?"""', f'PUBLIC_KEY_PEM = """{pem}"""', text, count=1)
    if n != 1:
        raise SystemExit("could not locate PUBLIC_KEY_PEM in core/licensing.py")
    licensing_path.write_text(updated, encoding="utf-8")
    return f"{b64url(body)}.{b64url(sig)}"


def env_lines(stub_url: str, license_key: str, overrides: dict) -> list[str]:
    from core.pin_policy import suggest_pin
    pg = secrets.token_hex(24)
    lines = [
        f"SECRET_KEY={secrets.token_hex(32)}",
        f"MASTER_SECRET={secrets.token_hex(32)}",
        f"PARENT_PASSWORD=cap-{secrets.token_hex(16)}",
        f"CHILD_PIN={suggest_pin()}",
        "COMPOSE_PROFILES=local-db",
        f"POSTGRES_PASSWORD={pg}",
        f"DATABASE_URL=postgresql+asyncpg://sage:{pg}@db:5432/bede",
        f"LICENSE_KEY={license_key}",
        f"LOCAL_LLM_BASE_URL={stub_url}",
        "LOCAL_LLM_MODEL=sample-stub",
        "BEDE_FORCE_ADAPTER=local",
        "TRANSCRIPTION_PROVIDER=local",
        "CORS_ORIGINS=https://localhost,http://ui:80",
    ]
    for name, value in overrides.items():
        if value is not None:
            lines.append(f"{name}={int(value)}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub-url", required=True)
    ap.add_argument("--db-pool-size", type=int)
    ap.add_argument("--db-max-overflow", type=int)
    ap.add_argument("--rate-limit-api-per-minute", type=int)
    a = ap.parse_args()
    overrides = {"DB_POOL_SIZE": a.db_pool_size, "DB_MAX_OVERFLOW": a.db_max_overflow,
                 "RATE_LIMIT_API_PER_MINUTE": a.rate_limit_api_per_minute}
    for name, value in overrides.items():
        if value is not None and not 0 <= value <= 10000:
            raise SystemExit(f"{name} out of range")
    key = mint_license(REPO / "homeschool-api" / "core" / "licensing.py")
    env = REPO / ".env"
    if env.exists():
        raise SystemExit(".env already exists; refusing to overwrite it")
    env.write_text("\n".join(env_lines(a.stub_url, key, overrides)) + "\n", encoding="utf-8")
    os.chmod(env, 0o600)
    print("wrote .env with", sum(v is not None for v in overrides.values()), "override(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
