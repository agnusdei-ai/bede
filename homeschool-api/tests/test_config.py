"""
Regression tests for core/config.py's cross-field validators around
SANDBOX_PIN — must never collide with another real credential, and must
meet the same strength bar as CHILD_PIN/DEMO_PIN once PRODUCTION=true.
"""
import pytest

from core.config import Settings


def test_sandbox_pin_matching_parent_password_rejected():
    with pytest.raises(ValueError, match="SANDBOX_PIN"):
        Settings(sandbox_pin="602656", parent_password="602656")


def test_sandbox_pin_matching_child_pin_rejected():
    with pytest.raises(ValueError, match="SANDBOX_PIN"):
        Settings(sandbox_pin="602656", child_pin="602656")


def test_sandbox_pin_matching_demo_pin_rejected():
    with pytest.raises(ValueError, match="SANDBOX_PIN"):
        Settings(sandbox_pin="602656", demo_pin="602656")


def test_sandbox_pin_distinct_from_everything_is_accepted():
    s = Settings(sandbox_pin="602656", parent_password="x", child_pin="111222", demo_pin="333444")
    assert s.sandbox_pin == "602656"


def test_sandbox_pin_empty_by_default():
    assert Settings().sandbox_pin == ""


def test_weak_sandbox_pin_rejected_in_production():
    with pytest.raises(ValueError, match="SANDBOX_PIN"):
        Settings(
            production="true",
            secret_key="a" * 40,
            parent_password="a-strong-password",
            child_pin="602656",
            master_secret="b" * 40,
            sandbox_pin="111111",
        )


def test_strong_sandbox_pin_accepted_in_production():
    # 749283 deliberately differs from conftest.py's DEMO_PIN env default
    # (384756) — Settings() falls back to the environment for any field not
    # passed explicitly, so reusing that value here would collide with it.
    s = Settings(
        production="true",
        secret_key="a" * 40,
        parent_password="a-strong-password",
        child_pin="602656",
        master_secret="b" * 40,
        sandbox_pin="749283",
    )
    assert s.sandbox_pin == "749283"


def test_unset_sandbox_pin_never_blocks_production_startup():
    """Empty = disabled, same as DEMO_PIN — must not itself trigger a
    weak-default failure just because it's unset."""
    s = Settings(
        production="true",
        secret_key="a" * 40,
        parent_password="a-strong-password",
        child_pin="602656",
        master_secret="b" * 40,
    )
    assert s.sandbox_pin == ""
