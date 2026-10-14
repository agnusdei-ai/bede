"""Bede campus offline-first encrypted PostgreSQL backup.

Requires only the existing PyCryptodome dependency and docker compose already
used by Bede. No external provider/SDK/network service is required.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

MAGIC = b"BEDEBK01"
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
HEADER_SIZE = len(MAGIC) + SALT_SIZE + NONCE_SIZE
CHUNK_SIZE = 1024 * 1024


def _key(secret: str, salt: bytes) -> bytes:
    if len(secret) < 20:
        raise ValueError("Backup passphrase must be at least 20 characters")
    return hashlib.scrypt(secret.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32)


def encrypt_stream(src, dest, secret: str) -> None:
    salt, nonce = get_random_bytes(SALT_SIZE), get_random_bytes(NONCE_SIZE)
    header = MAGIC + salt + nonce
    dest.write(header)
    cipher = AES.new(_key(secret, salt), AES.MODE_GCM, nonce=nonce)
    cipher.update(header)
    while block := src.read(CHUNK_SIZE):
        dest.write(cipher.encrypt(block))
    dest.write(cipher.digest())


def decrypt_stream(src, dest, secret: str) -> None:
    header = src.read(HEADER_SIZE)
    if len(header) != HEADER_SIZE or not header.startswith(MAGIC):
        raise ValueError("Unknown or truncated encrypted backup")
    cipher = AES.new(_key(secret, header[len(MAGIC):len(MAGIC) + SALT_SIZE]), AES.MODE_GCM,
                     nonce=header[-NONCE_SIZE:])
    cipher.update(header)
    # Keep the trailing 16-byte authentication tag out of ciphertext.
    tail = b""
    while block := src.read(CHUNK_SIZE):
        tail += block
        if len(tail) > TAG_SIZE:
            body, tail = tail[:-TAG_SIZE], tail[-TAG_SIZE:]
            dest.write(cipher.decrypt(body))
    if len(tail) != TAG_SIZE:
        raise ValueError("Encrypted backup missing authentication tag")
    cipher.verify(tail)


class _Null:
    def write(self, data):
        return len(data)


def verified_backup(path: Path, secret: str) -> None:
    # Fail closed before ever writing database SQL to psql.
    with path.open("rb") as f:
        decrypt_stream(f, _Null(), secret)


def backup(path: Path, secret: str) -> None:
    if path.exists():
        raise FileExistsError("Refusing to overwrite an existing backup")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_name = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".bede-backup-", dir=path.parent)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out:
            # pg_dump is executed INSIDE the existing local PostgreSQL service.
            # No plaintext SQL is written to host disk.
            proc = subprocess.Popen(
                ["docker", "compose", "exec", "-T", "db", "pg_dump",
                 "-U", "sage", "-d", "bede", "--clean", "--if-exists"],
                stdout=subprocess.PIPE,
            )
            try:
                assert proc.stdout is not None
                encrypt_stream(proc.stdout, out, secret)
                if proc.wait() != 0:
                    raise RuntimeError("pg_dump failed: backup discarded")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
            out.flush()
            os.fsync(out.fileno())
        verified_backup(Path(temp_name), secret)
        os.link(temp_name, path)  # atomic no-overwrite publication
        os.unlink(temp_name)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def restore(path: Path, secret: str, *, acknowledge: bool) -> None:
    if not acknowledge:
        raise ValueError("Restore needs explicit --ack-replace-local-db")
    verified_backup(path, secret)
    proc = subprocess.Popen(
        ["docker", "compose", "exec", "-T", "db", "psql", "-X",
         "--set", "ON_ERROR_STOP=1", "--single-transaction", "-U", "sage", "-d", "bede"],
        stdin=subprocess.PIPE,
    )
    try:
        assert proc.stdin is not None
        try:
            with path.open("rb") as stream:
                decrypt_stream(stream, proc.stdin, secret)
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("Database restore failed")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bede local encrypted campus backup")
    parser.add_argument("action", choices=("backup", "verify", "restore"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--ack-replace-local-db", action="store_true")
    args = parser.parse_args()
    secret = os.environ.get("BEDE_BACKUP_PASSPHRASE", "")
    if not secret:
        parser.error("Set BEDE_BACKUP_PASSPHRASE using a protected secret source")
    if args.action == "backup":
        backup(args.path, secret)
    elif args.action == "verify":
        verified_backup(args.path, secret)
    else:
        restore(args.path, secret, acknowledge=args.ack_replace_local_db)
    print(f"{args.action} completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
