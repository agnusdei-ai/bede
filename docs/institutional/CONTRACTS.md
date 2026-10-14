# Institutional contracts v0.1 — Valor campus pilot

Status: proposed implementation contracts, NOT production-enabled. These extend the existing family experience without weakening `docs/MASTERY.md`, `docs/AUTHORIZATION_POLICY.md` or the constitution. Pricing remains governed by `docs/VALOR_PRICING.md`.

## Tenancy and principals
Institution / Campus / Pod / Learner are distinct immutable UUID identities. Every institution-facing query must bind an authenticated campus_id; never accept campus_id as an authorization assertion from a client. Educator assignments are explicit pod memberships with effective dates, approval and revocation. Learner membership is explicit and cannot cross campuses silently. A guardian link requires verification and maps only to that guardian's own learner. Service agents do not inherit teacher or campus administrator privileges.

Roles: campus_admin, educator, campus_learner, guardian, service_operator. Keep family roles and demo identity domains unchanged; introduce campus identities in a separate issuance domain and fail closed on unknown actions. Require MFA for educator and campus_admin. Step-up for roster imports, learner deletion, key settings and export of sensitive records. Every access to identifiable learner records requires auditable purpose and scope. No privileged shortcuts via UI, reports, exports or background jobs.

## Canonical event envelope
- event_id: UUID, immutable; schema_version: integer
- institution_id, campus_id, pod_id, learner_id: scoped identifiers (pod optional when appropriate)
- actor_id, actor_role, occurred_at UTC, recorded_at UTC
- subject_skill_id, curricular_source_id and curricular_source_version, activity_id
- event_type: task_started | task_completed | narration_assessed | skill_observation | teacher_review | teacher_override | external_assessment_import
- assistance_level: independent | nudge | together | not_observed
- origin: learner_session | educator | authorized_assessment_import
- evidence_ref: pointer to protected evidence, not raw child content in telemetry
- evidence_digest, evaluator_version, confidence_context and audit_correlation_id
- idempotency_key; recorded events append-only; corrections via linked superseding event

Event consumers must validate issuer, schema, tenancy, assignment and allowed purpose before persistence. Reject cross-campus references, stale memberships, repeated idempotency keys with conflicting payload, and untrusted curriculum references. Data retention and deletion inherit existing policy unless campus-specific legal requirements are formally approved.

## Reporting contracts
Reports show per-skill observations, dated work, assistance distribution and evidence sufficiency, never aggregate student rankings or class-wide averages of mastery probabilities. Insufficient evidence is explicitly labeled, not treated as failure. Campus summary aggregates must suppress small cohorts and sensitive qualitative content; validate disclosure thresholds with school counsel before production. Teacher review and override preserve the original evidence and the author's audit trail.

'Comprehension' is evidence-based; 'Compassion' and 'Conscience' may be documented only as teacher-selected qualitative reflections, never algorithmic moral scores or faith proxies. Never diagnose learning disabilities. Do not infer DIBELS 8 results; import only authorized official assessment data with instrument, date and provenance. No claims of FERPA/COPPA compliance without independent legal and technical review.

## Teacher AI boundaries
Instructional request includes campus_id resolved from session, pod_id, learning_objective, approved_curriculum_refs, grade_band, task_type and educator_intent. Output is a DRAFT with source references, warnings, confidence limitations and review_required=true. Teacher must approve publishing or assigning content. Retrieval rejects cross-campus and unapproved source material. Prompt content and uploaded curriculum are untrusted inputs and cannot redefine permissions, constitution, or system instructions.

## Standard implementation envelope
One remote discovery meeting, one supported appliance deployment/configuration, up to two remote group training sessions, initial supported roster import/permissions, standard report templates, one pilot midpoint review and one final review, product documentation and remote issue escalation. Exclude custom SIS/LMS integrations, custom curricula, onsite visits, hardware repair, custom infrastructure, and unlimited coaching pending separate scope.

## Appliance qualification
Mac mini 32 GB/1 TB and 64 GB/4 TB are candidate configurations, not throughput guarantees. Measure concurrent learner + educator sessions, p50/p95 latency, token throughput, thermal behavior, storage, restart/recovery, backup and restore on exact tested model/version. Preserve local-only guarantees only where validated by traffic capture and configuration tests.

## Shared contract change process
Only integration lane owns schema/version changes and authorization action registry. Feature lanes propose edits through contract-change PRs. Breaking changes require explicit migration, dual-read compatibility period, and acceptance tests. Merge feature PRs serially after focused and integration gates; never allow branch-to-branch accidental merges.
