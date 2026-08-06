"""
core/instance_id.py — see its own docstring for why this exists (proving,
from a browser trace, whether a voice-stream session's start and its
following chunk/finish calls landed on the same backend process).

INSTANCE_ID is resolved once at import time from a module-level expression,
not a function — so these tests exercise that resolution logic directly
via importlib.reload() rather than calling something a real request path
also calls, since there is no separate "resolve" function to call.
"""
import importlib

import core.instance_id as instance_id_module


def _reload_with_env(monkeypatch, render_instance_id):
    if render_instance_id is None:
        monkeypatch.delenv("RENDER_INSTANCE_ID", raising=False)
    else:
        monkeypatch.setenv("RENDER_INSTANCE_ID", render_instance_id)
    importlib.reload(instance_id_module)
    return instance_id_module.INSTANCE_ID


def test_prefers_render_instance_id_when_set(monkeypatch):
    value = _reload_with_env(monkeypatch, "srv-abc123-x7f2q")
    assert value == "srv-abc123-x7f2q"


def test_falls_back_to_a_local_id_when_unset(monkeypatch):
    # Self-hosted, single-instance deployments never set RENDER_INSTANCE_ID
    # — the diagnostic must still resolve to SOMETHING rather than None or
    # an empty string, or the header middleware would silently stop
    # stamping voice-stream responses everywhere except Render.
    value = _reload_with_env(monkeypatch, None)
    assert value
    assert value.startswith("local-")


def test_local_fallback_is_not_the_same_every_process(monkeypatch):
    # A fixed fallback (e.g. "local-unknown") would make every self-hosted
    # deployment report the identical id, defeating the one thing this is
    # for: telling two processes apart.
    monkeypatch.delenv("RENDER_INSTANCE_ID", raising=False)
    importlib.reload(instance_id_module)
    first = instance_id_module.INSTANCE_ID
    importlib.reload(instance_id_module)
    second = instance_id_module.INSTANCE_ID
    assert first != second


def teardown_module(module):
    # Leave the module in its real, environment-driven state for any test
    # collected after this file — reload once more against the actual
    # process environment rather than whatever the last test case set.
    importlib.reload(instance_id_module)
    assert instance_id_module.INSTANCE_ID  # sanity: reload didn't break it
