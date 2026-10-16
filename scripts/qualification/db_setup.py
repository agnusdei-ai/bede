#!/usr/bin/env python3
"""Create the run's fresh database and its NON-superuser application role.

Uses a superuser connection (QUAL_DB_ADMIN_URL, the service container's
bootstrap account) ONLY to create a role with LOGIN and nothing else
(NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS) and a database it owns.
The application then connects as that role through production's own
_build_engine(); the superuser URL is never handed to the application.

The role owns its database so the application's startup
``CREATE TABLE IF NOT EXISTS`` works exactly as it does on a self-hosted
install, where the configured role owns the schema.

    QUAL_DB_ADMIN_URL=postgresql://postgres@127.0.0.1:5432/postgres \
    QUAL_APP_DB_PASSWORD=... python scripts/qualification/db_setup.py --db bede_qualification
Prints the application DATABASE_URL on stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualconfig as cfg  # noqa: E402

IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


async def setup(admin_url: str, db: str, role: str, password: str, *, recreate: bool) -> str:
    import asyncpg
    if not (IDENT.fullmatch(db) and IDENT.fullmatch(role)):
        raise SystemExit("database and role names must be simple lowercase identifiers")
    host = urlparse(admin_url).hostname
    if host not in cfg.ALLOWED_DB_HOSTS:
        raise SystemExit(f"refusing to administer non-service database host {host!r}")
    conn = await asyncpg.connect(admin_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        if recreate:
            await conn.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        exists = await conn.fetchval("select 1 from pg_roles where rolname=$1", role)
        verb = "ALTER" if exists else "CREATE"
        await conn.execute(
            f'{verb} ROLE "{role}" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
            f"NOREPLICATION NOBYPASSRLS PASSWORD '{password.replace(chr(39), '')}'")
        if not await conn.fetchval("select 1 from pg_database where datname=$1", db):
            await conn.execute(f'CREATE DATABASE "{db}" OWNER "{role}"')
    finally:
        await conn.close()
    parsed = urlparse(admin_url)
    port = parsed.port or 5432
    return f"postgresql+asyncpg://{role}:{password}@{host}:{port}/{db}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=os.environ.get("QUAL_DB_NAME", "bede_qualification"))
    p.add_argument("--keep", action="store_true", help="do not drop an existing database")
    a = p.parse_args()
    admin = os.environ.get("QUAL_DB_ADMIN_URL", "")
    pw = os.environ.get("QUAL_APP_DB_PASSWORD", "")
    if not admin or not pw:
        print("QUAL_DB_ADMIN_URL and QUAL_APP_DB_PASSWORD are required", file=sys.stderr)
        return 2
    print(asyncio.run(setup(admin, a.db, cfg.APP_DB_ROLE, pw, recreate=not a.keep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
