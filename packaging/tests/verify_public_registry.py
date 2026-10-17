"""Fail closed unless every pinned pilot image is downloadable anonymously.

This probe deliberately uses urllib with no Docker credentials, no GitHub token,
and no ~/.docker/config.json. A private GHCR package must fail this check.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ACCEPT = ", ".join((
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
))


def probe(image, digest):
    if image.startswith("ghcr.io/"):
        registry = "ghcr.io"
        repo = image[len("ghcr.io/"):].split(":", 1)[0]
    elif image.startswith(("postgres:", "caddy:")):
        registry = "registry-1.docker.io"
        repo = "library/" + image.split(":", 1)[0]
    else:
        raise ValueError("Unrecognized registry: " + image)
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Invalid image digest")
    if registry == "ghcr.io":
        token_url = "https://ghcr.io/token?" + urlencode({"scope": f"repository:{repo}:pull", "service": "ghcr.io"})
    else:
        token_url = "https://auth.docker.io/token?" + urlencode({"scope": f"repository:{repo}:pull", "service": "registry.docker.io"})
    with urlopen(Request(token_url, headers={"User-Agent": "Bede-anonymous-pilot-probe"}), timeout=20) as response:
        token = json.load(response)["token"]
    url = f"https://{registry}/v2/{repo}/manifests/{digest}"
    request = Request(url, method="GET", headers={"Authorization": "Bearer " + token, "Accept": ACCEPT})
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError("Manifest not accessible")


def main(path):
    rows = [line.split() for line in Path(path).read_text().splitlines() if line.strip()]
    if len(rows) != 6 or any(len(row) != 2 for row in rows):
        raise ValueError("Expected six pinned image references")
    failures = []
    for image, digest in rows:
        try:
            probe(image, digest)
            print("ANONYMOUS PULL OK:", image)
        except Exception as exc:
            failures.append(image)
            print("ANONYMOUS PULL FAILED:", image, type(exc).__name__, file=sys.stderr)
    if failures:
        raise SystemExit("BLOCKED: image distribution requires authentication; no pilot installer will be published. Configure GHCR package visibility as Public and rerun.")


if __name__ == "__main__":
    main(sys.argv[1])
