# Lite and Offline operator distribution

The build produces **two packages per architecture** from the same immutable commit and application images:

- **Lite**: `bede-operator-lite-<SHA>-arm64.tar.gz` (or amd64). No `images.tar`; contains `IMAGE_DIGESTS` and downloads the six exact pinned image digests from registries on first install. Subsequent installs can reuse local Docker layer caches. **Requires network access and GHCR pull permission** when packages are private. Registry access must be explicitly granted; do not put credentials in the archive.
- **Offline**: `bede-operator-<SHA>-arm64.tar.gz` (or amd64). Contains `images.tar` and works without image downloads; larger by design.

Both retain the same setup wizard, Compose configuration, TLS, local-only default binding, Mac verification launcher, architecture checks, and synthetic-only pilot restrictions. The Lite launcher pulls by `image@sha256:digest` and then tags the verified image with its SHA-qualified runtime tag. It refuses an absent or malformed digest manifest. The Offline launcher loads the archived images instead. Neither path falls back to floating tags.

## Operator steps

1. Download the **matching architecture** artifact and verify its adjacent `.sha256` checksum before extraction.
2. Extract the tarball. Enter `bede-operator-lite/` for Lite or `bede-operator/` for Offline.
3. Start Docker Desktop, then run `./Install-Bede.command`. For Lite, authenticate to GHCR first if the registry images are private.
4. Complete the wizard using only synthetic disposable data and approved inference, then run `./Verify-Bede.command`.
5. Record the package SHA, image digests, Docker architecture, OS, UTC timestamps and redacted results. This does not certify physical WebAuthn or release G3.

**Build caveats:** The build workflow requires GitHub Actions permission to publish GHCR packages. Existing GHCR package settings must allow the repository's workflow token to write packages and intended operators to read them. Do not make a private school image public solely for Lite distribution. First-run Lite network transfer can still be substantial: the reduction is in the downloadable **installer artifact**, not total runtime bytes. Keep the existing known-good Offline artifact for the current Mac qualification until the new workflow passes.

## School pilot download selection

GitHub Actions now publishes **four separate artifacts**, not two combined architecture bundles: `bede-lite-<SHA>-arm64`, `bede-lite-<SHA>-amd64`, `bede-offline-<SHA>-arm64`, and `bede-offline-<SHA>-amd64`. For Apple Silicon schools, select **bede-lite-…-arm64**. Do not download an Offline artifact for network-connected pilot machines. Each Lite artifact contains only the Lite archive and checksum, not `images.tar`.

**Important bandwidth limitation:** The Lite artifact is small, but the installer still pulls the full API and other pinned Docker images on first deployment. No claim of low total network usage is justified until image-layer bytes are measured and reduced. Repeated installations on separate Macs do not share Docker's local cache. A private LAN image cache or controlled distribution proxy may reduce repeat external downloads, subject to school network approval and authentication controls. Avoid removing PyTorch, Whisper or speech/authentication dependencies without capability regression tests.
