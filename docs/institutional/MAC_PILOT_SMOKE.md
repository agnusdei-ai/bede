# Bede | Mac pilot smoke and G3 certification entry point

**Current integrated code:** main `d3eb645c2de1058bb8056005a09c7d40446cea20`, with G1/G2/owner deletion and scoped tutoring integrated. The qualified underlying pilot candidate `6574a0e1b69ed3b162c39c626be316c4e457db4e` passed **146/146 synthetic checks**. This does **not** constitute a physical Mac test.

For the **complete mandatory physical-Mac certification**, use:

- [G3 physical-Mac certification runbook](MAC_G3_CERTIFICATION_RUNBOOK.md)
- [G3 evidence and owner release decision record](MAC_G3_CERTIFICATION_RECORD.md)

This page describes only the quick, non-destructive installation/health checks that prepare for G3. Never mark G3 PASS solely because a smoke test passed. Use synthetic records and identities until a separate owner release explicitly authorizes another scope.

## Option A — source-free operator archive (preferred installation evidence)

On the physical server Mac, obtain the exact-SHA `bede-operator-<SHA>-arm64.tar.gz` for Apple Silicon or `...-amd64.tar.gz` for an Intel Mac, together with its `.sha256` file, from the approved `Bede self-contained operator bundle` GitHub Actions run. Check checksum and `RELEASE`/Docker architecture before using the archive; install Docker Desktop and start Docker Compose. A source checkout is **not** needed.

From the extracted `bede-operator/` directory:

```bash
./Install-Bede.command
./Verify-Bede.command
```

The first command launches the packaged setup wizard and starts the bundled images. The second checks Docker architecture, Compose validity and **CA-verified** `https://localhost/api/health` and produces a restricted `bede-evidence/<UTC>/` folder. The resulting `manual-acceptance.txt` intentionally says NOT RUN for passkeys, campus isolation, teacher journey, recovery and release approval. Read and redact evidence before sharing.

For a teacher's **second Mac**, deliberately enable a private LAN listener during fresh installation, configure privately resolvable DNS for the server Mac, restrict firewall traffic, and verify the specific TLS CA trust on the teacher Mac. Never use `localhost` on the remote client, a raw LAN IP for a WebAuthn RP name, or a certificate-warning bypass. Refer to [TWO_MAC_TEACHER_PILOT.md](../../packaging/bundle/TWO_MAC_TEACHER_PILOT.md).

## Option B — source checkout Docker smoke (developer-only)

With the exact candidate source checked out, Docker Desktop running and a verified disposable synthetic-only database:

```bash
BEDE_SYNTHETIC_ONLY=1 bash scripts/pilot-smoke.sh start
bash scripts/pilot-smoke.sh check
```

The environment flag is an **operator assertion**, not a protective synthetic-data detector. This helper checks Docker/Compose, local configuration and trusted HTTPS health and saves `pilot-evidence/`. It does not create educators, perform WebAuthn, exercise G2 or test recovery. It must not be confused with the source-free operator artifact.

## Option C — real teacher passkey browser check (separate from package)

The installed code also has `scripts/qualification/mac_check.py`, an interactive source-checkout harness that uses a real Safari/Chrome teacher authenticator **but a virtual Chromium administrator**, local synthetic mail and inference stubs. It tests six passkey and roster outcomes, and creates `mac-check-out/mac-check-result.json`. It **recreates and later drops** its `bede_mac_check` Postgres test database, so run it only on an isolated sacrificial Postgres host. Follow the exact setup in [SYNTHETIC_QUALIFICATION.md](../SYNTHETIC_QUALIFICATION.md#real-device-check-on-a-mac-10-20-minutes-owner-run).

It cannot substitute for the packaged Mac installation, administrator lost-device recovery, whole-account educator offboarding, independent recovery-plane isolation, G2 classroom runtime or service restart/restore acceptance.

## Outcome interpretation

| Result | Meaning |
| --- | --- |
| PASS | The named script actually checked **its narrow documented scope** and recorded successful observations |
| FAIL | A required observed check failed |
| BLOCKED | Essential dependency or trust precondition was unavailable |
| NOT RUN | Scenario was not executed; never convert to PASS |

Keep `.env`, device PIN/biometric, bearer tokens, invitation links, test-user secrets, private CA keys and real learner data out of reports. Do not execute volume-destroying Compose commands or a restore against any real database.

**G3 remains a separate signed release engineering test. Pilot GO is a further distinct owner decision.**
