"""Both Mac engineering DMGs ship with RELEASE_PROVENANCE.json beside them.

The repair loop's package evidence (scripts/release_repair) binds each
artifact to its source SHA and architecture by reading the provenance file
next to it. The Intel DMG always had one; the arm64 DMG did not, so its
package check could only ever read NOT_RUN. This pins both uploads, and that
the arm64 build checks the copied file names this build's SHA.
"""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/build-bede-operator.yml"


def _steps():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    for job in jobs.values():
        for step in job.get("steps", []):
            yield step


def _upload_paths(artifact_prefix: str) -> list[str]:
    for step in _steps():
        name = (step.get("with") or {}).get("name", "")
        if str(step.get("uses", "")).startswith("actions/upload-artifact") and name.startswith(artifact_prefix):
            return [line.strip() for line in str(step["with"]["path"]).splitlines() if line.strip()]
    raise AssertionError(f"no upload step for {artifact_prefix}")


def _dir_of(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[0] if path.endswith((".dmg", ".json", ".sha256", ".txt")) else path.rstrip("/")


def test_the_arm64_dmg_is_uploaded_with_its_provenance_beside_it():
    paths = _upload_paths("bede-mac-engineering-unnotarized-arm64-")
    dmg = next(p for p in paths if p.endswith("Bede-Engineering-Mac-arm64.dmg"))
    prov = [p for p in paths if p.endswith("/RELEASE_PROVENANCE.json")]
    assert prov, "the arm64 DMG upload carries no RELEASE_PROVENANCE.json"
    assert _dir_of(prov[0]) == _dir_of(dmg), "provenance is not beside the arm64 DMG"


def test_the_intel_dmg_upload_still_includes_its_provenance():
    paths = _upload_paths("bede-mac-engineering-unnotarized-amd64-")
    assert paths == ["dist/mac-intel-engineering/"]
    text = WORKFLOW.read_text()
    assert "dist/mac-intel-engineering/RELEASE_PROVENANCE.json" in text


def test_the_arm64_build_checks_the_copied_provenance_names_this_sha():
    script = next(
        s["run"] for s in _steps()
        if s.get("name") == "Compile branded Mac installer and package native app"
    )
    copy = script.index('"$RUNNER_TEMP/RELEASE_PROVENANCE.json"')
    check = script.index('source_sha")==os.environ["SOURCE_SHA"]')
    assert check > copy, "the SHA check must read the file that is uploaded"
