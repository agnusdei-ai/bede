"""The live upload probe (scripts/live_upload_check_probe.py) must send
requests the real API accepts. Its first live run returned 422 on both chat
checks because it sent grade_stage "core_mastery" where the API takes "3-5";
a probe the API refuses says nothing about the deployment."""
import importlib.util
from pathlib import Path

from models.practice import ReadPhotosRequest
from models.schemas import TutorRequest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_upload_check_probe.py"
_spec = importlib.util.spec_from_file_location("live_upload_check_probe", _PATH)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def test_the_chat_turn_is_a_valid_tutor_request():
    TutorRequest(**probe.chat_body(probe.tree_drawing()))


def test_the_upload_is_a_valid_read_request():
    ReadPhotosRequest(**probe.upload_body(probe.worksheet()))


def test_main_sends_these_bodies():
    src = _PATH.read_text()
    assert "chat_body(image)" in src and "upload_body(image)" in src
