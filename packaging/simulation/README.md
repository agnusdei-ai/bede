# Bede installer simulation (Mac, Linux, Docker Desktop Windows)

This is an **engineering fixture**, not a Bede runtime image. It never requests a GitHub credential, never pulls Bede images, and does not handle real student data.

For Mac: install/start Docker Desktop, open Terminal, run `bash packaging/simulation/Run-Bede-Installer-Test.command` from the repository root. For Windows or Linux, use `docker compose -f packaging/simulation/compose.yaml -p bede-installer-sim up -d --build` and check `http://127.0.0.1:18766/health`.

First run pulls the small Python Alpine base image from Docker Hub if not cached. The exact bandwidth and image size must be measured, not assumed. Cleanup: `docker compose -f packaging/simulation/compose.yaml -p bede-installer-sim down`.

This proves only Docker prerequisites, image build, ARM64/AMD64 execution, loopback port binding and synthetic health. It does **not** prove production image delivery, application startup, TLS/CA, passkeys/WebAuthn, recovery, offboarding, SBOM or G3 certification. Do not use it to clear those gates. The permanent school distribution channel is a later decision.
