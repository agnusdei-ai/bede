"""The locuto-ipc container has to actually stay up.

`full-stack-boot` was red on main, and the cause was two individually
correct decisions colliding:

  * docker-compose.yml's `locuto-ipc` service deliberately withholds every
    commercial provider key, because that process may only ever resolve a
    model through `resolve_local_only()` (bede-ipc-spec.md §6). Its own
    block says so.
  * It also pins `PRODUCTION=true`, and
    `reject_no_ai_provider_configured_in_production` demands at least one of
    the four providers.

So for every household on a cloud provider — the ordinary case, since
`LOCAL_LLM_BASE_URL` is unset there — the service could never satisfy the
check. `Settings()` raised at IMPORT (`__main__` -> `server.py` ->
`core.config`), before `server.py`'s own `LOCUTO_IPC_ENABLED` kill-switch is
ever read, so **turning the connector off did not stop the crash loop**
under `restart: unless-stopped`.

These guards are built from the REAL compose block rather than a
hand-copied replica, so the fix and its invocation are the same assertion:
delete `BEDE_PROCESS_ROLE` from that service and the boot test fails too.
"""
import re
from pathlib import Path

import pytest

from core.config import (
    PROCESS_ROLE_API,
    PROCESS_ROLE_LOCUTO_IPC,
    PROCESS_ROLES,
    Settings,
    role_is_exempt_from_provider_requirement,
)

_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# Stand-ins for the `${X:?...}` variables a deployment must supply. Values
# are only required to be individually valid; what is under test is the
# provider rule, not these.
_REQUIRED_STANDINS = {
    "SECRET_KEY": "s" * 40,
    "MASTER_SECRET": "m" * 40,
    "PARENT_PASSWORD": "a-real-parent-password",
    "CHILD_PIN": "836194",
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/bede",
    "LICENSE_KEY": "not-checked-by-Settings",
}


def _service_block(name: str) -> str:
    text = _COMPOSE.read_text()
    block = text.split(f"\n  {name}:", 1)[1]
    # Stop at the next service (two-space indent, not part of this one).
    return re.split(r"\n  [a-z-]+:\n", block, maxsplit=1)[0]


def _compose_env(service: str) -> dict[str, str]:
    """{VAR: value a real container would receive} for one service.

    `${X:-default}` resolves to its default, which models the household this
    bug actually hits: one that set no local model because it uses a cloud
    provider.
    """
    env = _service_block(service).split("environment:", 1)[1]
    env = re.split(r"\n    [a-z_]+:", env, maxsplit=1)[0]
    out: dict[str, str] = {}
    for line in env.splitlines():
        m = re.match(r"^      - ([A-Z][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue
        name, raw = m.group(1), m.group(2)
        default = re.fullmatch(r"\$\{[A-Z0-9_]+:-(.*)\}", raw)
        required = re.fullmatch(r"\$\{([A-Z0-9_]+):\?.*\}", raw)
        if default:
            out[name] = default.group(1)
        elif required:
            out[name] = _REQUIRED_STANDINS[required.group(1)]
        else:
            out[name] = raw
    return out


# Every credential that can satisfy the provider rule. A service block that
# does not name one describes a container that does not receive it.
_PROVIDER_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY", "LOCAL_LLM_BASE_URL")


def _settings_kwargs(service: str) -> dict[str, str]:
    env = _compose_env(service)
    known = set(Settings.model_fields)
    unknown = {k for k in env if k.lower() not in known}
    assert not unknown, (
        f"docker-compose.yml's {service} block names {sorted(unknown)}, which "
        "are not real settings. `extra = 'ignore'` means a typo here is "
        "silent and permanent."
    )
    # cors_origins is validated but not part of this service's block; supply
    # a non-wildcard value so an unrelated production rule cannot mask the
    # one under test.
    kwargs = {"cors_origins": "https://localhost"}
    # Blank any provider the block does NOT pass, because the container does
    # not get it. Spelled out rather than left to pydantic's env fallback:
    # tests/conftest.py sets ANTHROPIC_API_KEY for the whole suite, so
    # without this every guard below would pass on ambient environment
    # instead of on the behaviour under test. That is not hypothetical —
    # these guards were written without it, and the boot test passed with
    # the fix reverted.
    for var in _PROVIDER_VARS:
        if var not in env:
            kwargs[var.lower()] = ""
    kwargs.update({k.lower(): v for k, v in env.items()})
    return kwargs


# ── The bug ─────────────────────────────────────────────────────────────


def test_the_locuto_ipc_container_boots_on_a_cloud_provider_household():
    """The reported crash. Built from the real compose block with every
    optional variable at its default, which is exactly a family who set an
    OPENAI/ANTHROPIC key and no local model."""
    kwargs = _settings_kwargs("locuto-ipc")
    assert kwargs["production"] == "true", "the service pins production; the bug needs it"
    assert not kwargs["local_llm_base_url"], "an unset local model is the case that crashed"
    for key in ("anthropic_api_key", "openai_api_key", "mistral_api_key"):
        assert not kwargs[key], "no commercial key reaches this service, by design"

    settings = Settings(**kwargs)
    assert settings.bede_process_role == PROCESS_ROLE_LOCUTO_IPC


def test_turning_the_connector_off_is_not_what_fixes_it():
    """LOCUTO_IPC_ENABLED is read inside serve(); the crash was at import,
    so the kill-switch could never be reached. It must boot either way."""
    for enabled in ("true", "false"):
        Settings(**{**_settings_kwargs("locuto-ipc"), "locuto_ipc_enabled": enabled})


# ── What must not have been weakened to get there ───────────────────────


def test_the_api_still_refuses_to_start_with_no_provider_at_all():
    """The rule this exemption is carved out of. A deployment that can
    actually tutor must still prove it can."""
    kwargs = _settings_kwargs("locuto-ipc")
    kwargs.pop("bede_process_role")
    with pytest.raises(Exception, match="no AI provider is configured"):
        Settings(**kwargs)


def test_a_misspelled_role_keeps_the_strict_behaviour():
    """The exemption is compared against the exact literal, so a typo cannot
    quietly buy it — the dangerous direction for a value that relaxes a
    production check."""
    kwargs = {**_settings_kwargs("locuto-ipc"), "bede_process_role": "locuto-ipc"}
    with pytest.raises(Exception) as exc:
        Settings(**kwargs)
    assert "not a known process role" in str(exc.value)


@pytest.mark.parametrize("role", ["", "API", "tutor", "locuto ipc"])
def test_an_unknown_role_is_refused_rather_than_defaulted_past(role):
    with pytest.raises(Exception, match="not a known process role"):
        Settings(**{**_settings_kwargs("locuto-ipc"), "bede_process_role": role})


def test_the_default_role_is_the_tutoring_api():
    """Every deployment that never sets this — including local development
    and the Render demo — is validated exactly as before."""
    assert Settings.model_fields["bede_process_role"].default == PROCESS_ROLE_API
    assert PROCESS_ROLE_API in PROCESS_ROLES


# ── The invocation, which is what actually fixes the container ──────────


def test_compose_tells_the_locuto_service_which_process_it_is():
    """The validator change alone does nothing: the process only becomes
    exempt because its own service block says what it is."""
    assert _compose_env("locuto-ipc").get("BEDE_PROCESS_ROLE") == PROCESS_ROLE_LOCUTO_IPC


def test_the_api_service_is_not_handed_a_role_that_would_exempt_it():
    """Nothing should ever mark the tutoring process as something else — it
    would silently drop the provider requirement for the one container that
    genuinely needs it."""
    assert _compose_env("api").get("BEDE_PROCESS_ROLE", PROCESS_ROLE_API) == PROCESS_ROLE_API


def test_the_isolation_was_not_loosened_instead():
    """The lazier fix — hand locuto-ipc a provider key so the check passes —
    would have broken bede-ipc-spec.md §6's whole point: content from
    outside this process must never be able to reach a commercial API. This
    fails if any commercial credential is ever added to that service."""
    env = _compose_env("locuto-ipc")
    forbidden = [k for k in env if k in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY"}]
    assert not forbidden, (
        f"docker-compose.yml's locuto-ipc service now passes {forbidden}. That process "
        "may only resolve a model through resolve_local_only() — see "
        "docs/LOCUTO_CONNECTOR_DECISIONS.md."
    )


# ── The exemption is an exact match, not a negation ─────────────────────


@pytest.mark.parametrize("role", ["locuto-ipc", "LOCUTO_IPC", "", "tutor", "locuto_ipcx"])
def test_only_the_exact_role_is_exempt(role):
    """`!= "api"` and `== "locuto_ipc"` behave identically for every valid
    value and differ only on a typo, where the first hands out the
    exemption. `reject_unknown_process_role` also catches a typo, but only
    because it is defined first — pydantic runs `after` validators in
    definition order, so testing through Settings() cannot see this property
    at all: the membership check shadows it.

    Asserting the predicate directly is what makes the safe behaviour
    independent of the order those two methods happen to appear in. Written
    after the negated form survived every other guard in this file.
    """
    assert role_is_exempt_from_provider_requirement(role) is False


def test_the_locuto_role_is_exempt():
    assert role_is_exempt_from_provider_requirement(PROCESS_ROLE_LOCUTO_IPC) is True
    assert role_is_exempt_from_provider_requirement(PROCESS_ROLE_API) is False


# ── The guard has to be reachable for the change it guards ──────────────


def test_docker_compose_is_in_the_ci_change_filter():
    """This suite reads docker-compose.yml, which is outside
    homeschool-api/. Until it is named in .github/workflows/test.yml's
    filter, a compose-only edit computes relevant=false, skips api-tests,
    and these guards never run for exactly the change they exist to catch —
    the failure test_decision_register.py documents. Removing
    BEDE_PROCESS_ROLE from that block is precisely such an edit.

    Reads the grep pattern line itself rather than the whole workflow: the
    first version of the equivalent guard passed on a comment beside the
    filter, which is a vacuous pass.
    """
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml"
    ).read_text()
    pattern_lines = [ln for ln in workflow.splitlines() if "grep -qE" in ln]
    assert pattern_lines, "Could not find the change filter's grep line in test.yml."
    assert any(r"docker-compose\.yml" in ln for ln in pattern_lines), (
        "docker-compose.yml is not in test.yml's change filter, so a compose-only "
        "edit would skip the suite that reads it."
    )
