"""
Deployment posture assertions (P6 network zones, P20 container hardening).

Same reasoning as tests/test_app_composition.py, one layer further down.
Mutation testing on 2026-08-03 established that this codebase tests
behaviour well and composition badly: 25 of 25 mutations that broke a
control's logic were caught, and 0 of 8 that broke only its wiring.

Infrastructure is wiring by definition. The hardening here is all genuinely
present — `USER sage` in the Dockerfile, `read_only: true`, no-new-privileges
on every service, and only Caddy publishing ports — and none of it had a
single assertion. Adding `ports: - "8000:8000"` to the api service would
expose the application directly to the LAN, bypassing the reverse proxy that
terminates TLS and is the only thing P6's network zoning rests on, and every
test would still pass.

These are file-reading tests rather than runtime tests on purpose: the
property is about what gets deployed, not what the code does once deployed,
and a runtime test cannot observe a port mapping that only exists in
production.
"""
import pathlib

import pytest
import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.yml"
_DOCKERFILE = _ROOT / "homeschool-api" / "Dockerfile"


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text())


def _services() -> dict:
    return _compose()["services"]


# ── P6: only the reverse proxy is reachable from the network ────────────────

# Caddy terminates TLS and fronts everything else. It is the only service
# that may publish a port; every other service is reachable solely on the
# internal Compose network.
_MAY_PUBLISH_PORTS = {"caddy"}


def test_only_the_reverse_proxy_publishes_ports():
    """The whole of P6's network zoning for the self-hosted stack.

    A published port on the api service would put the application directly
    on the LAN — no TLS termination, no Caddy, and the browser-facing
    security headers and rate limits are the app's own rather than the
    proxy's. This is a one-line change in docker-compose.yml that nothing
    else would catch.
    """
    offenders = {
        name: svc["ports"]
        for name, svc in _services().items()
        if svc.get("ports") and name not in _MAY_PUBLISH_PORTS
    }
    assert not offenders, (
        f"these services publish ports to the host and should not: {offenders}. "
        "Only the reverse proxy may be reachable from outside the Compose network."
    )


def test_the_reverse_proxy_publishes_only_http_and_https():
    published = _services()["caddy"]["ports"]
    host_ports = {p.split(":")[-1] for p in published}
    assert host_ports == {"80", "443"}, f"unexpected published ports on caddy: {published}"


# ── P20: container hardening is a baseline, not a per-file convention ───────

@pytest.mark.parametrize("service", sorted(yaml.safe_load(_COMPOSE.read_text())["services"]))
def test_every_service_forbids_privilege_escalation(service):
    """no-new-privileges is the cheapest container hardening there is and the
    easiest to forget on a service added later. Parametrized over whatever
    services actually exist so a new one is covered the moment it appears,
    rather than needing to be remembered here."""
    opts = _services()[service].get("security_opt") or []
    assert "no-new-privileges:true" in opts, f"{service} allows privilege escalation"


# Postgres and Caddy both write to their own data directories, so a
# read-only root filesystem is not appropriate for them. Everything else is
# stateless — all state lives in Postgres.
_STATEFUL = {"db", "caddy"}


@pytest.mark.parametrize(
    "service",
    sorted(s for s in yaml.safe_load(_COMPOSE.read_text())["services"] if s not in _STATEFUL),
)
def test_stateless_services_run_read_only(service):
    assert _services()[service].get("read_only") is True, (
        f"{service} is stateless and should run with a read-only root filesystem"
    )


def test_the_api_image_does_not_run_as_root():
    """A USER directive after the last privileged build step. Without it the
    application runs as root inside the container, which makes read_only and
    no-new-privileges much less valuable than they look."""
    lines = [l.strip() for l in _DOCKERFILE.read_text().splitlines()]
    users = [l.split(maxsplit=1)[1].strip() for l in lines if l.startswith("USER ")]

    assert users, "Dockerfile has no USER directive — the api runs as root"
    assert users[-1] != "root", f"Dockerfile's final USER is {users[-1]!r}"


def test_the_api_image_declares_a_healthcheck():
    """Compose restart policies and any future orchestrator both need a real
    liveness signal; without one a wedged process looks healthy forever."""
    assert any(l.strip().startswith("HEALTHCHECK") for l in _DOCKERFILE.read_text().splitlines()), (
        "Dockerfile declares no HEALTHCHECK"
    )
