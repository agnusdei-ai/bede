"""Subject packs for the Practice Coach (docs/PRACTICE_COACH.md).

The core pipeline is subject-agnostic; everything that knows what a Latin or
spelling mistake *means* lives in a pack, so adding a subject never changes
the core. A pack is a package next to this file with:

    manifest.json        id, display name, grade bands, what it detects
    taxonomy.json        error categories, each with a remediation_strategy
    extract_hints.md     what to look for when reading this subject's pages
    item_bank/           curated content the pack may draw practice from
    golden/              hand-typed fixtures, never real photos
    __init__.py          classify_errors / find_strengths / generate_practice

Registration is explicit (`_PACKS` below) rather than discovered from the
directory, so a half-written pack cannot become reachable by accident.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

_HERE = Path(__file__).resolve().parent

# Pack id -> package name. Adding a pack is a folder plus one line here.
_PACKS = {"latin": "latin"}


@dataclass(frozen=True)
class SubjectPack:
    id: str
    root: Path
    manifest: dict
    taxonomy: dict
    extract_hints: str
    classify_errors: Callable[..., list]
    find_strengths: Callable[..., list]
    generate_practice: Callable[..., Any]

    def knows(self, category: str) -> bool:
        return category in self.taxonomy.get("categories", {}) or category in self.taxonomy.get("strengths", {})


_cache: dict[str, SubjectPack] = {}


def _load(pack_id: str) -> SubjectPack:
    root = _HERE / _PACKS[pack_id]
    module = importlib.import_module(f"{__name__}.{_PACKS[pack_id]}")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("id") != pack_id:
        raise ValueError(f"pack {pack_id!r} manifest declares id {manifest.get('id')!r}")
    return SubjectPack(
        id=pack_id,
        root=root,
        manifest=manifest,
        taxonomy=json.loads((root / "taxonomy.json").read_text(encoding="utf-8")),
        extract_hints=(root / "extract_hints.md").read_text(encoding="utf-8"),
        classify_errors=module.classify_errors,
        find_strengths=module.find_strengths,
        generate_practice=module.generate_practice,
    )


def get_pack(pack_id: str) -> Optional[SubjectPack]:
    if pack_id not in _PACKS:
        return None
    if pack_id not in _cache:
        _cache[pack_id] = _load(pack_id)
    return _cache[pack_id]


def available_packs() -> list[dict]:
    out = []
    for pack_id in _PACKS:
        pack = get_pack(pack_id)
        out.append({"id": pack.id, "display_name": pack.manifest.get("display_name", pack.id)})
    return out
