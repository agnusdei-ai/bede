"""
Runtime "effective license" state — the single source every consumer reads
(the seat cap in routers/pod.py, the status block in routers/admin.py, the
LicenseGateMiddleware in core/middleware.py).

Why this exists: the license used to live only in the .env file, validated
once at import time, and a missing/expired key refused to boot. That made
every renewal a customer-side file edit on the server machine — and an
expiry bricked the whole instance until someone edited that file. Now the
license can also live in the database (applied from the parent UI via
POST /admin/license), and instead of refusing to boot, an unlicensed
production instance starts in a gated "license required" mode where the
parent can log in and paste the new key — no file edits, no restart.

Selection order: a valid, unexpired DB license wins (it's the renewal),
then a valid, unexpired env license. If neither is usable the instance is
gated (production only — dev and the public demo are never gated, same
exemptions as before). The best *expired* candidate is kept for messaging
so the parent sees "your core license expired on …" rather than a generic
error.

Also deliberately not here: any kind of phone-home. Licenses are verified
offline against the embedded public key (core/licensing.py), exactly as
before — this module only changes where the signed text can be stored and
when it's checked. The OPTIONAL license-server heartbeat
(core/license_heartbeat.py) adds server-tracked validity on top for
deployments that opt in by setting LICENSE_SERVER_URL; an unset value is a
permanent opt-out with zero outbound license traffic, asserted as code in
tests/test_license_heartbeat.py. When a server report IS supplied (live or
read from the tamper-evident cache), refresh() folds it in after the
signature check, and the report outranks the signed payload's now-nominal
expiry in both directions — never the reverse.
"""
import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from core import licensing

log = logging.getLogger(__name__)

# How long the last successful license-server answer keeps being honored
# after contact is lost (the uniform offline grace; the heartbeat retries
# daily long before this matters). See core/license_heartbeat.py for the
# tamper-evident cache that carries the answer across restarts.
SERVER_GRACE_DAYS = 30


def _now() -> datetime:
    """The clock the server-status verdict runs on — patched in tests."""
    return datetime.now(timezone.utc)


def _digest_text(license_text: str) -> str:
    """Stable fingerprint of the exact key text a server report describes —
    how a report is bound to the key it was fetched with. A parent pasting
    a different key while the server is unreachable must not inherit the
    old key's server status, any more than a fresh signature would."""
    return hashlib.sha256(license_text.encode("utf-8")).hexdigest()[:16]


def parse_server_datetime(value) -> Optional[datetime]:
    """Parse the activate/validate protocol's valid_until/reported_at values
    (ISO-8601; a naive value is UTC by server contract). Unparseable input
    yields None rather than raising — a malformed field is a protocol
    hiccup, not a reason to fail the exchange."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class ServerReport:
    """The license server's last successful answer about THIS instance's
    license key — live from a heartbeat contact, or read back from the
    tamper-evident cache (core/license_heartbeat.py). Built via
    server_report_from_payload(); consumed by refresh(), where a fresh
    report outranks the signed payload's nominal expiry in both directions
    and an `unknown` report (no server row for this key) is ignored."""

    status: str                      # 'active' | 'revoked' | 'unknown'
    valid_until: Optional[datetime]  # server-authoritative paid-term end (None: trials/revoked)
    reported_at: datetime            # when the server last said so (grace clock)
    key_digest: str                  # _digest_text of the exact key it describes
    activations_used: Optional[int] = None
    max_activations: Optional[int] = None

    def fresh(self, now: datetime) -> bool:
        """Within the offline-grace window of the last successful contact."""
        return (now - self.reported_at) <= timedelta(days=SERVER_GRACE_DAYS)


def server_report_from_payload(
    payload: dict,
    key_text: str,
    *,
    reported_at: Optional[datetime] = None,
) -> ServerReport:
    """Build a ServerReport from the activate/validate response — or from
    the identical JSON shape the cache persists (core/license_heartbeat.py).
    A status this build doesn't recognize maps to 'unknown' (signed payload
    governs): a future server that reports a new status must never gate
    anyone."""
    status = payload.get("status")
    if status not in ("active", "revoked", "unknown"):
        status = "unknown"
    used, limit = payload.get("activations_used"), payload.get("max_activations")
    return ServerReport(
        status=status,
        valid_until=parse_server_datetime(payload.get("valid_until")),
        reported_at=reported_at if reported_at is not None else _now(),
        key_digest=_digest_text(key_text),
        activations_used=int(used) if used is not None else None,
        max_activations=int(limit) if limit is not None else None,
    )


@dataclass(frozen=True)
class EffectiveLicense:
    info: Optional[licensing.LicenseInfo]  # best VALID-SIGNATURE candidate (may be expired)
    source: str          # 'db' | 'env' | 'none'
    ok: bool             # a usable (valid + unexpired, or server-honored) license is active, or none is required
    required: bool       # production non-demo deployment — gating applies when not ok
    problem: Optional[str]  # human-readable reason when not ok (for the parent UI)
    # Optional license-server answer — None unless the heartbeat is enabled
    # AND a report bound to the applied key exists (live or cached):
    server_status: Optional[str] = None          # 'active' | 'revoked' | 'unknown'
    server_valid_until: Optional[datetime] = None  # server-authoritative paid-term end
    activations_used: Optional[int] = None       # how many installs have activated this key
    max_activations: Optional[int] = None        # the key's activation cap (2 at launch)
    server_grants_validity: bool = False         # fresh 'active' + in-term: outranks nominal signed expiry


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


def refresh(
    env_key: str,
    db_key: Optional[str],
    *,
    required: bool,
    server_report: Optional[ServerReport] = None,
) -> EffectiveLicense:
    """Recompute the effective license. Called at startup (main.py's
    lifespan, once the DB row is readable) and again whenever the parent
    applies a new key via POST /admin/license — takes effect live, no
    restart.

    `server_report` — when the optional heartbeat is enabled
    (LICENSE_SERVER_URL set; core/license_heartbeat.py) — is the license
    server's last successful answer about THIS instance's license key,
    live or read from the tamper-evident cache. Decision order: the
    signature check is unchanged and always first; then a report bound to
    the applied key outranks the signed payload's now-nominal expiry in
    BOTH directions (an `active` report keeps the app un-gated even past
    nominal expiry — that's how renewals arrive without re-pasting a key;
    a `revoked` report gates it even though the signature still
    verifies); and a signature-valid key the server has never seen (or a
    server that can't be reached, or a heartbeat that was never enabled —
    the default, a permanent opt-out) falls back to the signed payload
    exactly as before, so enabling the heartbeat can never break a
    license that already worked."""
    global _state
    db_info = _candidate(db_key)
    env_info = _candidate(env_key)

    candidates = []
    if db_info is not None:
        candidates.append((db_info, "db", db_key))
    if env_info is not None:
        candidates.append((env_info, "env", env_key))
    chosen, source, chosen_text = None, "none", None
    for info, src, text in candidates:
        if not info.is_expired:
            chosen, source, chosen_text = info, src, text
            break
    if chosen is None and candidates:
        # No usable license — keep the best signature-valid (but expired)
        # candidate purely for a clear message.
        chosen, source, chosen_text = candidates[0]

    # A server report governs only the exact key text it was fetched with:
    # a different key applied while the server was unreachable must not
    # inherit the old key's server status.
    report: Optional[ServerReport] = None
    if server_report is not None and chosen_text is not None:
        if server_report.key_digest == _digest_text(chosen_text):
            report = server_report
        else:
            log.info(
                "Ignoring license-server report: it describes a different "
                "license key than the one currently applied"
            )

    server_grants, server_denies, grace_lapsed = _server_verdict(report)
    signed_ok = chosen is not None and not chosen.is_expired
    licensed = server_grants or (signed_ok and not server_denies and not grace_lapsed)
    ok = (not required) or licensed

    problem: Optional[str] = None
    if not ok:
        if server_denies and report is not None and report.status == "revoked":
            problem = (
                "Your Bede license is no longer active — the license server reports it "
                "as revoked (for example a refund or cancellation). Reconnect to the "
                "license server to revalidate, or contact support if this is unexpected."
            )
        elif grace_lapsed:
            problem = (
                f"Bede has been unable to reach the license server for over "
                f"{SERVER_GRACE_DAYS} days. Reconnect to revalidate — Bede checks again "
                "automatically once the internet is back — or paste a renewed license key."
            )
        elif server_denies and report is not None and report.valid_until is not None:
            problem = (
                f"Your Bede license's paid term ended on "
                f"{report.valid_until.date().isoformat()} — reconnect to the license "
                "server to revalidate once renewed, or contact support if this is "
                "unexpected."
            )
        elif chosen is not None and chosen.is_expired:
            problem = (
                f"Your {chosen.tier} license for {chosen.licensee!r} expired on "
                f"{chosen.expires.isoformat()} — paste a renewed license key to continue."
            )
        elif env_key or db_key:
            problem = "The stored license key is invalid — paste the license key exactly as you received it."
        else:
            problem = "No license key has been entered yet — paste the license key you received."

    with _lock:
        _state = EffectiveLicense(
            info=chosen,
            source=source,
            ok=ok,
            required=required,
            problem=problem,
            server_status=report.status if report is not None else None,
            server_valid_until=report.valid_until if report is not None else None,
            activations_used=report.activations_used if report is not None else None,
            max_activations=report.max_activations if report is not None else None,
            server_grants_validity=server_grants,
        )
    if not ok:
        log.critical("LICENSE REQUIRED: %s (instance is gated until a valid key is applied)", problem)
    elif chosen is not None:
        log.info(
            "License active: %s for %r (%d seats, source=%s%s)",
            chosen.tier, chosen.licensee, chosen.seats, source,
            f", expires {chosen.expires.isoformat()}" if chosen.expires else "",
        )
    if report is not None and report.status != "unknown":
        log.info(
            "License server reports %r for the applied key (valid_until=%s, reported_at=%s)",
            report.status,
            report.valid_until.isoformat() if report.valid_until else None,
            report.reported_at.isoformat(),
        )
    return _state


def _server_verdict(report: Optional[ServerReport]) -> tuple[bool, bool, bool]:
    """Fold the (already digest-bound) server report into three flags:
    (server_grants, server_denies, grace_lapsed).

    server_grants — a fresh `active` report whose paid term is still
      running: valid regardless of the signed payload's nominal expiry.
    server_denies — the server has a record for this key and it is bad:
      `revoked`, or a fresh `active` report whose paid term has ended.
    grace_lapsed — the last answer is a stale `active` one, older than
      SERVER_GRACE_DAYS: the server may be fine, but this instance can no
      longer know, so it stops trusting the cached answer.

    A missing report (heartbeat disabled, or unreachable with no cache) or
    an `unknown` one (the server has no row for this signature-valid key —
    e.g. a legacy hand-issued license) yields all False: the signed
    payload governs, exactly the pre-heartbeat behavior."""
    if report is None or report.status == "unknown":
        return False, False, False
    now = _now()
    if report.status == "revoked":
        return False, True, False  # revocation has no grace
    if not report.fresh(now):
        return False, False, True
    if report.valid_until is None:
        # Trials carry their authority in the signed expiry; the server
        # defers — no valid_until to honor, no denial either.
        return False, False, False
    if report.valid_until > now:
        return True, False, False
    return False, True, False  # fresh answer: the paid term has ended


def current() -> EffectiveLicense:
    with _lock:
        return _state


def effective_info() -> Optional[licensing.LicenseInfo]:
    """The active license's info for enforcement (seat caps, status). None
    when unlicensed, expired, or gated for ANY reason — a server-reported
    revocation or an exhausted offline grace included: with the gate up
    there is nothing to enforce a cap against. Conversely, a license the
    (optional) license server reports as active-and-in-term stays honored
    past its nominal signed expiry (refresh() keeps the instance
    un-gated) — the server-tracked term is the live truth for renewed
    licenses, so the seat cap keeps enforcing against it."""
    s = current()
    if s.info is None or not s.ok:
        return None
    return s.info


def is_gated() -> bool:
    """True when the LicenseGateMiddleware should restrict the API to the
    login + license-management surface."""
    s = current()
    return s.required and not s.ok
