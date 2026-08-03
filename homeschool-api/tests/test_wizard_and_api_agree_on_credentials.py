"""The setup wizard and the API enforce credential policy at two different
moments: the wizard when a parent types a value into the browser form, the
API when the container boots on the .env that form produced. Nothing checked
that they agreed, and they stopped agreeing.

PR #366 rejected the published example PIN (602656) at boot, which is right
— it had been printed in .env.example, setup.sh, the wizard's own hint text,
several docs, and the error messages that told a parent what a good PIN
looks like, so it is not a secret. But the wizard kept recommending it on
screen and kept accepting it. A parent following the installer's own advice
got an .env the wizard called valid and a container that then refused to
start, reporting that their PIN was "the default dev value."

It also broke the deployment regression suite, which drives the wizard
exactly as a parent would. main went red for five consecutive runs and every
one of them was this.

The rule these tests encode: **the wizard must never accept a credential the
API will refuse to boot on.** A wizard that can produce an unbootable .env
is worse than no wizard, because the parent has no reason to suspect the
tool that just told them everything was fine.
"""
import importlib.util
from pathlib import Path

import pytest

from core.config import Settings
from core.pin_policy import (
    PUBLISHED_EXAMPLE_PINS,
    WEAK_PLACEHOLDER_SECRETS,
    is_published_credential,
    pin_is_strong,
    suggest_pin,
)

_WIZARD = Path(__file__).resolve().parents[2] / "scripts" / "setup_wizard" / "wizard.py"


def _load_wizard():
    spec = importlib.util.spec_from_file_location("bede_setup_wizard", _WIZARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wizard = _load_wizard()


def _wizard_fields(**overrides) -> dict:
    fields = {
        "provider": "anthropic",
        "anthropic_key": "sk-ant-test",
        "db_choice": "local",
        "parent_password": "a-real-parent-password",
        "child_pin": suggest_pin(),
        "license_key": "eyJ.test",
    }
    fields.update(overrides)
    return fields


def _boots_in_production(**overrides) -> bool:
    """True if the API would construct Settings in production mode."""
    kwargs = {
        "production": "true",
        "secret_key": "s" * 40,
        "master_secret": "m" * 40,
        "parent_password": "a-real-parent-password",
        "child_pin": suggest_pin(),
        "database_url": "postgresql+asyncpg://u:p@h/d",
        "anthropic_api_key": "sk-ant-test",
        "disable_api_docs": "true",
        "cors_origins": "https://localhost",
    }
    kwargs.update(overrides)
    try:
        Settings(**kwargs)
        return True
    except Exception:
        return False


# ── The specific value that broke main ───────────────────────────────────

def test_the_wizard_refuses_the_published_example_pin():
    """The exact regression. This PIN passes every strength rule, which is
    why shape checking alone did not catch it."""
    assert pin_is_strong("602656"), "shape is not the problem, publication is"
    error = wizard.validate(_wizard_fields(child_pin="602656"))
    assert error, "the wizard accepted the PIN the API refuses to boot on"
    assert "602656" not in error or "published" in error.lower()


def test_the_api_refuses_the_same_pin():
    assert not _boots_in_production(child_pin="602656")


# ── The general rule, so the next published value cannot repeat this ─────

@pytest.mark.parametrize("pin", sorted(PUBLISHED_EXAMPLE_PINS))
def test_neither_side_accepts_any_published_pin(pin):
    assert wizard.validate(_wizard_fields(child_pin=pin)), (
        f"the wizard accepts published PIN {pin}"
    )
    assert not _boots_in_production(child_pin=pin), (
        f"the API boots on published PIN {pin}"
    )


@pytest.mark.parametrize("secret", sorted(WEAK_PLACEHOLDER_SECRETS - {"0000"}))
def test_neither_side_accepts_a_placeholder_password(secret):
    """"change-me-parent" is 16 characters, so the wizard's length check
    passed it happily while the API rejected it by name — the same dead end
    as the PIN, one field over."""
    assert wizard.validate(_wizard_fields(parent_password=secret)), (
        f"the wizard accepts placeholder password {secret!r}"
    )
    assert not _boots_in_production(parent_password=secret), (
        f"the API boots on placeholder password {secret!r}"
    )


def test_a_wizard_accepted_credential_actually_boots():
    """The other direction, and the one that matters to a real family: what
    the wizard calls valid must start."""
    fields = _wizard_fields()
    assert wizard.validate(fields) == ""
    assert _boots_in_production(
        child_pin=fields["child_pin"], parent_password=fields["parent_password"]
    )


def test_the_env_file_the_wizard_writes_boots_in_production():
    """The full path CI drives and a parent lives: submit the form, take the
    .env it produces, and construct Settings from it exactly as the API
    container does. Asserting on validate() alone would have missed a
    credential that passed validation but was written to .env differently."""
    fields = _wizard_fields()
    assert wizard.validate(fields) == ""

    env = {}
    for line in wizard.build_env_file(fields).splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip().lower()] = value

    settings_kwargs = {
        k: v for k, v in env.items() if k in Settings.model_fields
    }
    # COMPOSE_PROFILES/POSTGRES_PASSWORD are compose-level, not settings.
    Settings(**settings_kwargs)  # raises if the wizard produced an unbootable .env


# ── The suggestion the wizard now prints instead of a literal ────────────

def test_the_wizard_never_shows_a_parent_a_published_credential():
    """The hint text and the input placeholder both named 602656, so the
    screen recommended it. Asserted against the RENDERED page rather than
    the source, since what matters is what a parent reads — a source-text
    check would also trip on the comment explaining this history."""
    page = wizard.render_form()
    for value in PUBLISHED_EXAMPLE_PINS | WEAK_PLACEHOLDER_SECRETS:
        assert value not in page, f"the setup form still shows {value!r} to a parent"


def test_the_wizard_offers_no_pin_of_its_own_either():
    """Replacing the fixed example with a generated one would have fixed the
    secrecy problem and left a worse one: a child has to remember this PIN
    from memory, and a random six-digit number is close to the worst thing
    to hand a five-year-old. The installer states the rules and checks the
    answer. It does not answer."""
    field = wizard.render_form()
    field = field[field.index('name="child_pin"'):]
    field = field[:field.index(">") + 1]
    assert 'value=""' in field, f"the PIN field arrives pre-filled: {field}"
    assert "placeholder" not in field, f"the PIN field suggests a value: {field}"


def test_the_live_check_and_the_boot_check_agree():
    """check_child_pin backs the feedback a parent sees while typing. If it
    accepted something Settings refuses, the form would reassure a parent
    inline and hand them a stack that will not start — the original defect
    with a faster feedback loop."""
    for pin in ["481973", "602656", "111111", "123456", "1234", "", "99x999", "907183"]:
        live_ok = wizard.check_child_pin(pin) == ""
        boots = _boots_in_production(child_pin=pin)
        assert live_ok == boots, (
            f"live check says {'ok' if live_ok else 'no'} for {pin!r} but the API "
            f"{'boots' if boots else 'refuses to boot'}"
        )


def test_suggest_pin_is_not_used_by_the_installer():
    """It survives for tests and CI, which need a policy-passing PIN without
    committing a literal. Reintroducing it into the wizard would undo the
    decision above, so this says so out loud."""
    for pin in {suggest_pin() for _ in range(50)}:
        assert pin_is_strong(pin) and not is_published_credential(pin)
    assert "suggest_pin" not in _WIZARD.read_text()
