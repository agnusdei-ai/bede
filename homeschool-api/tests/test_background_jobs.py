"""A background job that stops is reported rather than vanishing.

main.py's periodic jobs (data purge, credential and device-revocation
refresh, the local-AI health check, the license re-check and heartbeat) each
catch their own errors and retry, so none should ever finish. One that did,
through an error escaping its handler or a loop that returns, used to stop
without a word, and the work it did stopped with it. See docs/RELIABILITY.md.

Two layers: the watcher on its own, driven with real tasks; and the real
lifespan starting every job through it, read from main.lifespan itself rather
than a replica (the convention test_periodic_license_refresh.py follows).
"""
import asyncio
import inspect
import logging
import re

import pytest

import main


@pytest.mark.asyncio
async def test_a_job_that_raises_is_reported(caplog):
    async def boom():
        raise RuntimeError("database went away")

    def _boom_line(text):
        return "Background job data-purge stopped: RuntimeError" in text

    with caplog.at_level(logging.ERROR, logger="main"):
        task = main._start_background(boom(), "data-purge")
        with pytest.raises(RuntimeError):
            await task
        await asyncio.sleep(0)
    assert _boom_line(caplog.text)
    assert "will not run again until the API restarts" in caplog.text


@pytest.mark.asyncio
async def test_a_loop_that_returns_is_reported(caplog):
    async def returns():
        return None

    with caplog.at_level(logging.ERROR, logger="main"):
        await main._start_background(returns(), "license-refresh")
        await asyncio.sleep(0)
    assert "Background job license-refresh stopped." in caplog.text


@pytest.mark.asyncio
async def test_cancellation_at_shutdown_is_not_reported(caplog):
    async def forever():
        await asyncio.sleep(3600)

    with caplog.at_level(logging.ERROR, logger="main"):
        task = main._start_background(forever(), "credentials-refresh")
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
    assert "Background job" not in caplog.text


@pytest.mark.asyncio
async def test_a_one_shot_job_finishing_is_its_normal_end(caplog):
    async def warm():
        return None

    async def warm_fails():
        raise OSError("model files missing")

    with caplog.at_level(logging.ERROR, logger="main"):
        await main._start_background(warm(), "voice-model-warmup", one_shot=True)
        await asyncio.sleep(0)
        assert "Background job" not in caplog.text
        task = main._start_background(warm_fails(), "voice-model-warmup", one_shot=True)
        with pytest.raises(OSError):
            await task
        await asyncio.sleep(0)
    assert "voice-model-warmup stopped: OSError" in caplog.text
    assert "will not run again" not in caplog.text


_LIFESPAN = inspect.getsource(main.lifespan)


def test_the_lifespan_starts_no_unwatched_job():
    assert "asyncio.create_task(" not in _LIFESPAN, (
        "a background job is started without the watcher; if it stops, nothing says so"
    )


@pytest.mark.parametrize("job", [
    "_warm_voice_models()",
    "_periodic_data_purge()",
    "parent_credential.periodic_refresh()",
    "device_registry.periodic_refresh()",
    "_periodic_local_health_check()",
    "_periodic_license_refresh()",
    "license_heartbeat.run_periodic()",
])
def test_each_job_goes_through_the_watcher(job):
    assert re.search(r"_start_background\(\s*" + re.escape(job), _LIFESPAN), job


def test_only_the_warm_up_is_one_shot():
    assert re.findall(r"_start_background\((\w[\w.]*)\(\)[^)]*one_shot=True", _LIFESPAN) == ["_warm_voice_models"]


@pytest.mark.asyncio
async def test_the_report_never_prints_the_error_message(caplog):
    """An error's text can carry a learner's name, a row or a key. The report
    names the job, the error type and where it was raised, and nothing else."""
    secret = "Sam Example sk-live-0123456789abcdef"

    async def leaky():
        raise ValueError(f"could not purge rows for {secret}")

    with caplog.at_level(logging.ERROR, logger="main"):
        task = main._start_background(leaky(), "data-purge")
        with pytest.raises(ValueError):
            await task
        await asyncio.sleep(0)
    assert "Background job data-purge stopped: ValueError" in caplog.text
    assert "leaky" in caplog.text, "where it was raised is the actionable part and must stay"
    assert secret not in caplog.text and "sk-live" not in caplog.text and "Sam Example" not in caplog.text
