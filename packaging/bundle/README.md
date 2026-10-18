# Bede controlled deployment — operator package

## Start here: Valor prepilot (no setup required)

1. Extract this archive and open **Open-Bede-Prepilot.html** in any modern browser.
2. Follow the four steps with the fictional learner: official result → teacher observation → Data Day decision → downloadable review record.
3. This experience is **synthetic and self-contained**. It does not ask for passwords, API keys, a learner PIN, Docker, school-system access or personal information. It never sends data to a server and does not claim to run official assessment scoring or Bede inference.

**Do not enter real learner information.** This is the low-friction review of what a school administrator will see, not the authenticated pilot or a production record. Data remains in the browser tab until closed; a local JSON review can be downloaded. The trace is illustrative, not the server's immutable audit.

## When your school is ready to test an actual installation

Use \`Install-Bede.command\` (Mac) or the approved platform launcher. The real software still needs Docker Engine/Compose, an authorized license, a properly configured private HTTPS origin and actual passkey verification. A first-run wizard configures the environment; the walkthrough above does not.

If installation stops, the installer prints a plain-language **stage** and writes a **secret-free diagnostic** in \`bede-support/setup-*.log\` beside the installer. The report contains the package SHA, architecture, Docker readiness, stage and exit status. It intentionally does **not** collect credentials, .env files, student records, docker logs or form contents. Share only the report after inspecting it.

This bundle includes Compose configuration, the Caddy TLS proxy configuration,
and a launcher. **No source checkout or compiler is required.**
Images are included in images.tar and keyed to an immutable Git commit SHA; no image download is required.

The first run creates a permission-restricted `.env` template and exits.
Fill the credentials and deployment settings privately, then launch again.
Docker Engine + Compose and a valid Bede license are still required.

This is **a controlled engineering qualification package**, not a public
school rollout installer. The archive contains no generated credentials or
model weights. The operator must supply a licensed inference provider and
trusted HTTPS name. The bundled Caddy gateway listens on loopback only.
Enrollment passkeys require a browser origin that matches
`WEBAUTHN_ORIGIN`, RP ID and an explicitly trusted certificate.

For organizational test enrollment, use the exact-address allowlist only
after PR #575 has been released into the image tag. Do not put actual Valor
student records in this installation until tenant isolation is qualified.

The final consumer-ready graphical wizard and verified release distribution
remain release gates; this first package removes the full source download.


## CPU architecture selection

The release produces two distinct Linux-container payloads:

| Package suffix | Native Docker engine architecture | Hosts |
| --- | --- | --- |
| `amd64` | x86_64 / Intel or AMD 64-bit | Linux x86_64, Intel Mac Docker Desktop, Windows x64 Docker Desktop |
| `arm64` | AArch64 / ARMv8 64-bit | Raspberry Pi 5 running 64-bit Linux, Apple Silicon Docker Desktop, ARM64 Windows with Linux-container support |

The launchers check **Docker's engine architecture** before importing images and reject the wrong package. Container platforms and inference capacity are different concerns: a Pi 5 needs a 64-bit OS, working Docker, suitable free memory, and a separately qualified local or external model service. A built ARM64 image does not establish acceptable model latency, concurrency, voice model readiness, or production classroom capacity.

The GitHub CI package job builds and seals each architecture on a matching native Linux runner. The Windows and macOS checks validate launcher syntax only until actual Docker startup and passkey enrollment tests have been run on those hosts. Do not call a target architecture supported until its image build and smoke tests pass.

No raw application source or developer build tools are needed on the operator's machine.

## Two-Mac educator pilot (explicit private LAN mode)

By default this bundle publishes Bede **only to localhost**. To let an
older Mac use the Mac mini as its server, select **Allow an approved teacher
Mac on my private network** in the wizard, give the Mac mini's stable private
IPv4 address, and an organization-controlled DNS name resolved on the older
Mac. Docker binds only that IPv4 interface in addition to localhost. Do not
forward router ports to the internet. Restrict host firewall access to the
approved teacher devices. The browser must trust the Bede Caddy local CA
for the exact hostname and its WebAuthn origin before passkey registration.
The server cannot directly see a client Mac's Touch ID; Bede's frontend uses
the client browser's platform authenticator probe. A security key or phone
may work if supported by the browser. The educator never enters their local
biometric or PIN in Bede. The two-Mac setup needs actual device qualification
and cross-campus synthetic tests before live learners.

`Verify-Bede.command` creates a private, non-destructive smoke evidence folder,
not a G1/G2/G3 sign-off. The operator installer includes built application
images; no repo download is required. The package remains an engineering
qualification artifact until Mac hardware tests complete.

## Valor executive case and practice support

Open `Valor-Executive-Business-Case.html` for the branded, editable annual expense, avoided-cash-cost and teacher-capacity model. Use `Valor-Prepilot-Walkthrough.html` for the separate synthetic teacher journey. Test preparation and original practice materials belong to Bede's broader teacher-guided product vision; learner-facing delivery and official proprietary assessment forms are not part of the Valor pilot.
