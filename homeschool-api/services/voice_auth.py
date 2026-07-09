"""
Speaker verification for student identity checks.

Two-tier approach:
  1. resemblyzer (GE2E-trained 256-dim embeddings) if available → more accurate
  2. librosa MFCC + cosine similarity fallback → reliable, no model download

Confidence thresholds:
  ≥ 0.82   → HIGH    (auto-pass)
  0.68–0.82 → MEDIUM (parent can override)
  < 0.68   → LOW     (deny, retry)

Profiles are stored as AES-256-GCM-encrypted BYTEA rows in the voice_profiles
table — one row per student. Embeddings never appear in plaintext outside this
module and are never returned to API callers.
"""

import io
import logging
from typing import Optional

import numpy as np
import soundfile as sf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import VoiceProfile
from core.encryption import decrypt_json, encrypt_json

logger = logging.getLogger(__name__)

# ── Try resemblyzer; fall back to MFCC ──────────────────────────────────────
_encoder = None
_USE_RESEMBLYZER = False

try:
    from resemblyzer import VoiceEncoder, preprocess_wav as _rz_preprocess  # type: ignore
    _encoder = VoiceEncoder()
    _USE_RESEMBLYZER = True
    logger.info("Voice auth: using resemblyzer (GE2E model)")
except Exception:
    logger.info("Voice auth: resemblyzer unavailable, using librosa MFCC fallback")

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

def _extract_embedding_resemblyzer(audio: np.ndarray) -> np.ndarray:
    return _encoder.embed_utterance(audio)  # type: ignore


def _extract_embedding_mfcc(audio: np.ndarray, sr: int = 16000) -> np.ndarray:
    import librosa  # type: ignore
    mfcc   = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=20)
    delta  = librosa.feature.delta(mfcc)
    delta2 = librosa.feature.delta(mfcc, order=2)
    features = np.concatenate([mfcc, delta, delta2], axis=0)
    features = (features - features.mean(axis=1, keepdims=True)) / (
        features.std(axis=1, keepdims=True) + 1e-9
    )
    return features.mean(axis=1)


def _extract_embedding(audio: np.ndarray) -> np.ndarray:
    return _extract_embedding_resemblyzer(audio) if _USE_RESEMBLYZER else _extract_embedding_mfcc(audio)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


# ── DB helpers ───────────────────────────────────────────────────────────────

async def _get_profile(db: AsyncSession, student_name: str) -> Optional[dict]:
    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return decrypt_json(row.profile_enc)  # type: ignore


async def _save_profile(db: AsyncSession, student_name: str, profile: dict) -> None:
    enc = encrypt_json(profile)
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

    embeddings = []
    for idx, raw in enumerate(audio_samples):
        try:
            audio = _load_wav(raw)
            emb   = _extract_embedding(audio)
            embeddings.append(emb)
        except Exception as exc:
            logger.warning("Sample %d failed to process: %s", idx, exc)

    if not embeddings:
        raise ValueError("No samples could be processed")

    mean_embedding = np.mean(embeddings, axis=0)
    mean_embedding = mean_embedding / (np.linalg.norm(mean_embedding) + 1e-9)

    profile = {
        "embedding":   mean_embedding.tolist(),
        "num_samples": len(embeddings),
        "method":      "resemblyzer" if _USE_RESEMBLYZER else "mfcc",
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
    profile = await _get_profile(db, student_name)
    if profile is None:
        return {
            "verified": False,
            "score":    0.0,
            "level":    ConfidenceLevel.LOW,
            "message":  "No voice profile found — ask a parent to enrol your voice first.",
        }

    stored = np.array(profile["embedding"])

    try:
        audio     = _load_wav(audio_bytes)
        embedding = _extract_embedding(audio)
        embedding = embedding / (np.linalg.norm(embedding) + 1e-9)
        score     = _cosine_similarity(embedding, stored)
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
