"""
Identity domains — the seam between the family deployment and the public
demo (docs/ARCHITECTURE_PRINCIPLES.md P10).

THE PROBLEM. `routers/auth.py`'s `login()` issues `parent`, `child`, and
`demo_code` tokens from one function, in one format, under one signing key,
validated by one path. Those are not one trust domain. The family instance
is single-tenant, LAN-scoped, and holds a known child's real data under a
password its own operator chose. The demo is multi-tenant, pseudonymous,
internet-facing, and operated *for* strangers rather than *by* them. The
business model forks there; the architecture had no seam.

What that costs concretely: every bug in the demo's credential path is a
bug in the family's. `demo_code` login takes a code minted by an
unauthenticated endpoint. If any flaw there — in redemption, in code
generation, in a future demo feature — ever yields an attacker-controlled
*signed* token, nothing structural stops that token being replayed with
`role: "parent"`. The only thing standing in the way is that every
authorization check remembers to look at the role, forever, in every code
path added from here on. That is a discipline, not a boundary.

THE MECHANISM. Two domains, each with its own signing key, derived from
`SECRET_KEY` by HMAC with a domain-separated label (the standard KDF
construction — distinct labels give computationally independent keys). A
token carries its domain in the JWT *header*, so it is covered by the
signature rather than being an attacker-chosen hint. Verification selects
the key by that domain and then requires the token's role to be one that
domain is allowed to issue.

The result is that a demo-domain token claiming `role: "parent"` fails at
the signature layer, before any authorization code runs and regardless of
whether that code remembered to check. Forging one requires the family
signing key, which the demo's own code paths never touch.

FULL SEPARATION IS AVAILABLE. By default both keys derive from the one
`SECRET_KEY`, so a compromise of that secret still yields both — this is
domain separation, not key isolation, and it is exactly the "separate
signing context at minimum" P10 asks for. A deployment that wants the
stronger property can set `DEMO_SECRET_KEY` to an independent value, at
which point the demo's signing key shares no material with the family's.
That is the recommended setting for the public demo instance, where the
operator holds third parties' data and the two roles genuinely run in
different places.

MIGRATION. Tokens issued before this existed carry no domain header and are
signed with the raw `SECRET_KEY`. They stay valid until they expire (8h max
for a parent, less for everything else) so that deploying this change does
not sign every family out mid-lesson. The grace is self-limiting — no new
legacy tokens are ever issued — and can be switched off immediately with
`LEGACY_TOKEN_GRACE=false`. It grants nothing an attacker did not already
have: verifying a legacy token needs the same `SECRET_KEY` it always did.
"""
import hashlib
import hmac
from typing import Optional

from core.config import settings

FAMILY = "family"
DEMO = "demo"

# Which domain is allowed to issue which roles. A token whose role isn't
# listed for its own domain is rejected in core/security.py — that check is
# what makes the boundary structural rather than a convention.
_ROLE_DOMAIN = {
    "parent": FAMILY,
    "parent_pending": FAMILY,
    "parent_recovery": FAMILY,
    "parent_enrolling": FAMILY,
    "child": FAMILY,
    "demo_code": DEMO,
}

# Versioned so the derivation can change later without silently validating
# old tokens under a new scheme.
_LABEL = "bede/identity/v1/"


def domain_for_role(role: Optional[str]) -> str:
    """The domain a role belongs to.

    Unknown roles map to FAMILY deliberately: a role added later without
    being classified here lands in the domain with the *stricter* set of
    checks (fingerprint binding, credentials_version) rather than the
    internet-facing one. Failing closed matters more than being tidy.
    """
    return _ROLE_DOMAIN.get(role or "", FAMILY)


def _derive(secret: str, domain: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), (_LABEL + domain).encode("utf-8"), hashlib.sha256).digest()


def signing_key(domain: str) -> bytes:
    """The signing key for a domain.

    Not cached: `settings` is mutated by tests and by the credential-refresh
    path, and an HMAC-SHA256 over ~20 bytes is ~1 us — far below the cost of
    the request it authenticates. A stale cached signing key would present
    as a mass logout, which is not worth 1 us.
    """
    if domain == DEMO and settings.demo_secret_key:
        return _derive(settings.demo_secret_key, domain)
    return _derive(settings.secret_key, domain)


def legacy_key() -> bytes:
    """The pre-domain signing key: `SECRET_KEY` used raw.

    Only for verifying tokens issued before domain separation existed. Never
    used to sign.
    """
    return settings.secret_key.encode("utf-8")


def demo_key_is_independent() -> bool:
    """True when the demo domain has its own secret rather than deriving
    from the family's. Surfaced in the readiness/deployment docs so an
    operator can tell which of the two properties they actually have."""
    return bool(settings.demo_secret_key)
