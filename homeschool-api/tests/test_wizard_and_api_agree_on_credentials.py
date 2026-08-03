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

def test_the_suggested_pin_is_one_the_api_will_boot_on():
    """The wizard offers this to a parent as a credential they may accept
    as-is, so it has to satisfy every rule the API applies, not just shape."""
    for _ in range(50):
        pin = suggest_pin()
        assert pin_is_strong(pin)
        assert not is_published_credential(pin)
        assert _boots_in_production(child_pin=pin)


def test_the_suggested_pin_is_not_a_fixed_literal():
    """A hardcoded suggestion is exactly what created this bug. If these
    ever collide across 200 draws, the generator has stopped being random."""
    assert len({suggest_pin() for _ in range(200)}) > 1


def test_the_wizard_never_shows_a_parent_a_published_credential():
    """The hint text and the input placeholder both named 602656, so the
    screen recommended it. Asserted against the RENDERED page rather than
    the source, since what matters is what a parent reads — a source-text
    check would also trip on the comment explaining this history."""
    page = wizard.render_form()
    for value in PUBLISHED_EXAMPLE_PINS | WEAK_PLACEHOLDER_SECRETS:
        assert value not in page, f"the setup form still shows {value!r} to a parent"


def test_the_wizard_offers_its_generated_suggestion_instead():
    page = wizard.render_form()
    assert wizard.SUGGESTED_CHILD_PIN in page
    assert wizard.validate(_wizard_fields(child_pin=wizard.SUGGESTED_CHILD_PIN)) == ""
