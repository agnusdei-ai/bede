"""The Anthropic SDK 1.x removed `temperature`/`top_p`/`top_k` from
messages.create() and .stream(); passing one is a TypeError raised client-side.

services/moderation.py passes `temperature=0` on every tutoring turn, and
classify_child_message() FAILS OPEN on any exception — so an unadapted call
would not raise anywhere visible. It would silently stop classifying, and the
pre-turn self_harm / violence / sexual_content gate would pass everything
through with nothing in the logs saying so. That is why this is pinned by a
test rather than left to the type checker.

The parameter is adapted per-adapter rather than deleted upstream: every other
adapter still takes it as an ordinary kwarg (openai_compatible_adapter reads
`temperature` explicitly when building its request), so deleting it at the call
site would drop the setting on the OpenAI, Mistral and local paths to fix a
problem only Anthropic has.
"""
import inspect

import pytest

from services.adapters.router import _SDK_REMOVED_SAMPLING_PARAMS, _kwargs_for


def test_the_anthropic_path_carries_no_removed_parameter_at_top_level():
    adapted = _kwargs_for("anthropic", {"model": "m", "max_tokens": 8, "temperature": 0})
    for param in _SDK_REMOVED_SAMPLING_PARAMS:
        assert param not in adapted, f"{param} would reach the 1.x SDK and raise TypeError"
    assert adapted["extra_body"]["temperature"] == 0, "the setting must still reach the API"
    assert adapted["model"] == "m" and adapted["max_tokens"] == 8


def test_temperature_zero_survives_being_falsy():
    """`temperature=0` is the value this codebase actually passes. A truthiness
    check instead of a membership check would drop it and silently change the
    classifier from deterministic to sampled."""
    assert _kwargs_for("anthropic", {"temperature": 0})["extra_body"]["temperature"] == 0


@pytest.mark.parametrize("name", ["openai", "mistral", "local"])
def test_every_other_adapter_still_receives_it_as_a_normal_kwarg(name):
    """openai_compatible_adapter._build_request reads kwargs["temperature"].
    Moving it into extra_body for these adapters would drop it on the floor."""
    kwargs = {"model": "m", "temperature": 0}
    assert _kwargs_for(name, kwargs) == kwargs


def test_an_existing_extra_body_is_preserved():
    adapted = _kwargs_for("anthropic", {"temperature": 0, "extra_body": {"metadata": {"k": "v"}}})
    assert adapted["extra_body"]["metadata"] == {"k": "v"}
    assert adapted["extra_body"]["temperature"] == 0


def test_an_explicit_extra_body_value_wins():
    """A caller that already spelled the parameter out in extra_body meant it."""
    adapted = _kwargs_for("anthropic", {"temperature": 0, "extra_body": {"temperature": 0.7}})
    assert adapted["extra_body"]["temperature"] == 0.7


def test_the_callers_kwargs_are_not_mutated():
    """The failover loop may hand the same dict to a second adapter after the
    first errors. Mutating it would leak the Anthropic shape onto the next."""
    original = {"model": "m", "temperature": 0}
    _kwargs_for("anthropic", original)
    assert original == {"model": "m", "temperature": 0}


def test_a_call_with_no_sampling_parameter_is_passed_through_unchanged():
    kwargs = {"model": "m", "max_tokens": 8}
    assert _kwargs_for("anthropic", kwargs) is kwargs


def test_both_dispatch_paths_adapt_their_kwargs():
    """create() and stream() are separate call sites in the failover client.
    Fixing one and not the other is the shape of defect this catches."""
    from services.adapters import router

    source = inspect.getsource(router)
    assert "adapter.messages.create(**_kwargs_for(name, kwargs))" in source
    assert "adapter.messages.stream(**_kwargs_for(name, self._kwargs))" in source


def test_moderation_still_asks_for_a_deterministic_classification():
    """If someone 'fixes' the SDK error by deleting the parameter instead, the
    classifier goes from deterministic to sampled with no test failing. This is
    the guard against that being the quiet outcome."""
    from services import moderation

    source = inspect.getsource(moderation)
    assert "temperature=0" in source
