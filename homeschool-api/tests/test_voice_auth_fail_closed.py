"""Fail-closed synthetic regression for issue #726 (no real voice data).

These tests deliberately stub model inference. They do NOT qualify the
actual Resemblyzer model, clean Python 3.12, or a physical Mac.
"""
import numpy as np
import pytest

from services import voice_auth as voice


def test_unqualified_mfcc_helper_never_issues_identity_embedding():
    with pytest.raises(RuntimeError, match="disabled"):
        voice._extract_embedding_mfcc(np.zeros(16000, dtype=np.float32))


def test_encoder_absence_denies_instead_of_using_mfcc(monkeypatch):
    monkeypatch.setattr(voice, "_get_encoder", lambda: None)
    monkeypatch.setattr(
        voice, "_extract_embedding_mfcc",
        lambda *_a, **_kw: pytest.fail("unqualified fallback was invoked"),
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        voice._extract_embedding(np.zeros(16000, dtype=np.float32))


def test_enrollment_refuses_unavailable_encoder_before_decoding(monkeypatch):
    monkeypatch.setattr(voice, "_get_encoder", lambda: None)
    monkeypatch.setattr(
        voice, "_load_wav",
        lambda *_a, **_kw: pytest.fail("audio should not be decoded"),
    )
    with pytest.raises(ValueError, match="unavailable"):
        voice._embed_samples_sync([b"synthetic", b"synthetic"])


@pytest.mark.asyncio
async def test_legacy_mfcc_profile_cannot_verify(monkeypatch):
    async def legacy_profile(_db, _student):
        return {"method": "mfcc", "embedding": [0.0] * 60}
    monkeypatch.setattr(voice, "_get_profile", legacy_profile)
    monkeypatch.setattr(
        voice, "_get_encoder",
        lambda: pytest.fail("legacy profile must be rejected before inference"),
    )
    result = await voice.verify_student("synthetic", b"not-real-audio", object())
    assert result["verified"] is False
    assert result["level"] == voice.ConfidenceLevel.LOW
    assert result["score"] == 0.0


@pytest.mark.parametrize("stored", [
    np.zeros(60),
    np.zeros(256),
    np.full(256, np.nan),
])
def test_invalid_or_degenerate_stored_embeddings_are_rejected(stored):
    with pytest.raises(ValueError, match="Invalid|Degenerate"):
        voice._score_against_profile_sync(b"synthetic", stored)


def test_trained_model_path_still_scores_valid_embeddings(monkeypatch):
    class FakeEncoder:
        def embed_utterance(self, _audio):
            return np.eye(1, 256, dtype=np.float32)[0]
    monkeypatch.setattr(voice, "_get_encoder", lambda: FakeEncoder())
    monkeypatch.setattr(voice, "_load_wav", lambda *_a: np.zeros(16000, dtype=np.float32))
    stored = np.eye(1, 256, dtype=np.float32)[0]
    assert voice._score_against_profile_sync(b"synthetic", stored) == pytest.approx(1.0)


def test_bad_trained_model_output_denied(monkeypatch):
    class FakeEncoder:
        def embed_utterance(self, _audio):
            return np.full(256, np.nan)
    monkeypatch.setattr(voice, "_get_encoder", lambda: FakeEncoder())
    monkeypatch.setattr(voice, "_load_wav", lambda *_a: np.zeros(16000, dtype=np.float32))
    stored = np.eye(1, 256, dtype=np.float32)[0]
    with pytest.raises(ValueError, match="Invalid"):
        voice._score_against_profile_sync(b"synthetic", stored)

@pytest.mark.asyncio
async def test_invalid_model_embedding_never_creates_profile(monkeypatch):
    class BadEncoder:
        def embed_utterance(self, _audio):
            return np.zeros(256, dtype=np.float32)
    monkeypatch.setattr(voice, "_get_encoder", lambda: BadEncoder())
    monkeypatch.setattr(voice, "_load_wav", lambda *_a: np.zeros(16000, dtype=np.float32))
    async def forbid_save(*_a, **_kw):
        pytest.fail("invalid profile must never be persisted")
    monkeypatch.setattr(voice, "_save_profile", forbid_save)
    with pytest.raises(ValueError, match="No samples could be processed"):
        await voice.enroll_student("synthetic", [b"sample-1", b"sample-2"], object())


@pytest.mark.asyncio
async def test_opposing_model_samples_cannot_save_zero_mean(monkeypatch):
    a = np.eye(1, 256, dtype=np.float64)[0]
    monkeypatch.setattr(voice, "_embed_samples_sync", lambda *_a: [a, -a])
    async def forbid_save(*_a, **_kw):
        pytest.fail("degenerate mean must never be persisted")
    monkeypatch.setattr(voice, "_save_profile", forbid_save)
    with pytest.raises(ValueError, match="Degenerate"):
        await voice.enroll_student("synthetic", [b"sample-1", b"sample-2"], object())


@pytest.mark.asyncio
async def test_enrollment_requires_two_valid_samples(monkeypatch):
    good = np.eye(1, 256, dtype=np.float64)[0]
    monkeypatch.setattr(voice, "_embed_samples_sync", lambda *_a: [good])
    async def forbid_save(*_a, **_kw):
        pytest.fail("one valid sample must not create a biometric profile")
    monkeypatch.setattr(voice, "_save_profile", forbid_save)
    with pytest.raises(ValueError, match="two valid"):
        await voice.enroll_student("synthetic", [b"sample-1", b"bad-sample"], object())


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [
    {"method": "resemblyzer"},
    {"method": "resemblyzer", "embedding": "invalid"},
    {"method": "resemblyzer", "embedding": [0.0] * 60},
    {"method": "resemblyzer", "embedding": [0.0] * 256},
    [],
])
async def test_malformed_profile_denied_without_server_error(monkeypatch, profile):
    async def malformed(_db, _student):
        return profile
    monkeypatch.setattr(voice, "_get_profile", malformed)
    result = await voice.verify_student("synthetic", b"not-real-audio", object())
    assert result["verified"] is False
    assert result["level"] == voice.ConfidenceLevel.LOW
    assert result["score"] == 0.0


@pytest.mark.asyncio
async def test_corrupt_encrypted_profile_denied_without_leaking_error(monkeypatch):
    async def unreadable_profile(_db, _student):
        raise ValueError("synthetic authentication tag mismatch")

    monkeypatch.setattr(voice, "_get_profile", unreadable_profile)
    monkeypatch.setattr(
        voice, "_get_encoder",
        lambda: pytest.fail("profile read failure must not invoke biometric inference"),
    )
    result = await voice.verify_student("synthetic", b"not-real-audio", object())
    assert result["verified"] is False
    assert result["level"] == voice.ConfidenceLevel.LOW
    assert result["score"] == 0.0
    assert "authentication tag" not in result["message"]


def test_packaged_resemblyzer_encoder_cpu_inference_on_synthetic_waveform(monkeypatch):
    """Exercise real packaged weights on Linux CI, without learner voice data.

    This is a model-import/inference smoke test, NOT speaker-discrimination,
    enrollment/verification accuracy, or physical Mac qualification.
    """
    monkeypatch.setattr(voice, "_encoder", None)
    monkeypatch.setattr(voice, "_encoder_load_attempted", False)
    encoder = voice._get_encoder()
    assert encoder is not None, "Packaged speaker encoder must load or voice auth stays disabled"

    sample_rate = 16000
    t = np.arange(2 * sample_rate, dtype=np.float32) / sample_rate
    synthetic = (
        0.06 * np.sin(2 * np.pi * 180 * t)
        + 0.025 * np.sin(2 * np.pi * 360 * t)
    ).astype(np.float32)
    embedding = np.asarray(voice._extract_embedding(synthetic))
    assert embedding.shape == (256,)
    assert np.all(np.isfinite(embedding))
    assert np.linalg.norm(embedding) > 1e-6
