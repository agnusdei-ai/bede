# Bede pilot image distribution

**Standard installation must not require a GitHub account, PAT, Docker login, or school-issued registry credential.** The installer downloads digest-pinned images anonymously.

## Registry publication requirement

The four application packages `ghcr.io/agnusdei-ai/bede-api`, `bede-ui`, `bede-trust`, and `bede-wizard` must each be made **Public** in GitHub Packages by an authorized organization/package administrator. Repository visibility and `packages: write` do **not** automatically make package versions public. This is a package visibility operation, not a request to expose the private source repository.

Before distributing, review every runtime image for embedded source, credentials, personal information, and proprietary assets. A public image is inspectable and must be treated as publicly disclosed. If public GHCR images are unacceptable, use a separate anonymous-read pilot registry/CDN and update pinned references and the gate; do not ship registry credentials to schools.

The packaging workflow probes all six pinned manifest digests using anonymous HTTPS requests, independent of Docker login. If any image is private, missing, or inaccessible, the workflow fails before installer artifacts are uploaded. Public access must be tested again from an unauthenticated school network during physical Mac acceptance.

## School rollout acceptance

1. Administrator explicitly approves public runtime-image distribution after image-content review.
2. Build completes the anonymous registry probe for ARM64 and AMD64.
3. Clean Mac installation succeeds with no Docker registry credentials and without a GitHub login.
4. Record first-install network transfer, peak memory, image sizes, SBOM, vulnerability findings, and all six digests.
5. Complete physical Mac G3, recovery, and offboarding evidence before the separate owner Pilot GO decision.

Previously published standard/Lite installers with private image references are **not** approved for school distribution. The build does not change visibility by itself.
