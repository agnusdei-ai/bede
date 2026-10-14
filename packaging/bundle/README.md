# Bede controlled deployment — operator package

This bundle includes Compose configuration, the Caddy TLS proxy configuration,
and a launcher. **No source checkout or compiler is required.**
Images are pulled from GitHub Container Registry by an immutable Git SHA tag.

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
