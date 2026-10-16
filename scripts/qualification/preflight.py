#!/usr/bin/env python3
"""Fail-closed preflight for the synthetic qualification run.

Exits non-zero, before any server starts, if the environment could make the
run touch something real or pass for the wrong reason:

  * the checked-out commit is not exactly the candidate SHA;
  * production mode, or any production/commercial credential, is set;
  * the database is not the run's own service container, the application
    role is a superuser, or the database already holds data;
  * a real-data, billing, auto-enrollment or authorization-bypass marker is on;
  * the AI provider is anything but the loopback stub;
  * any route under /pilot looks like it launches or delivers into a learner
    session, or the tutoring turn reads teacher-authorized instruction.

Every check is reported, pass or fail, in <out>/preflight.json — a preflight
that only prints its first failure hides the rest.

    python scripts/qualification/preflight.py [--phase pre-start|post-seed]
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualconfig as cfg  # noqa: E402

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TRUTHY = {"1", "true", "yes", "on"}


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.checks)


def check_candidate(r: Report, env: dict) -> None:
    sha = env.get("QUAL_CANDIDATE_SHA", "")
    r.add("candidate_sha_is_40_hex", bool(SHA_RE.fullmatch(sha)),
          "candidate must be a full commit SHA, never a branch or tag name")
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cfg.REPO,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        r.add("head_equals_candidate", False, f"git rev-parse failed: {exc}")
        return
    r.add("head_equals_candidate", head == sha, f"HEAD={head} candidate={sha}")


def check_environment(r: Report, env: dict) -> None:
    for name in cfg.FORBIDDEN_NONEMPTY_ENV:
        r.add(f"env_unset:{name}", not env.get(name, "").strip(),
              "must be empty in the synthetic qualification environment")
    for key, value in sorted(env.items()):
        if any(key.startswith(p) for p in cfg.FORBIDDEN_ENV_PREFIXES) and value.strip():
            r.add(f"env_prefix_forbidden:{key}", False, "billing/email credential present")
        if key.startswith("QUAL_"):
            continue  # the harness's own knobs are not application markers
        if any(m in key.upper() for m in cfg.FORBIDDEN_TRUTHY_MARKERS) and value.strip().lower() in TRUTHY:
            r.add(f"env_marker_enabled:{key}", False,
                  "real-data / billing / auto-enrollment / bypass / delivery marker is on")
    for key, expected in cfg.REQUIRED_ENV.items():
        actual = env.get(key)
        r.add(f"env_required:{key}={expected}", (actual or "").strip().lower() == expected,
              f"actual={actual!r}")
    r.add("teacher_auth_mode_known", env.get("QUAL_TEACHER_AUTH_MODE", cfg.TEACHER_AUTH_MODE)
          in cfg.TEACHER_AUTH_MODES, f"one of {cfg.TEACHER_AUTH_MODES}")


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_ai_provider(r: Report, env: dict) -> None:
    base = env.get("LOCAL_LLM_BASE_URL", "")
    r.add("ai_provider_is_loopback_stub", _is_loopback(urlparse(base).hostname),
          f"LOCAL_LLM_BASE_URL={base!r} must point at the local stub")
    r.add("ai_adapter_forced_local", env.get("BEDE_FORCE_ADAPTER", "") == "local",
          "BEDE_FORCE_ADAPTER must be 'local' so no other provider can be reached")


async def _db_facts(url: str) -> dict:
    sys.path.insert(0, str(cfg.API_DIR))
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from core.database import normalize_database_url  # type: ignore

    engine = create_async_engine(normalize_database_url(url))
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text(
                "select current_user, r.rolsuper, r.rolcreaterole, r.rolbypassrls "
                "from pg_roles r where r.rolname = current_user"))).one()
            tables = (await conn.execute(text(
                "select count(*) from information_schema.tables "
                "where table_schema = 'public'"))).scalar_one()
        return {"user": row[0], "super": row[1], "createrole": row[2],
                "bypassrls": row[3], "public_tables": tables}
    finally:
        await engine.dispose()


def check_database(r: Report, env: dict, phase: str) -> None:
    url = env.get("DATABASE_URL", "")
    parsed = urlparse(url)
    r.add("database_is_postgres", parsed.scheme.startswith("postgres"), f"scheme={parsed.scheme!r}")
    r.add("database_host_is_service", parsed.hostname in cfg.ALLOWED_DB_HOSTS,
          f"host={parsed.hostname!r} allowed={cfg.ALLOWED_DB_HOSTS}")
    if not (parsed.scheme.startswith("postgres") and parsed.hostname in cfg.ALLOWED_DB_HOSTS):
        return  # never connect to a database the run does not own
    try:
        facts = asyncio.run(_db_facts(url))
    except Exception as exc:  # noqa: BLE001 — every failure is a failed check
        r.add("database_reachable", False, f"{type(exc).__name__}: {exc}"[:300])
        return
    r.add("database_reachable", True)
    r.add("app_role_is_configured_role", facts["user"] == cfg.APP_DB_ROLE,
          f"connected as {facts['user']!r}, expected {cfg.APP_DB_ROLE!r}")
    r.add("app_role_not_superuser", not facts["super"], f"rolsuper={facts['super']}")
    r.add("app_role_no_createrole", not facts["createrole"], f"rolcreaterole={facts['createrole']}")
    r.add("app_role_no_bypassrls", not facts["bypassrls"], f"rolbypassrls={facts['bypassrls']}")
    if phase == "pre-start" and cfg.REQUIRE_EMPTY_DATABASE:
        r.add("database_starts_empty", facts["public_tables"] == 0,
              f"{facts['public_tables']} tables already present: not a fresh synthetic database")


def served_routes(routes, prefix: str = ""):
    """Every (METHOD, path) the app serves. FastAPI 0.141 includes routers
    lazily, so ``app.routes`` holds ``_IncludedRouter`` wrappers; filtering
    it for routes with a ``path`` finds almost nothing (the trap
    tests/test_app_composition.py documents). Unwrap them, carrying any
    include prefix."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            ctx = getattr(route, "include_context", None)
            yield from served_routes(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
            continue
        path = getattr(route, "path", None)
        if path is None:
            continue
        for method in (getattr(route, "methods", None) or ()):
            yield method, prefix + path


def delivery_offenders(table) -> list[str]:
    """Routes under /pilot whose literal path words name a session launch or
    delivery (``session``, ``launch``, ``deliver``...). Path parameters are
    ignored, so ``{session_id}`` alone never trips it."""
    offenders = []
    for method, path in table:
        if not path.startswith("/pilot"):
            continue
        segments = [s for s in path.lower().split("/") if s and not s.startswith("{")]
        words = {w for s in segments for w in re.split(r"[-_]", s)}
        hit = sorted(words & set(cfg.DELIVERY_PATH_MARKERS))
        if hit:
            offenders.append(f"{method} {path} ({','.join(hit)})")
    return offenders


def check_delivery_disabled(r: Report) -> None:
    """No /pilot route launches or delivers into a learner session, and the
    tutoring turn has no path that reads teacher-authorized instruction.

    Reads the REAL app object's route table rather than grepping decorators,
    so a route mounted under another router's prefix is still seen."""
    sys.path.insert(0, str(cfg.API_DIR))
    os.chdir(cfg.API_DIR)
    try:
        import main  # type: ignore
    except Exception as exc:  # noqa: BLE001
        r.add("app_importable_for_route_scan", False, f"{type(exc).__name__}: {exc}"[:300])
        return
    r.add("app_importable_for_route_scan", True)
    table = sorted(set(served_routes(main.app.routes)))
    cfg.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.OUT_DIR / "routes.json").write_text(json.dumps(table, indent=0) + "\n")
    r.add("route_table_nonempty", len(table) > 20, f"{len(table)} (method, path) pairs")
    pilot = [(m, p) for m, p in table if p.startswith("/pilot")]
    r.add("pilot_routes_present", bool(pilot), f"{len(pilot)} routes under /pilot")
    offenders = delivery_offenders(table)
    r.add("no_pilot_session_launch_route", not offenders, "; ".join(offenders))
    for rel in cfg.DELIVERY_SOURCE_FILES:
        src = (cfg.API_DIR / rel).read_text(encoding="utf-8")
        found = [m for m in cfg.DELIVERY_SOURCE_MARKERS if m in src]
        r.add(f"tutor_reads_no_authorized_instruction:{rel}", not found, ",".join(found))
    from models.schemas import TutorRequest  # type: ignore
    pilot_fields = [f for f in TutorRequest.model_fields if "pilot" in f]
    r.add("tutor_request_has_no_pilot_handle", not pilot_fields, ",".join(pilot_fields))


def run(phase: str, env: dict | None = None, *, skip_import: bool = False) -> Report:
    env = dict(os.environ if env is None else env)
    r = Report()
    check_candidate(r, env)
    check_environment(r, env)
    check_ai_provider(r, env)
    check_database(r, env, phase)
    if not skip_import:
        check_delivery_disabled(r)
    return r


def main_cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("pre-start", "post-seed"), default="pre-start")
    args = parser.parse_args()
    report = run(args.phase)
    cfg.OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = cfg.OUT_DIR / f"preflight-{args.phase}.json"
    out.write_text(json.dumps({"phase": args.phase, "ok": report.ok, "checks": report.checks},
                              indent=2) + "\n")
    for c in report.checks:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + (f" — {c['detail']}" if c["detail"] and not c["ok"] else ""))
    print(f"preflight {args.phase}: {'OK' if report.ok else 'FAILED (fail closed)'}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main_cli())
