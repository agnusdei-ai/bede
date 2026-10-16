"""Seed synthetic fixtures through the REAL application API, and sign in.

Order, every step an HTTP call to the running server:

  1. Administrator: password login -> elevate -> enroll a passkey on the
     admin's virtual authenticator (POST /mfa/webauthn/register/*) ->
     password login again (now parent_pending) -> passkey assertion
     (POST /mfa/webauthn/authenticate/*) -> a ``webauthn_uv`` admin session
     -> elevate. That is the only session the /pilot admin routes accept.
  2. Synthetic Campus One and Two (POST /pilot/campuses).
  3. Synthetic Learner One and Two — the SAME display name, one per campus
     (POST /pilot/campuses/{id}/learners).
  4. Synthetic Teacher One and Two:
       virtual_authenticator (default): POST /auth/educator-passkey/invite,
         then the invitation ticket -> register/options -> create() ->
         register/verify -> login/options -> get() -> login/verify.
       minted_token (documented fallback): see ``_mint_teachers``.
  5. Memberships and roster grants, each teacher to their own campus and
     learner only (POST /pilot/campuses/{c}/educators/{t}[/learners/{l}]).

Every name sent is checked against the synthetic allowlist first. The
transcript written to <out>/seed.json holds ids, routes and status codes only.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualconfig as cfg  # noqa: E402
from harness import Api, Driver, HarnessError  # noqa: E402


class NotSynthetic(ValueError):
    pass


def assert_synthetic(name: str) -> str:
    """Refuse any identity outside the synthetic allowlist."""
    if name not in cfg.ALLOWED_NAMES:
        raise NotSynthetic(f"refusing to seed non-allowlisted identity {name!r}")
    return name


@dataclass
class Fixture:
    mode: str
    admin_token: str = ""
    campus: dict = field(default_factory=dict)
    learner: dict = field(default_factory=dict)
    teacher_id: dict = field(default_factory=dict)
    teacher_token: dict = field(default_factory=dict)
    teacher_blocker: str = ""
    deviations: list = field(default_factory=list)
    steps: list = field(default_factory=list)

    def public(self) -> dict:
        """Transcript form: ids and outcomes, never a token."""
        data = asdict(self)
        data.pop("admin_token")
        data["teacher_token"] = {k: bool(v) for k, v in self.teacher_token.items()}
        return data


class Seeder:
    def __init__(self, api: Api, driver: Driver, env: dict) -> None:
        self.api = api
        self.driver = driver
        self.env = env
        self.fx = Fixture(mode=env.get("QUAL_TEACHER_AUTH_MODE", cfg.TEACHER_AUTH_MODE))

    # ── helpers ──────────────────────────────────────────────────────────────
    def _step(self, label: str, method: str, path: str, token: str | None = None,
              body: dict | None = None, expect: tuple = (200, 201, 202, 204)):
        r = self.api.call(method, path, token, body)
        self.fx.steps.append({"step": label, "method": method, "route": path,
                              "status": r.status_code, "ok": r.status_code in expect})
        if r.status_code not in expect:
            raise HarnessError(f"{label}: {method} {path} -> {r.status_code} {r.text[:200]}")
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else {}

    def elevate(self) -> None:
        self._step("admin_elevate", "POST", "/auth/elevate", self.fx.admin_token,
                   {"password": self.env["PARENT_PASSWORD"]})

    # ── 1. administrator ─────────────────────────────────────────────────────
    def bootstrap_admin(self) -> None:
        pw = self.env["PARENT_PASSWORD"]
        tok = self._step("admin_password_login", "POST", "/auth/login", None,
                         {"role": "parent", "credential": pw})["access_token"]
        self.fx.admin_token = tok
        self.elevate()
        options = self._step("admin_passkey_register_options", "POST",
                             "/mfa/webauthn/register/options", tok)
        cred = self.driver.create("admin", options)
        self._step("admin_passkey_register_verify", "POST", "/mfa/webauthn/register/verify",
                   tok, {"credential": cred, "nickname": "Synthetic admin key"})
        login = self._step("admin_password_login_mfa", "POST", "/auth/login", None,
                           {"role": "parent", "credential": pw})
        if not login.get("mfa_required"):
            raise HarnessError("admin second login did not require the enrolled passkey")
        pending = login["access_token"]
        options = self._step("admin_passkey_auth_options", "POST",
                             "/mfa/webauthn/authenticate/options", pending)
        assertion = self.driver.get("admin", options)
        full = self._step("admin_passkey_auth_verify", "POST",
                          "/mfa/webauthn/authenticate/verify", pending, {"credential": assertion})
        self.fx.admin_token = full["access_token"]
        self.elevate()

    # ── 2-3. campuses and learners ───────────────────────────────────────────
    def seed_campuses_and_learners(self) -> None:
        for key, title in cfg.CAMPUS_TITLES.items():
            body = {"title": assert_synthetic(title)}
            self.fx.campus[key] = self._step(f"create_{key}", "POST", "/pilot/campuses",
                                             self.fx.admin_token, body)["campus_id"]
        for learner, campus in cfg.LEARNER_FIXTURES.items():
            body = {"display_name": assert_synthetic(cfg.SHARED_LEARNER_DISPLAY_NAME)}
            self.fx.learner[learner] = self._step(
                f"create_{learner}", "POST", f"/pilot/campuses/{self.fx.campus[campus]}/learners",
                self.fx.admin_token, body)["learner_id"]

    # ── 4. teachers ──────────────────────────────────────────────────────────
    def seed_teachers(self) -> None:
        if self.fx.mode == "minted_token":
            self.fx.deviations.append(
                "TEACHER_AUTH_MODE=minted_token: teacher accounts created with the production "
                "provisioning service and tokens minted with the production payload shape; "
                "the teacher passkey ceremony was NOT exercised")
            self._mint_teachers()
            return
        for key, username in cfg.TEACHER_USERNAMES.items():
            body = {"username": assert_synthetic(username),
                    "institutional_email": f"{username}@{cfg.INSTITUTION_EMAIL_DOMAIN}"}
            r = self.api.call("POST", "/auth/educator-passkey/invite", self.fx.admin_token, body)
            self.fx.steps.append({"step": f"invite_{key}", "method": "POST",
                                  "route": "/auth/educator-passkey/invite",
                                  "status": r.status_code, "ok": r.status_code == 202})
            if r.status_code != 202:
                self.fx.teacher_blocker = (
                    f"no teacher session: invite -> {r.status_code} ({_detail(r)[:80]}); the "
                    "enrollment ticket is delivered only by email, which this environment forbids")
                return
            # A delivered ticket would arrive in a mailbox the harness does not
            # read. There is no route that returns it, by design.
            self.fx.teacher_blocker = ("invitation accepted, but its ticket is only ever sent "
                                       "by email; no harness mailbox exists")
            return

    def enroll_teacher_with_ticket(self, key: str, ticket_id: str, ticket_token: str) -> None:
        """The full real passkey enrollment + sign-in for one teacher, once a
        ticket exists. Kept here so the ceremony is ready the moment an
        approved delivery channel exists; exercised by local verification."""
        username = assert_synthetic(cfg.TEACHER_USERNAMES[key])
        ticket = {"ticket_id": ticket_id, "ticket_token": ticket_token}
        options = self._step(f"{key}_register_options", "POST",
                             "/auth/educator-passkey/register/options", None, ticket)
        cred = self.driver.create(key, options["options"])
        self._step(f"{key}_register_verify", "POST", "/auth/educator-passkey/register/verify",
                   None, {**ticket, "ceremony_id": options["ceremony_id"], "credential": cred})
        self.teacher_passkey_login(key, username)

    def teacher_passkey_login(self, key: str, username: str | None = None) -> str:
        username = username or cfg.TEACHER_USERNAMES[key]
        options = self._step(f"{key}_login_options", "POST", "/auth/educator-passkey/login/options",
                             None, {"username": username})
        assertion = self.driver.get(key, options["options"])
        token = self._step(f"{key}_login_verify", "POST", "/auth/educator-passkey/login/verify",
                           None, {"username": username, "ceremony_id": options["ceremony_id"],
                                  "credential": assertion})["access_token"]
        self.fx.teacher_token[key] = token
        return token

    def _mint_teachers(self) -> None:
        ids = asyncio.run(_provision_and_mint(
            {k: assert_synthetic(v) for k, v in cfg.TEACHER_USERNAMES.items()}, self.api.ua))
        for key, (ident, token) in ids.items():
            self.fx.teacher_id[key] = ident
            self.fx.teacher_token[key] = token
            self.fx.steps.append({"step": f"mint_{key}", "method": "SERVICE",
                                  "route": "services.educator_access.provision_educator",
                                  "status": None, "ok": True})

    def relogin_teacher(self, key: str) -> str | None:
        """A fresh session after the old one was invalidated (revocation bumps
        credential_version). Returns None when no login path is available."""
        if self.fx.mode == "minted_token":
            ident = self.fx.teacher_id.get(key)
            if not ident:
                return None
            token = asyncio.run(_mint_existing(ident, self.api.ua))
            self.fx.teacher_token[key] = token
            return token
        if self.fx.teacher_blocker:
            return None
        return self.teacher_passkey_login(key)

    # ── 5. memberships and grants ────────────────────────────────────────────
    def grant_rosters(self) -> None:
        if not all(self.fx.teacher_id.get(k) for k in cfg.TEACHER_USERNAMES):
            return
        self.elevate()
        for teacher, campus in cfg.TEACHER_HOME.items():
            c, t = self.fx.campus[campus], self.fx.teacher_id[teacher]
            learner = next(k for k, v in cfg.LEARNER_FIXTURES.items() if v == campus)
            self._step(f"membership_{teacher}", "POST", f"/pilot/campuses/{c}/educators/{t}",
                       self.fx.admin_token)
            self._step(f"grant_{teacher}_{learner}", "POST",
                       f"/pilot/campuses/{c}/educators/{t}/learners/{self.fx.learner[learner]}",
                       self.fx.admin_token)

    def run(self) -> Fixture:
        self.bootstrap_admin()
        self.seed_campuses_and_learners()
        self.seed_teachers()
        self.grant_rosters()
        return self.fx


def _detail(r) -> str:
    try:
        return str(r.json().get("detail"))[:160]
    except Exception:  # noqa: BLE001
        return r.text[:160]


# ── documented fallback: production provisioning + production payload ────────

def _api_imports():
    sys.path.insert(0, str(cfg.API_DIR))
    os.chdir(cfg.API_DIR)
    from core.database import AsyncSessionLocal, ClassicalEducator, engine  # type: ignore
    from core.middleware import compute_fingerprint  # type: ignore
    from core.security import create_access_token  # type: ignore
    from services.educator_access import provision_educator  # type: ignore
    return AsyncSessionLocal, ClassicalEducator, engine, compute_fingerprint, create_access_token, provision_educator


async def _init_keys(db) -> None:
    # The same key hierarchy the server unwrapped at startup (existing rows
    # only; the server created them first).
    from core.config import settings  # type: ignore
    from core.encryption import initialize_encryption  # type: ignore
    await initialize_encryption(settings.master_secret, db)


def _token(create_access_token, compute_fingerprint, ident: str, ev: int, ua: str) -> str:
    from datetime import timedelta
    # Exactly services/educator_passkey_runtime.verify_authentication's payload
    # and routers/educator_passkeys.login_verify's fingerprint and lifetime.
    return create_access_token(
        {"role": "educator", "sub": ident, "ev": ev, "auth_method": "webauthn_uv"},
        fingerprint=compute_fingerprint(cfg.API_HOST, ua), expires_delta=timedelta(minutes=60))


async def _provision_and_mint(usernames: dict, ua: str) -> dict:
    import secrets
    Session, Educator, engine, fp, mint, provision = _api_imports()
    out = {}
    try:
        async with Session() as db:
            await _init_keys(db)
            for key, username in usernames.items():
                created = await provision(db, username, secrets.token_urlsafe(48))
                row = await db.get(Educator, created["id"])
                out[key] = (created["id"], _token(mint, fp, created["id"], row.credential_version, ua))
    finally:
        await engine.dispose()
    return out


async def _mint_existing(ident: str, ua: str) -> str:
    Session, Educator, engine, fp, mint, _ = _api_imports()
    try:
        async with Session() as db:
            row = await db.get(Educator, ident)
            return _token(mint, fp, ident, row.credential_version, ua)
    finally:
        await engine.dispose()


def write_transcript(fx: Fixture, out: Path) -> None:
    (out / "seed.json").write_text(json.dumps(fx.public(), indent=2) + "\n")
