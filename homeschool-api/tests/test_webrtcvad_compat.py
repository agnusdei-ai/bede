"""Synthetic compatibility checks for the #726 single-provider VAD fix."""
from importlib import metadata
from pathlib import Path

import webrtcvad


def test_in_tree_wrapper_uses_installed_legacy_distribution():
    assert Path(webrtcvad.__file__).resolve() == Path(__file__).resolve().parents[1] / "webrtcvad.py"
    assert webrtcvad.__version__ == metadata.version("webrtcvad")
    providers = metadata.packages_distributions().get("webrtcvad", [])
    assert providers == ["webrtcvad"], f"overlapping VAD distributions: {providers!r}"


def test_real_vad_extension_accepts_synthetic_silence():
    assert webrtcvad.valid_rate_and_frame_length(16000, 320)
    assert webrtcvad.Vad(1).is_speech(bytes(640), 16000) is False
