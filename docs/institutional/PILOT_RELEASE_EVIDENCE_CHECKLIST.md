# Bede pilot launch and scale evidence checklist

**Status:** Mandatory release contract; not evidence of passing gates. **Owner:** solopreneur founder, serving as both engineering evidence owner and pilot-release approver. Record **two separate, dated decisions** even when made by the same person. Pilot date is TBD until qualification. Track live evidence and blockers in [#588](https://github.com/agnusdei-ai/bede/issues/588); integrate [#576](https://github.com/agnusdei-ai/bede/issues/576), [#584](https://github.com/agnusdei-ai/bede/issues/584) and [#585](https://github.com/agnusdei-ai/bede/issues/585).

## Mandatory release order

1. **#574** — encrypted backup, destructive restoration, key custody, offsite recovery, measured RTO/RPO and documented runbook.
2. **#575** — real WebAuthn educator invitation, enrollment, login, recovery and complete educator journeys; browser and negative security tests.
3. **#576** — immutable institution/campus/learner identities; campus and educator-to-learner authorization; tenant-scoped database, inference, SSE, exports, background jobs and encryption; positive and negative tests **on the deployed build**.
4. **#578** — final installer rebuilt against qualified commit, install/upgrade/rollback tests on applicable Linux, macOS, Windows, AMD64 and ARM64 including Raspberry Pi 5.

Parallel Bede unified UI, orchestration and learning-memory development may use **synthetic data only** until #576 deployed isolation is accepted. No real Valor student records in institutional deployment before that gate. Completion of #576 permits **integrated pilot acceptance**, not launch.

## Seven integrated sprint capabilities

- [ ] One recognizable Bede Tutor interface for learners and teachers; no separate visible agents.
- [ ] Bounded, governed orchestration of actual tools and model inference.
- [ ] Durable, tenant-scoped learner memory and session continuity.
- [ ] Evidence-grounded instructional recommendations joining assessment, lessons and interventions; source IDs, verified scoring and abstention when evidence is inadequate.
- [ ] Server-enforced educator approval for consequential instructional changes; version-bound audit trail.
- [ ] Real APIs, durable storage, Render backend and frontend, exact deployed SHA/URLs, TLS, auth and operational telemetry.
- [ ] Passing automated unit/integration/browser E2E, accessibility, privacy, security, recovery and release evidence.

## Full teacher-to-learner-to-teacher journey and measurement

- [ ] Capture baseline teacher preparation/review time and learner assessment evidence.
- [ ] Educator authenticates and accesses only assigned learners.
- [ ] Bede generates a source-linked recommendation; teacher approves, edits or rejects.
- [ ] Approved instruction reaches learner; Bede tutors; learner progress persists. (Deferred to #585: delivery is deliberately disabled and tested as disabled; the pilot UI says "recorded" / "ready for teacher use".)
- [ ] Evidence returns to educator for follow-up and next action.
- [ ] Measure real teacher time saved **net of corrections**, learner progress, teacher adoption, recommendation errors/overrides, usability feedback and operational reliability. Include denominators and inconclusive/negative outcomes. Proposed three hours/week is a hypothesis, not a proven result.

## Founder-operated device qualification matrix

The owner may supply actual evidence from the following devices; local runs supplement, but **do not replace**, CI and deployed-build evidence. Record OS/version, architecture, memory, model/runtime, commit SHA, test command, logs, timestamps and signed disposition.

| Device | Required evidence |
|---|---|
| **Apple Silicon Mac mini** | Native macOS installation, launch/update/rollback, actual WebAuthn with compatible authenticator, local inference and teacher/learner workflow, sustained concurrency, backup and destructive restore on disposable data, resource and latency traces |
| **Windows Surface Laptop** | Record exact Intel/AMD x64 or Snapdragon ARM64 SKU; native Windows install/update/rollback, Windows Hello/passkey where supported, browser teacher workflow, inference and failure/recovery logs; **do not assume architecture from model name** |
| **Raspberry Pi 5** | ARM64 OS/kernel, storage/RAM/power profile, actual packaged installer and launcher, service startup/reboot persistence, smoke and failure tests, measured inference feasibility/latency or documented remote inference dependency, backup/restore |
| **Linux AMD64** | Required separate CI/host/VM evidence for x86_64 Linux installation and runtime if not covered by one of the three physical devices |

Use **synthetic learner fixtures** with multiple campuses, same-named learners, revoked guardians, stale educator sessions, forged scopes, cross-tenant assessment/export/SSE attempts, concurrent teacher approvals, restart and backup during load. Negative tests must deny access and leave no leaked records.

## Capacity and scale proof — not implied by seats

Existing family-oriented single-node Compose/PostgreSQL and Render demo are **not** many-learner throughput proof; licensing tiers and roster bounds are not concurrency guarantees. Benchmark synthetic 25, 100, 250, 500+ enrolled learners at varied concurrent tutoring streams (1, 5, 10, 25, 50, 100 as hardware permits) plus teacher/assessment/report workloads. Capture p50/p95/p99 first-token latency, token throughput, timeout/error rates, queue depth, DB contention, CPU/GPU/RAM, cost, security isolation, soak/restart and restore results. Approve numerical SLOs and maximum supported simultaneous sessions **before** testing. Scale only to the measured hardware/environment envelope; unlimited licensed seats never means unlimited simultaneous inference. If replicas are needed, resolve shared rate limits, throttling, audit windows, session state and authorization before horizontal scaling.

## Evidence record (one row per gate/device)

| Gate / test | PR and commit SHA | CI run + conclusion | Device / OS / arch | Deploy URL + SHA | Positive + negative evidence | Measured result / SLO | Owner/date | GO / HOLD |
|---|---|---|---|---|---|---|---|---|
| _Populate with real results only_ | | | | | | | | HOLD |

## Authorization

**Engineering evidence acceptance:** owner signs dated evidence package, with explicit exceptions and blockers. **Pilot release decision:** owner separately records dated GO or HOLD, approved cohort size, maximum concurrency, monitoring, incident rollback triggers and pilot start date. Pilot remains **HOLD** until all required gates and the #585 loop pass. Customer or contractual independent-review requirements, if any, are not waived by merged founder roles. No untested merges, bypasses or invented evidence.
