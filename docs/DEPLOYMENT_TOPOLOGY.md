# Deployment Topology

What Bede is built to run on, whether Kubernetes or Rancher is warranted,
and — the part that matters most — **exactly which security controls stop
working if it is replicated**, since several fail silently rather than
loudly.

## Short answer on Kubernetes / Rancher

**Not required, and for the primary deployment shape, not recommended.**

Bede's target is a single always-on machine on a family's LAN, down to a
Raspberry Pi (`docs/PARENT_SETUP.md`). The stack is five containers with no
horizontal scaling story, no service mesh to justify, and a single-writer
Postgres. Kubernetes would add a control plane, a CNI, ingress
configuration, and a whole operational vocabulary to a system whose install
instruction is currently `make setup` and whose operator is a parent.

That is not a cost/benefit judgement about Kubernetes generally. It is that
**the orchestration problem Kubernetes solves does not exist here**: there
is nothing to schedule across nodes, nothing to scale on demand, and no
multi-tenancy to isolate. Compose is the right weight for a single-node
appliance, and swapping it for Kubernetes on a Pi trades a working
deployment for a harder one with no property gained.

The public demo is a single free-plan Render web service (`render.yaml`).
Same conclusion, different reason: it is one instance, and the platform
already handles the little orchestration it needs.

### When it would genuinely be warranted

Three shapes would change the answer, and only one is plausibly on the
roadmap:

| Scenario | Warranted? | Note |
|---|---|---|
| **Co-op / multi-household deployment** — the `coop` license tier exists (`core/licensing.py`, 40-seat examples in `scripts/issue_license.py`) | **Possibly** | A co-op serving many families from shared infrastructure is a genuinely different operational problem: multiple instances, upgrade coordination, real availability expectations. This is the realistic case. |
| **Demo at meaningful traffic** | Maybe | Only if the single instance stops coping. Today it does. |
| **Family instance** | No | Adding an orchestrator to a one-family appliance is strictly worse. |
| **Rancher specifically** | Only with the above | Rancher (or k3s) is a reasonable *choice* if Kubernetes is warranted at all — k3s in particular is light enough for ARM/edge hardware. It does not change *whether* it's warranted. |

**Before any of those, read the next section.** Bede is not currently safe
to replicate, and that is a code property, not a manifest property — no
amount of Kubernetes configuration fixes it.

## What breaks under replication

Every item below is correct on a single instance and silently wrong across
replicas. None fails loudly. This is the actual work that "support
Kubernetes" would require, and it is all in the application, not the
deployment.

### Security-relevant

| Component | Single instance | Replicated | Status |
|---|---|---|---|
| `core/parent_credential.py` — `credentials_version` | Correct | **Was: a password change on replica A did not invalidate stolen tokens on replica B until B restarted** — "change your password to end a takeover" would be true on one replica and false on the others | **Fixed 2026-08-02**: bounded to `_REFRESH_INTERVAL_SECONDS` (10s) by a periodic re-sync |
| `core/child_throttle.py` — brute-force delay | Correct | Free-attempt allowance becomes `3 × replicas`; an attacker spreading guesses across pods resets the escalation | **Open** — needs a shared store |
| `core/middleware.py` — rate limiting | Correct | Effective limit becomes `limit × replicas` | **Open** — already disclosed in `docs/SECURITY.md` |
| `core/audit.py` — E009 anomaly windows | Correct | Thresholds easier to stay under by spreading requests | **Open** — already disclosed |

The `credentials_version` one was the serious one, and worth spelling out
because of *how* it hid: the module's own docstring claimed the startup
re-sync covered "a version set by a different replica." It does — but only
for a replica that has not started yet. A **running** replica never learns
of a sibling's bump. The mechanism that makes password change end a session
takeover would have been quietly partial, with nothing reporting a fault.

It is now bounded by a periodic refresh rather than removed, deliberately:
the in-process cache exists so `core/deps.py`'s per-request check is an int
comparison rather than a database round trip, on every authenticated
request, on a Pi. One small query per replica per 10 seconds preserves that
and caps the exposure window.

### Functional

| Component | Replicated behavior |
|---|---|
| `services/streaming_transcription.py` — `_sessions` | A voice session started on one replica cannot continue on another. Requires sticky sessions, or a shared store. |
| `core/license_state.py`, `core/provider_state.py` | A license applied or provider switched on one replica is invisible to others until restart. Lower stakes than credentials, same staleness shape. |
| `services/ai_service.py` prompt caches | Benign — TTL'd read-through caches; worst case is a few redundant queries. |
| Local voice/Whisper models | Every replica loads its own copy. Memory cost multiplies; no correctness issue. |

### What is already replication-safe

Worth stating so a future migration knows what it does *not* need to touch:
`core/encryption.py`'s `DATA_KEY` (derived identically from the same
`MASTER_SECRET` on every replica), `core/demo_code_session.py` and
`core/diagnostic_preview_quota.py` (both DB-backed by design),
`core/parent_lockout.py` (DB-backed, explicitly so a restart cannot reset
an attacker's progress), and all persisted data.

Note the pattern: the components built DB-backed are fine, and the ones
built in-process for latency are the landmines. That was the right call for
the deployment shape that exists — the point is that the choice is
load-bearing and undocumented until now.

## If replication is ever pursued

In order, because the later items are pointless without the earlier ones:

1. **Move the four security-relevant in-process stores to a shared
   backend** (Redis, or Postgres if adding a dependency is unwelcome).
   `child_throttle` and rate limiting are the two that currently weaken
   under scale; the anomaly watch follows the same pattern.
2. **Decide sticky sessions vs. shared state for voice streaming.** Sticky
   is cheaper and adequate.
3. **Re-examine every "not a gap for a single-family instance" judgement**
   in `docs/SECURITY.md`. Several controls are justified by exactly that
   assumption, and replication invalidates the justification rather than
   the control.
4. **Then**, and only then, write manifests. k3s/Rancher is a sensible
   target for ARM or edge hardware if the co-op case materializes.

Doing (4) first would produce a deployment that appears to work while
several security controls quietly do not — which is the same failure
pattern as the inert exfiltration guard in `docs/SECURITY.md`'s closed
gaps, and is the reason this document exists rather than a Helm chart.
