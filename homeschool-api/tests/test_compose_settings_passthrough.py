"""docker-compose.yml's api service enumerates environment variables one by
one rather than using env_file, which is a deliberate choice: the block is a
reviewable surface showing exactly what a container receives. Its own comment
states the rule that follows from that choice —

    "this block enumerates variables explicitly rather than using env_file,
     so anything set in .env and NOT named here is silently dropped. A knob
     documented in .env.example that does nothing is worse than no knob at
     all."

— but nothing enforced it, and it had drifted badly. Twenty-two documented
settings never reached the container, including RETAIN_MASTERY_PROFILES on
the same day the setup wizard started asking a parent to choose it, LOCALE
(the entire localization feature), and every WEBAUTHN_* value that makes a
security key bind to the right host.

The failure is silent in both directions. Nothing errors: pydantic simply
falls back to the code default, so a deployer who sets a value in .env gets
a running system that ignores them. That is the worst shape a defect can
take in a self-hosted product, because the person affected has no way to
tell the difference between "I configured it wrong" and "this was never
wired up."

So these tests pin three things:

  1. Every setting documented in either .env.example reaches the container.
  2. Every default written into compose equals the default in config.py, so
     the two copies of the same fact cannot drift apart.
  3. Every variable in the block is a real setting, which catches a typo
     that would otherwise pass silently forever.
"""
import re
from pathlib import Path

import pytest

from core.config import Settings

_REPO = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO / "docker-compose.yml"
_ENV_EXAMPLES = [_REPO / ".env.example", _REPO / "homeschool-api" / ".env.example"]


# Variables the deployment must supply, written as ${X:?message} so compose
# refuses to start rather than falling back to config.py's placeholder. Every
# one of these has a deliberately unusable code default (a "change-me" string,
# an empty DSN) that production validation would reject anyway — failing at
# `docker compose up` is the earlier, clearer failure.
REQUIRED = {
    "SECRET_KEY",
    "MASTER_SECRET",
    "PARENT_PASSWORD",
    "CHILD_PIN",
    "DATABASE_URL",
    "LICENSE_KEY",
}

# Hardcoded in compose rather than passed through, because they are a property
# of THIS deployment shape rather than a knob. Both are what makes the stack a
# production one; a .env that set them otherwise would be describing a
# different deployment than the one this file builds.
PINNED = {
    "DISABLE_API_DOCS": "true",
    "PRODUCTION": "true",
}

# Cases where compose's default deliberately differs from config.py's, with
# the reason. Kept short on purpose: each entry is a place where reading the
# code tells you something other than what a deployment actually does.
DIVERGENT_DEFAULTS = {
    "CORS_ORIGINS": (
        "config.py defaults to the Vite dev-server origins, which are what a "
        "developer running uvicorn directly needs. The compose stack is served "
        "through Caddy and nginx instead, so its own default names those."
    ),
    "RESEND_FROM_ADDRESS": (
        "config.py's default is an example.com placeholder that "
        "email_service.email_configured() treats as unconfigured on purpose. "
        "Compose names a real sending domain so the first-party deployment "
        "works; a self-hosted family setting their own RESEND_API_KEY must "
        "also set this to a domain verified in their own Resend account."
    ),
}


def _api_environment() -> dict[str, str]:
    """{VAR: raw right-hand side} for the api service's environment block."""
    text = _COMPOSE.read_text()
    api = text.split("\n  api:", 1)[1].split("\n  db:", 1)[0]
    env = api.split("environment:", 1)[1]
    # Stop at the next key at service-indent level (4 spaces).
    env = re.split(r"\n    [a-z_]+:", env, maxsplit=1)[0]
    out = {}
    for line in env.splitlines():
        m = re.match(r"^      - ([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _documented() -> set[str]:
    """Every variable either .env.example shows a deployer they can set,
    including the commented-out optional ones (which is most of them)."""
    found = set()
    for path in _ENV_EXAMPLES:
        for line in path.read_text().splitlines():
            m = re.match(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", line)
            if m:
                found.add(m.group(1))
    return found


def _setting_names() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def _expected_default(name: str) -> str:
    """config.py's default, rendered the way compose has to write it."""
    value = Settings.model_fields[name.lower()].default
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def test_every_documented_setting_reaches_the_container():
    """The rule the compose block's own comment states. This is the assertion
    that would have caught RETAIN_MASTERY_PROFILES being asked about in the
    setup wizard while the container never received the answer."""
    passed = set(_api_environment())
    missing = sorted((_documented() & _setting_names()) - passed)
    assert not missing, (
        "documented in .env.example but never passed to the api container, so "
        "setting them in .env silently does nothing: " + ", ".join(missing)
    )


def test_compose_defaults_match_the_code_defaults():
    """Two copies of the same fact, checked rather than trusted. A compose
    default that drifts below the code default is invisible: the container
    runs, it just runs on a different value than the source says."""
    mismatched = []
    for name, raw in _api_environment().items():
        if name in REQUIRED or name in PINNED or name in DIVERGENT_DEFAULTS:
            continue
        m = re.fullmatch(r"\$\{%s:-(.*)\}" % name, raw)
        if not m:
            continue  # shape is covered by the tests below
        if m.group(1) != _expected_default(name):
            mismatched.append(f"{name}: compose={m.group(1)!r} config.py={_expected_default(name)!r}")
    assert not mismatched, "\n".join(mismatched)


def test_required_variables_fail_the_stack_rather_than_defaulting():
    """A missing SECRET_KEY should stop `docker compose up`, not quietly boot
    on config.py's "change-me" placeholder and fail later somewhere less
    obvious."""
    env = _api_environment()
    for name in sorted(REQUIRED):
        assert name in env, f"{name} is required but not passed at all"
        assert env[name].startswith("${%s:?" % name), (
            f"{name} must use the ${{{name}:?message}} form so compose refuses "
            f"to start without it, got: {env[name]}"
        )


def test_pinned_variables_are_literal_and_named_here():
    env = _api_environment()
    for name, value in PINNED.items():
        assert env.get(name) == value, (
            f"{name} is pinned to {value!r} because it describes this deployment "
            f"shape rather than a knob; got {env.get(name)!r}"
        )


def test_no_variable_in_the_block_is_a_typo():
    """A misspelled name is passed happily by compose and read by nobody."""
    unknown = sorted(set(_api_environment()) - _setting_names())
    assert not unknown, (
        "passed to the api container but not a setting in core/config.py "
        "(a typo here is silent): " + ", ".join(unknown)
    )


@pytest.mark.parametrize("name", sorted(DIVERGENT_DEFAULTS))
def test_documented_divergences_are_still_real_settings(name):
    """Keeps the exemption list honest. An entry left behind after the setting
    it excused was renamed or removed would quietly widen the exemption."""
    assert name.lower() in Settings.model_fields, (
        f"{name} is listed as a deliberate divergence but is no longer a "
        f"setting — remove it from DIVERGENT_DEFAULTS"
    )
    assert DIVERGENT_DEFAULTS[name].strip(), f"{name} needs a stated reason"
