import io
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
import importlib.util

_module_path = Path(__file__).resolve().parents[2] / "scripts" / "campus_backup.py"
_spec = importlib.util.spec_from_file_location("bede_campus_backup", _module_path)
assert _spec is not None and _spec.loader is not None
_backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_backup)
encrypt_stream = _backup.encrypt_stream
decrypt_stream = _backup.decrypt_stream
verified_backup = _backup.verified_backup
backup = _backup.backup
restore = _backup.restore

SECRET = "owner-controlled-test-passphrase-not-a-real-secret"

def encrypt(data=b"synthetic campus data"):
    result = io.BytesIO()
    encrypt_stream(io.BytesIO(data), result, SECRET)
    return result.getvalue()

def test_round_trip_and_non_deterministic_ciphertext():
    source = b"synthetic educational records" * 300
    a, b = encrypt(source), encrypt(source)
    assert a != b
    assert source not in a
    output = io.BytesIO()
    decrypt_stream(io.BytesIO(a), output, SECRET)
    assert output.getvalue() == source

def test_tampering_and_wrong_key_fail():
    blob = bytearray(encrypt())
    blob[-20] ^= 1
    with pytest.raises(ValueError):
        decrypt_stream(io.BytesIO(blob), io.BytesIO(), SECRET)
    with pytest.raises(ValueError):
        decrypt_stream(io.BytesIO(encrypt()), io.BytesIO(), SECRET + "wrong")

def test_truncated_or_wrong_header_fails(tmp_path):
    for blob in (b"", b"BAD!" + encrypt()[4:], encrypt()[:-1]):
        file = tmp_path / "backup.enc"
        file.write_bytes(blob)
        with pytest.raises(ValueError):
            verified_backup(file, SECRET)

def test_restore_requires_explicit_acknowledgement(tmp_path):
    file = tmp_path / "backup.enc"
    file.write_bytes(encrypt())
    with pytest.raises(ValueError, match="explicit"):
        restore(file, SECRET, acknowledge=False)

def test_no_overwrite(tmp_path):
    file = tmp_path / "backup.enc"
    file.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        backup(file, SECRET)
    assert file.read_bytes() == b"existing"
