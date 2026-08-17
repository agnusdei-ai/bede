#!/usr/bin/env python3
"""Compute the SHA-256 digest of a constitution file, for pinning in code.

    python pin_digest.py path/to/constitution.json
    python pin_digest.py path/to/constitution.json --check <expected>

This exists as a script rather than a one-liner so that the act of re-pinning is
a deliberate, visible step someone performs and mentions in a pull request --
not something that happens as a side effect of an editor save.

A re-pin should never appear in a commit by itself. It belongs in the same
reviewed commit as the constitution change that produced it, with a written
reason. If you find a commit that only re-pins the digest, that is the shape of
an unreviewed governance change and it is worth asking about.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="Path to the constitution JSON file")
    parser.add_argument("--check", metavar="DIGEST", help="Exit non-zero unless the file matches this digest")
    args = parser.parse_args()

    if not args.path.is_file():
        print(f"error: {args.path} is not a file", file=sys.stderr)
        return 2

    try:
        json.loads(args.path.read_bytes())
    except json.JSONDecodeError as exc:
        print(f"error: {args.path} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    actual = digest_of(args.path)

    if args.check:
        if actual == args.check:
            print(f"ok: {args.path} matches the pinned digest")
            return 0
        print(f"MISMATCH\n  expected: {args.check}\n  actual:   {actual}", file=sys.stderr)
        return 1

    print(actual)
    print(f'\nPin it:\n    PINNED_SHA256 = "{actual}"', file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
