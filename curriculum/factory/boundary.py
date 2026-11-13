"""Development boundary. No database, model, runtime registration, or network."""
import hashlib
import importlib
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "curriculum/production-spec"
sys.path.insert(0, str(SPEC))
contract = importlib.import_module("contract")
Error = contract.ContractError


def enabled():
    if (os.environ.get("BEDE_CURRICULUM_FACTORY_ENABLED") != "1"
            or os.environ.get("BEDE_FACTORY_MODE") != "development"):
        raise Error("Factory disabled; explicit development-only opt-in required")


def safe_path(path, root):
    """Reject all symlinks, including internal links, before any local file IO."""
    path, root = Path(path).absolute(), Path(root).absolute()
    if not path.is_relative_to(root) or ".." in path.parts:
        raise Error("Path outside isolated workspace")
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise Error("Symlinks are not permitted")
    return path


def store_path(path):
    return safe_path(path, ROOT / "generated-artifacts/curriculum-factory")


def tools():
    """Version plus exact code bytes, including transitive curriculum dependencies."""
    files = [*SPEC.glob("*.py"), *Path(__file__).parent.glob("*.py")]
    for directory in ("services/curriculum", "services/diagnostic"):
        files.extend((ROOT / "homeschool-api" / directory).glob("*.py"))
    files.extend(ROOT / "homeschool-api" / p for p in (
        "services/content_curation.py", "models/schemas.py",
        "services/educator_access.py", "core/encryption.py"))
    return {
        "factory_version": "1.0.0",
        "python_version": sys.version,
        "sqlite_version": sqlite3.sqlite_version,
        "code": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(set(files))},
    }
