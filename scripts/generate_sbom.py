#!/usr/bin/env python3
"""
Regenerates docs/sbom/backend.cdx.json and docs/sbom/frontend.cdx.json —
CycloneDX 1.5 software bills of material for Bede's two dependency trees.

Deliberately hand-rolled rather than shelling out to `cyclonedx-py` /
`@cyclonedx/cyclonedx-npm`: this only needs to read requirements.txt and
package-lock.json, which are already committed and don't require a live
`pip install` / `npm install` (network access, matching Python/Node
versions, etc.) just to produce a bill of materials. If a real
vulnerability-scanning tool needs a more complete SBOM later (license
detection beyond what package-lock.json already carries, dependency
graphs, etc.), reach for one of those instead of extending this.

Usage: python3 scripts/generate_sbom.py   (run from the repo root)
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SBOM_DIR = ROOT / "docs" / "sbom"

_REQ_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*>=\s*([0-9][A-Za-z0-9.]*)")


def _parse_requirements(path: Path, scope: str) -> list[dict]:
    """requirements.txt here uses lower-bound-only pins (see CLAUDE.md /
    docs/SECURITY.md) — there is no single "the" installed version, so the
    declared floor is recorded as `version`, with a note field making that
    explicit rather than implying it's an exact resolved version the way
    the frontend's lockfile-derived entries genuinely are."""
    components = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r "):
            continue
        m = _REQ_LINE.match(line)
        if not m:
            continue
        name, _extras, version = m.groups()
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower()}@{version}",
            "scope": scope,
            "properties": [
                {"name": "bede:versionConstraint", "value": "lower-bound only (>=), not an exact pin"},
            ],
        })
    return components


def _npm_purl(name: str, version: str) -> str:
    if name.startswith("@"):
        scope, _, pkg = name[1:].partition("/")
        return f"pkg:npm/%40{scope}/{pkg}@{version}"
    return f"pkg:npm/{name}@{version}"


def _parse_package_lock(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    components = []
    for pkg_path, entry in data.get("packages", {}).items():
        if pkg_path == "" or "node_modules" not in pkg_path:
            continue  # skip the root project entry itself
        name = entry.get("name") or pkg_path.rsplit("node_modules/", 1)[-1]
        version = entry.get("version")
        if not version:
            continue  # workspace/link entries with no resolvable version
        component = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": _npm_purl(name, version),
            "scope": "optional" if entry.get("dev") else "required",
        }
        if entry.get("license"):
            component["licenses"] = [{"license": {"id": entry["license"]}}]
        components.append(component)
    # Stable order — otherwise every regeneration produces a noisy diff
    # purely from dict-iteration order.
    components.sort(key=lambda c: (c["name"], c["version"]))
    return components


def _bom(component_name: str, component_version: str, components: list[dict]) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": {"type": "application", "name": component_name, "version": component_version},
        },
        "components": components,
    }


def main() -> None:
    SBOM_DIR.mkdir(parents=True, exist_ok=True)

    backend_components = _parse_requirements(
        ROOT / "homeschool-api" / "requirements.txt", scope="required",
    ) + _parse_requirements(
        ROOT / "homeschool-api" / "requirements-dev.txt", scope="optional",
    )
    backend_bom = _bom("homeschool-api", "unversioned", backend_components)
    (SBOM_DIR / "backend.cdx.json").write_text(json.dumps(backend_bom, indent=2) + "\n")

    package_json = json.loads((ROOT / "homeschool-tutor" / "package.json").read_text())
    frontend_components = _parse_package_lock(ROOT / "homeschool-tutor" / "package-lock.json")
    frontend_bom = _bom("homeschool-tutor", package_json.get("version", "unversioned"), frontend_components)
    (SBOM_DIR / "frontend.cdx.json").write_text(json.dumps(frontend_bom, indent=2) + "\n")

    print(f"backend.cdx.json:  {len(backend_components)} components")
    print(f"frontend.cdx.json: {len(frontend_components)} components")


if __name__ == "__main__":
    main()
