"""Pins that every docker-compose.yml service carries an explicit mem_limit
— the guard against the Linux OOM killer picking an arbitrary process
(possibly `db`, mid-write) under memory pressure on a resource-constrained
host, most concretely a Raspberry Pi. See docker-compose.yml's own comment
on `api`'s mem_limit for the full reasoning, and
docs/PRODUCTION_SETUP.md's "Running on a Raspberry Pi" section for the
deployer-facing story this test keeps honest.

Uses the legacy top-level `mem_limit` key deliberately, not
`deploy.resources.limits.memory` — the latter's behavior under plain
`docker compose up` (no Swarm) is version-dependent (verified during
authoring: conflicting current guidance on whether it's honored without
`--compatibility`), exactly the kind of "looks configured but isn't" risk
tests/test_compose_settings_passthrough.py already exists to catch for
environment variables. mem_limit has no such ambiguity.
"""
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO / "docker-compose.yml"
_PRODUCTION_SETUP = _REPO / "docs" / "PRODUCTION_SETUP.md"

# Real, runnable services only — `networks:`/`volumes:` are top-level
# compose sections, not services, and must never be mistaken for one by the
# same indentation-based parsing this file uses.
_EXPECTED_SERVICES = {"api", "locuto-ipc", "db", "ui", "trust", "caddy"}


def _services() -> dict[str, str]:
    """{service_name: raw block text} for every service under `services:`,
    split at the next same-indent (2-space) key — the same boundary-finding
    approach test_compose_settings_passthrough.py uses for the api block."""
    text = _COMPOSE.read_text()
    body = text.split("\nservices:\n", 1)[1]
    body = body.split("\nvolumes:\n", 1)[0]  # stop before the top-level volumes: section
    # Split on lines that open a new service: "  <name>:" at 2-space indent,
    # not deeper (a service's own nested keys are indented 4+ spaces).
    parts = re.split(r"\n  ([a-z][a-z0-9_-]*):\n", "\n" + body)
    out = {}
    # parts alternates [prefix_before_first_match, name, block, name, block, ...]
    for i in range(1, len(parts), 2):
        out[parts[i]] = parts[i + 1]
    return out


def test_every_expected_service_is_actually_found():
    """A canary for the parser itself — if this drifts, the two tests below
    would silently check nothing rather than fail loudly."""
    found = set(_services().keys())
    assert _EXPECTED_SERVICES <= found, (
        f"Expected services {_EXPECTED_SERVICES} not all found in docker-compose.yml "
        f"(found: {sorted(found)}) — the parser or the compose file's shape has changed."
    )


def test_every_service_has_an_explicit_mem_limit():
    services = _services()
    missing = [
        name
        for name in _EXPECTED_SERVICES
        if not re.search(r"\n    mem_limit: ", services[name])
    ]
    assert not missing, (
        f"Service(s) {missing} have no explicit mem_limit — on a memory-constrained "
        "host, the Linux OOM killer would pick which process to SIGKILL rather than "
        "this being a predictable, per-container restart. See docker-compose.yml's "
        "api service's own mem_limit comment."
    )


def test_mem_limit_values_are_env_overridable_with_a_byte_suffix():
    """Every mem_limit must be a deployer-overridable ${..._MEM_LIMIT:-Nm}
    (or Ng/Nk) — never a bare hardcoded value a Pi owner has no way to
    tune without editing this file directly."""
    services = _services()
    pattern = re.compile(r"mem_limit: \$\{([A-Z_]+):-(\d+[mgk])\}")
    for name in _EXPECTED_SERVICES:
        m = pattern.search(services[name])
        assert m, f"{name}'s mem_limit is not of the form ${{VAR:-Nm}}: {services[name][:200]!r}"


def test_production_setup_doc_names_every_mem_limit_env_var():
    """docs/PRODUCTION_SETUP.md's Raspberry Pi section names the specific
    override variables — if a service's variable name changes here without
    that doc being updated, a deployer following the doc would tune a
    setting that no longer exists and get no error telling them so."""
    services = _services()
    pattern = re.compile(r"mem_limit: \$\{([A-Z_]+):-\d+[mgk]\}")
    doc_text = _PRODUCTION_SETUP.read_text()
    for name in _EXPECTED_SERVICES:
        m = pattern.search(services[name])
        assert m, f"{name} missing a parseable mem_limit"
        var_name = m.group(1)
        assert var_name in doc_text, (
            f"{var_name} (docker-compose.yml's {name} service) is not mentioned in "
            "docs/PRODUCTION_SETUP.md — a deployer reading that doc has no way to "
            "discover this knob exists."
        )
