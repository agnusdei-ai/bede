"""Build the source-free Bede operator bundle from canonical docker-compose.yml.

Release image tags are immutable Git commit identifiers; the bundle does not
contain application source or build contexts. Requires PyYAML in CI only.
"""
from pathlib import Path
import os
import shutil
import yaml

root = Path(__file__).resolve().parents[1]
out = root / "dist" / "bede-operator"
out.mkdir(parents=True, exist_ok=True)
sha = os.environ["RELEASE_SHA"]
if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
    raise SystemExit("RELEASE_SHA must be a 40-character commit hash")
arch = os.environ["RELEASE_ARCH"]
if arch not in ("amd64", "arm64"):
    raise SystemExit("RELEASE_ARCH must be amd64 or arm64")
repository = os.environ.get("RELEASE_REPOSITORY", "ghcr.io/agnusdei-ai/bede").lower()
doc = yaml.safe_load((root / "docker-compose.yml").read_text())
for name, image in {"api": "api", "locuto-ipc": "api", "ui": "ui", "trust": "trust"}.items():
    svc = doc["services"][name]
    if "build" not in svc:
        raise SystemExit(f"Missing image build context for {name}")
    del svc["build"]
    svc["image"] = f"{repository}-{image}:sha-{sha}-{arch}"
# The normal distribution must not publish an open campus-facing listener.
doc["services"]["caddy"]["ports"] = ["127.0.0.1:80:80", "127.0.0.1:443:443"]
# DB remains optional in upstream Compose, explicitly enable in operator package.
(out / "compose.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
shutil.copy2(root / "Caddyfile", out / "Caddyfile")
shutil.copy2(root / "packaging" / "bundle" / "start.sh", out / "start.sh")
shutil.copy2(root / "packaging" / "bundle" / "Install-Bede.command", out / "Install-Bede.command")
shutil.copy2(root / "packaging" / "bundle" / "Install-Bede.ps1", out / "Install-Bede.ps1")
shutil.copy2(root / "packaging" / "bundle" / "README.md", out / "README.md")
shutil.copy2(root / "packaging" / "bundle" / ".env.example", out / ".env.example")
(out / "WIZARD_IMAGE").write_text(f"{repository}-wizard:sha-{sha}-{arch}\n")
(out / "RELEASE").write_text(sha + "\n")
(out / "ARCH").write_text(arch + "\n")
print(f"Built operator-only bundle at {out} for {sha}")
