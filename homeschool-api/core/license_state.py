"""
Runtime "effective license" state — the single source every consumer reads
(the seat cap in routers/pod.py, the status block in routers/admin.py, the
LicenseGateMiddleware in core/middleware.py).

Why this exists: the license used to live only in the .env file, validated
once at import time, and a missing/expired key refused to boot. That made
every renewal a customer-side file edit on the server machine — and an
expiry bricked the whole instance until someone edited that file. Now the
license can also live in the database (applied from the parent UI via
PUT /admin/license), and instead of refusing to boot, an unlicensed
production instance starts in a gated "license required" mode where the
parent can log in and paste the new key — no file edits, no restart.

Selection order: a valid, unexpired DB license wins (it's the renewal),
then a valid, unexpired env license. If neither is usable the instance is
gated (production only — dev and the public demo are never gated, same
exemptions as before). The best *expired* candidate is kept for messaging
so the parent sees "your core license expired on …" rather than a generic
error.

Deliberately NOT here: any kind of phone-home. Licenses are verified
offline against the embedded public key (core/licensing.py), exactly as
before — this module only changes where the signed text can be stored and
when it's checked.
"""
import logging
import threading
from dataclasses import dataclass
from typing import Optional

from core import licensing

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EffectiveLicense:
    info: Optional[licensing.LicenseInfo]  # best VALID-SIGNATURE candidate (may be expired)
    source: str          # 'db' | 'env' | 'none'
    ok: bool             # a usable (valid + unexpired) license is active, or none is required
    required: bool       # production non-demo deployment — gating applies when not ok
    problem: Optional[str]  # human-readable reason when not ok (for the parent UI)


_state = EffectiveLicense(info=None, source="none", ok=True, required=False, problem=None)
_lock = threading.Lock()


def _candidate(license_text: Optional[str]) -> Optional[licensing.LicenseInfo]:
    """Signature-valid LicenseInfo for the text, or None (unset/garbage)."""
    if not license_text:
        return None
    try:
        return licensing.verify_license(license_text)
    except licensing.InvalidLicenseError:
        return None


def refresh(env_key: str, db_key: Optional[str], *, required: bool) -> EffectiveLicense:
    """Recompute the effective license. Called at startup (main.py's
    lifespan, once the DB row is readable) and again whenever the parent
    applies a new key via PUT /admin/license — takes effect live, no
    restart."""
    global _state
    db_info = _candidate(db_key)
    env_info = _candidate(env_key)

    chosen: Optional[licensing.LicenseInfo] = None
    source = "none"
    for info, src in ((db_info, "db"), (env_info, "env")):
        if info is not None and not info.is_expired:
            chosen, source = info, src
            break
    if chosen is None:
        # No usable license — keep the best signature-valid (but expired)
        # candidate purely for a clear message.
        for info, src in ((db_info, "db"), (env_info, "env")):
            if info is not None:
                chosen, source = info, src
                break

    ok = (not required) or (chosen is not None and not chosen.is_expired)
    problem: Optional[str] = None
    if not ok:
        if chosen is not None and chosen.is_expired:
            problem = (
                f"Your {chosen.tier} license for {chosen.licensee!r} expired on "
                f"{chosen.expires.isoformat()} — paste a renewed license key to continue."
            )
        elif env_key or db_key:
            problem = "The stored license key is invalid — paste the license key exactly as you received it."
        else:
            problem = "No license key has been entered yet — paste the license key you received."

    with _lock:
        _state = EffectiveLicense(info=chosen, source=source, ok=ok, required=required, problem=problem)
    if not ok:
        log.critical("LICENSE REQUIRED: %s (instance is gated until a valid key is applied)", problem)
    elif chosen is not None:
        log.info(
            "License active: %s for %r (%d seats, source=%s%s)",
            chosen.tier, chosen.licensee, chosen.seats, source,
            f", expires {chosen.expires.isoformat()}" if chosen.expires else "",
        )
    return _state


def current() -> EffectiveLicense:
    with _lock:
        return _state


def effective_info() -> Optional[licensing.LicenseInfo]:
    """The active license's info for enforcement (seat caps, status). None
    when unlicensed or when the only candidate is expired — expired grants
    nothing."""
    s = current()
    if s.info is not None and not s.info.is_expired:
        return s.info
    return None


def is_gated() -> bool:
    """True when the LicenseGateMiddleware should restrict the API to the
    login + license-management surface."""
    s = current()
    return s.required and not s.ok
