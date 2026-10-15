# MacBook Pro: minimal Bede pilot smoke package

This is the **shortest safe owner-operated test** for the **invite-only pilot**. It uses the repository's existing `docker-compose.yml` and HTTPS health endpoint. It does not create campuses, authenticate teachers, invoke Stripe, or perform destructive recovery. **Passing this script does not satisfy G1, G2 or G3.** Only synthetic learners until real Bede campus isolation is verified.

## First time

1. Install and start Docker Desktop.
2. Use the Bede Setup wizard (`setup-gui.command` in the repository, or the approved packaged installer) to configure the local instance, including a disposable local database and model provider. Keep the generated `.env` private.
3. From the Bede repository directory, run:

```bash
BEDE_SYNTHETIC_ONLY=1 bash scripts/pilot-smoke.sh start
```

Only set `BEDE_SYNTHETIC_ONLY=1` after confirming the local environment uses a disposable database containing no real learner or campus records. This is an operator acknowledgement, **not an automated proof of data isolation**.\n\nThis validates Docker/Compose, checks the configuration **without printing secrets**, starts the existing services, waits for health and probes `https://localhost/api/health` **with certificate verification against the local `bede-root-ca.crt`**. If the CA is absent, HTTPS health is BLOCKED, never reported PASS using `curl --insecure`. It saves a private evidence folder under `pilot-evidence/`. First startup may require building/downloading images. For the actual source-free Mac pilot installation, use the merged package's `Verify-Bede.command` instead of this checkout-only helper.

## Later quick check

```bash
bash scripts/pilot-smoke.sh check
```

The output contains host/commit metadata, container status, a health response and a simple manual checklist. If startup fails, inspect `docker compose ps` and `docker compose logs --tail=50 api` locally; **review and redact logs before sharing**.

## Three short manual gates (not automated by this script)

1. **G1: right people/right records.** On a disposable Bede instance with two synthetic campuses, verify allowed learner access succeeds and cross-campus/unassigned/revoked access fails. Do not use real school records until this passes on the intended build.
2. **G2: one teacher workflow.** On that build, retrieve a learner's evidence, generate an evidence-linked recommendation, approve/edit/reject, and confirm decisions persist.
3. **G3: operate and stop.** Verify manually approved participants, revoke/disable, named support, basic feedback/time baseline, and a **separately scheduled destructive restore rehearsal only on a disposable database**. The script deliberately does not execute recovery.

**Pilot commercial boundary:** free, invite-only, manually administered for an agreed period. Keep `retained_trial_access` withheld. Do not enable self-service purchasing, purchase notices, automatic paid conversion or Community continuing-access promises. PR #587 requires separate copy review.

## Result interpretation

- `PASS`: Docker/Compose and health checks actually executed.
- `FAIL`: local startup/configuration/health check failed.
- `BLOCKED`: prerequisites missing.
- `NOT RUN`: G1, G2, G3, commercial separation and recovery until independently demonstrated.

Do not run `docker compose down -v`, delete volumes, or restore into any database containing real records. Local Docker smoke evidence is **not** hosted pilot release evidence.
