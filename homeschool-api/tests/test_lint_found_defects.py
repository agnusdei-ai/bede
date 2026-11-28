"""Regression tests for defects a linter (ruff F821/F811) found on 2026-11-28.

Neither was reachable by the existing suite: each lived on an error path no
test drove. Both guards were verified by reintroducing the defect.
"""
import inspect

import pytest


@pytest.mark.asyncio
@pytest.mark.usefixtures("demo_db")
async def test_an_unreadable_demo_parent_config_is_ignored_not_a_crash():
    """core/demo_code_session.get_parent_config's except branch called an
    undefined name (`logger`), so the one failure it exists to absorb (a
    row this process cannot decrypt) raised NameError instead, which is the
    500 on a demo visitor's first turn its own comment promised never to
    produce."""
    from core import database
    from core import demo_code_session

    async with database.AsyncSessionLocal() as db:
        db.add(database.DemoCodeParentConfig(code="SAMPLE-CODE", config_enc=b"not a ciphertext"))
        await db.commit()

    assert await demo_code_session.get_parent_config("SAMPLE-CODE") is None


def test_license_heartbeat_kick_is_defined_once_and_tolerates_no_loop():
    """core/license_heartbeat.py defined kick() twice; the second, shadowing
    copy called _kick.set() on None before the loop started and relied on a
    blanket except to hide the AttributeError."""
    from core import license_heartbeat

    source = inspect.getsource(license_heartbeat)
    assert source.count("\ndef kick(") == 1
    license_heartbeat._kick = None
    license_heartbeat.kick()  # must be a silent no-op
