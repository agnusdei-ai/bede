"""
Regression tests for the production-hardening gaps found in the pre-release
security survey (docs/SECURITY.md's "Known open gaps"): SECRET_KEY,
PARENT_PASSWORD, and MASTER_SECRET were only checked against the exact
known dev-default string, with no length/strength floor of their own —
unlike CHILD_PIN/DEMO_PIN/SANDBOX_PIN, which already ran through
pin_is_strong(). Also covers the new DISABLE_API_DOCS/CORS_ORIGINS
wildcard checks, which close the same class of gap for two settings that
had no production validator at all before this.

Every Settings(production="true", ...) call here must also pass
disable_api_docs="true" (production always requires it now — see
tests/test_config.py, which was updated the same way) — a real,
independently strong value for every OTHER production-required field, so
each test isolates exactly the one field it's exercising.
"""
import pytest

from core.config import Settings


def _base_production_kwargs(**overrides) -> dict:
    kwargs = dict(
        production="true",
        disable_api_docs="true",
        secret_key="a" * 40,
        parent_password="a-strong-password",
        child_pin="602656",
        master_secret="b" * 40,
        demo_pin="",
        anthropic_api_key="sk-ant-real",
    )
    kwargs.update(overrides)
    return kwargs


# ── SECRET_KEY / PARENT_PASSWORD / MASTER_SECRET length floors ─────────────

def test_short_secret_key_rejected_in_production():
    with pytest.raises(ValueError, match="SECRET_KEY must be at least"):
        Settings(**_base_production_kwargs(secret_key="a" * 31))


def test_secret_key_at_exactly_the_floor_accepted():
    s = Settings(**_base_production_kwargs(secret_key="a" * 32))
    assert s.secret_key == "a" * 32


def test_short_parent_password_rejected_in_production():
    with pytest.raises(ValueError, match="PARENT_PASSWORD must be at least"):
        Settings(**_base_production_kwargs(parent_password="short7"))


def test_parent_password_at_exactly_the_floor_accepted():
    s = Settings(**_base_production_kwargs(parent_password="eight000"))
    assert s.parent_password == "eight000"


def test_short_master_secret_rejected_in_production():
    with pytest.raises(ValueError, match="MASTER_SECRET must be at least"):
        Settings(**_base_production_kwargs(master_secret="b" * 31))


def test_master_secret_at_exactly_the_floor_accepted():
    s = Settings(**_base_production_kwargs(master_secret="b" * 32))
    assert s.master_secret == "b" * 32


def test_known_dev_default_secrets_still_rejected_by_the_exact_match_first():
    """The dev-default placeholders are themselves >= the new length floor
    (e.g. "change-me-master-secret-32-chars-min" is 37 chars), so the
    exact-match check must still fire and produce its own specific message
    rather than silently passing the length floor and booting."""
    with pytest.raises(ValueError, match="MASTER_SECRET is set to the default dev value"):
        Settings(**_base_production_kwargs(master_secret="change-me-master-secret-32-chars-min"))


def test_length_floors_do_not_apply_outside_production():
    s = Settings(secret_key="short", parent_password="x", master_secret="short")
    assert s.secret_key == "short"
    assert s.parent_password == "x"
    assert s.master_secret == "short"


# ── DISABLE_API_DOCS ─────────────────────────────────────────────────────

def test_docs_enabled_rejected_in_production():
    with pytest.raises(ValueError, match="API docs are not disabled"):
        Settings(**_base_production_kwargs(disable_api_docs="false"))


def test_docs_disabled_accepted_in_production():
    s = Settings(**_base_production_kwargs(disable_api_docs="true"))
    assert s.api_docs_enabled is False


def test_docs_default_is_enabled_outside_production():
    """Dev/test convenience — /docs stays reachable unless PRODUCTION=true,
    same default this field always had."""
    s = Settings()
    assert s.api_docs_enabled is True


# ── CORS_ORIGINS wildcard ────────────────────────────────────────────────

def test_wildcard_cors_origin_rejected_in_production():
    with pytest.raises(ValueError, match="CORS_ORIGINS must not include"):
        Settings(**_base_production_kwargs(cors_origins="*"))


def test_wildcard_cors_origin_rejected_even_outside_production():
    """allow_credentials=True (main.py's CORSMiddleware) makes a wildcard a
    misconfiguration at any time, not just in production — checked
    unconditionally, unlike the other new checks here."""
    with pytest.raises(ValueError, match="CORS_ORIGINS must not include"):
        Settings(cors_origins="*")


def test_wildcard_mixed_with_real_origins_still_rejected():
    with pytest.raises(ValueError, match="CORS_ORIGINS must not include"):
        Settings(cors_origins="https://example.com,*")


def test_explicit_origin_list_accepted_in_production():
    s = Settings(**_base_production_kwargs(cors_origins="https://tutor.lan,https://192.168.1.50"))
    assert s.cors_origins_list == ["https://tutor.lan", "https://192.168.1.50"]
