"""
Speaker verification for student identity checks.

Voice authentication requires the trained Resemblyzer GE2E speaker encoder.
The previous MFCC fallback is disabled: its mean-centered features produced
near-zero embeddings and could not reliably authenticate a speaker.
If the model is unavailable, enrollment and verification fail closed.

Confidence thresholds:
  ≥ 0.82   → HIGH    (auto-pass)
  0.68–0.82 → MEDIUM (parent can override)
  < 0.68   → LOW     (deny, retry)

Profiles are stored as AES-256-GCM-encrypted BYTEA rows in the voice_profiles
table — one row per student. Embeddings never appear in plaintext outside this
module and are never returned to API callers.
"""

import asyncio
import io
import logging
import threading
from typing import Optional

import numpy as np
import soundfile as sf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import VoiceProfile
from core.encryption import aad_for, decrypt_json, encrypt_json

logger = logging.getLogger(__name__)

# ── Lazy trained encoder; fail closed if unavailable ──────────────────────
# Loaded lazily, NOT at import time: constructing VoiceEncoder() loads a torch
# model, and this module is imported (via routers/voice.py) before uvicorn can
# accept its first request — an import-time load added the full model-load
# latency to every API boot, even for deployments that never use voice auth.
_encoder = None
_encoder_load_attempted = False
_encoder_lock = threading.Lock()


def _get_encoder():
    """Blocking on first call — only call from a worker thread (or preload())."""
    global _encoder, _encoder_load_attempted
    if _encoder is not None or _encoder_load_attempted:
        return _encoder
    with _encoder_lock:
        if _encoder is not None or _encoder_load_attempted:
            return _encoder
        try:
            from resemblyzer import VoiceEncoder  # type: ignore
            _encoder = VoiceEncoder()
            logger.info("Voice auth: using resemblyzer (GE2E model)")
        except Exception:
            logger.warning("Voice auth: speaker encoder unavailable; unqualified MFCC fallback disabled")
        finally:
            _encoder_load_attempted = True
        return _encoder


def preload() -> None:
    """Best-effort warm-up so the first voice verification of the day doesn't
    pay the model-load latency. Blocking — run in an executor (see main.py's
    startup warm-up task)."""
    _get_encoder()

THRESHOLD_HIGH   = settings.voice_threshold_high
THRESHOLD_MEDIUM = settings.voice_threshold_medium


# ── Audio loading ────────────────────────────────────────────────────────────

def _load_wav(audio_bytes: bytes, target_sr: int = 16000) -> np.ndarray:
    buf = io.BytesIO(audio_bytes)
    data, sr = sf.read(buf, dtype="float32", always_2d=False)

    if data.ndim > 1:
        data = data.mean(axis=1)

    if sr != target_sr:
        try:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(target_sr, sr)
            data = resample_poly(data, target_sr // g, sr // g)
        except Exception:
            old_len = len(data)
            new_len = int(old_len * target_sr / sr)
            data = np.interp(
                np.linspace(0, old_len - 1, new_len),
                np.arange(old_len),
                data,
            ).astype(np.float32)

    return data.astype(np.float32)


# ── Feature extraction ───────────────────────────────────────────────────────

def _extract_embedding_mfcc(audio: np.ndarray, sr: int = 16000) -> np.ndarray:
    """Unqualified biometric fallback. Never issue identity embeddings here.

    The previous mean-center/average operation returned near-zero vectors,
    making similarity depend on floating-point noise. Keep this explicit
    failure even if a future caller invokes the old helper directly.
    """
    raise RuntimeError("MFCC speaker verification is disabled until independently qualified")


def _extract_embedding(audio: np.ndarray) -> np.ndarray:
    """Blocking (torch/librosa inference) — only call from a worker thread."""
    encoder = _get_encoder()
    if encoder is None:
        raise RuntimeError("Voice encoder unavailable; biometric verification disabled")
    return encoder.embed_utterance(audio)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _embed_samples_sync(audio_samples: list[bytes]) -> list[np.ndarray]:
    """Blocking decode + embedding for enrollment — run in an executor."""
    if _get_encoder() is None:
        raise ValueError("Voice enrollment unavailable: speaker model could not be loaded")
    embeddings = []
    for idx, raw in enumerate(audio_samples):
        try:
            audio = _load_wav(raw)
            embedding = np.asarray(_extract_embedding(audio), dtype=np.float64)
            if (embedding.shape != (256,) or not np.all(np.isfinite(embedding))
                    or np.linalg.norm(embedding) < 1e-6):
                raise ValueError("Invalid or degenerate speaker encoder output")
            embeddings.append(embedding)
        except Exception as exc:
            logger.warning("Sample %d failed to process: %s", idx, exc)
    return embeddings


def _score_against_profile_sync(audio_bytes: bytes, stored: np.ndarray) -> float:
    """Blocking decode + embedding + similarity for verification — run in an
    executor. Like transcription.py, none of this may run on the event loop:
    it used to freeze every in-flight request (chat streams included) for the
    duration of each voice check."""
    if stored.shape != (256,) or not np.all(np.isfinite(stored)):
        raise ValueError("Invalid or unsupported stored voice profile")
    stored_norm = np.linalg.norm(stored)
    if stored_norm < 1e-6:
        raise ValueError("Degenerate stored voice profile")
    audio = _load_wav(audio_bytes)
    embedding = np.asarray(_extract_embedding(audio), dtype=np.float64)
    if embedding.shape != stored.shape or not np.all(np.isfinite(embedding)):
        raise ValueError("Invalid speaker encoder output")
    embedding_norm = np.linalg.norm(embedding)
    if embedding_norm < 1e-6:
        raise ValueError("Degenerate speaker encoder output")
    return _cosine_similarity(embedding / embedding_norm, stored / stored_norm)


# ── DB helpers ───────────────────────────────────────────────────────────────

# Tier 1 (biometric) under docs/DATA_CLASSIFICATION.md — the strictest tier,
# because a voice embedding is the one asset here that can't be reissued. A
# child can be given a new PIN, a new password, a new session; they cannot be
# given a new voice, so compromise is permanent in a way nothing else is.
#
# First call site migrated to the v2 (AAD-bound) envelope. Binding
# table/column/student_name means a profile blob is only valid in the row it
# was written for — copying one student's ciphertext into another's row now
# fails authentication instead of decrypting cleanly. Reads still accept v1
# blobs written before this change (core/encryption.py dispatches on the
# blob's own version byte), and each profile upgrades itself to v2 the next
# time it's written — i.e. on the student's next enrollment. No migration
# script, no bulk rewrite.
def _profile_aad(student_name: str) -> bytes:
    return aad_for("voice_profiles", "profile_enc", student_name)


async def _get_profile(db: AsyncSession, student_name: str) -> Optional[dict]:
    from core import student_keys

    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    # get_existing, never get_or_create: a read must not write, and must not
    # resurrect a key row for a student who was just shredded. None is
    # correct for a profile written before per-student keys existed — those
    # are v1/v2 under DATA_KEY and open without one.
    key = await student_keys.get_existing(db, student_name)
    return decrypt_json(row.profile_enc, _profile_aad(student_name), key)  # type: ignore


async def _save_profile(db: AsyncSession, student_name: str, profile: dict) -> None:
    from core import student_keys

    key = await student_keys.get_or_create(db, student_name)
    enc = encrypt_json(profile, _profile_aad(student_name), key)
    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        db.add(VoiceProfile(student_name=student_name, profile_enc=enc))
    else:
        row.profile_enc = enc
    await db.commit()


# ── Public API ───────────────────────────────────────────────────────────────

class ConfidenceLevel:
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


async def enroll_student(
    student_name: str,
    audio_samples: list[bytes],
    db: AsyncSession,
) -> dict:
    """Create or replace a voice profile from 2–5 audio samples."""
    if not audio_samples:
        raise ValueError("At least one audio sample is required")

    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(None, _embed_samples_sync, audio_samples)

    if not embeddings:
        raise ValueError("No samples could be processed")
    if len(embeddings) < 2:
        raise ValueError("At least two valid voice samples are required")

    mean_embedding = np.mean(embeddings, axis=0)
    mean_norm = np.linalg.norm(mean_embedding)
    if not np.isfinite(mean_norm) or mean_norm < 1e-6:
        raise ValueError("Degenerate voice enrollment samples")
    mean_embedding = mean_embedding / mean_norm

    profile = {
        "embedding":   mean_embedding.tolist(),
        "num_samples": len(embeddings),
        "method":      "resemblyzer",
    }
    await _save_profile(db, student_name, profile)

    return {
        "student_name": student_name,
        "samples_used": len(embeddings),
        "method":       profile["method"],
    }


async def verify_student(
    student_name: str,
    audio_bytes: bytes,
    db: AsyncSession,
) -> dict:
    """Compare audio against stored profile. Returns score + confidence level."""
    try:
        profile = await _get_profile(db, student_name)
    except Exception as exc:
        # Corrupt ciphertext, missing student key, or a failed database read
        # must never grant access or leak internal errors to the caller.
        logger.error("Voice profile unavailable; verification denied (%s)", type(exc).__name__)
        return {
            "verified": False,
            "score": 0.0,
            "level": ConfidenceLevel.LOW,
            "message": "Voice verification is unavailable — ask a parent to use another sign-in method.",
        }
    if profile is None:
        return {
            "verified": False,
            "score":    0.0,
            "level":    ConfidenceLevel.LOW,
            "message":  "No voice profile found — ask a parent to enrol your voice first.",
        }

    # Old MFCC profiles were derived from numerically degenerate features.
    # Never compare them with a trained-model vector or grandfather them in.
    if not isinstance(profile, dict) or profile.get("method") != "resemblyzer":
        return {
            "verified": False,
            "score": 0.0,
            "level": ConfidenceLevel.LOW,
            "message": "This voice profile needs parent-supervised re-enrollment.",
        }

    try:
        stored = np.asarray(profile["embedding"], dtype=np.float64)
        loop  = asyncio.get_running_loop()
        score = await loop.run_in_executor(None, _score_against_profile_sync, audio_bytes, stored)
    except Exception as exc:
        logger.error("Verification failed: %s", exc)
        return {
            "verified": False,
            "score":    0.0,
            "level":    ConfidenceLevel.LOW,
            "message":  "Could not process audio — please try again.",
        }

    if score >= THRESHOLD_HIGH:
        level, verified, message = ConfidenceLevel.HIGH, True, "Voice recognised! Welcome back."
    elif score >= THRESHOLD_MEDIUM:
        level, verified, message = ConfidenceLevel.MEDIUM, False, "Partial match — a parent can approve to continue."
    else:
        level, verified, message = ConfidenceLevel.LOW, False, "Voice not recognised — please try again."

    return {
        "verified":     verified,
        "score":        round(score, 4),
        "level":        level,
        "message":      message,
        "student_name": student_name,
    }


async def list_profiles(db: AsyncSession) -> list[str]:
    result = await db.execute(select(VoiceProfile.student_name))
    return list(result.scalars().all())


async def delete_profile(student_name: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


def parent_override(student_name: str) -> dict:
    return {
        "verified":        True,
        "score":           None,
        "level":           ConfidenceLevel.MEDIUM,
        "message":         f"Parent approved session for {student_name}.",
        "parent_override": True,
    }
