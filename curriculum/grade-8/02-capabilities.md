# Capability inventory — local source, not deployment certification

**Historical inventory:** source statements and synthetic checks below refer to the baseline HEAD stated here, not the later integration base. Seven referenced files changed upstream before integration. See [INTEGRATION.md](INTEGRATION.md); no fresh runtime/authorization review or deployment certification is claimed.

## Evidence ladder and repository identity

**S** inspected source; **T** upstream test code located/inspected, not necessarily run; **X** a named local check actually executed; **D** deployed availability independently verified. **No capability here has D evidence.** Documentation alone is labeled **DOC**.

Root for references: `release-checkout/bede/`. Local Git metadata and origin were checked without remote calls:

- Origin: `https://github.replit.internal/agnusdei-ai/bede.git`.
- HEAD: `597057406489880a1abe3fb57ac1beaafc48e776`, dated2026-10-28, branch `feat/audience-discovery-evidence`.
- Local cached `origin/main`: `ca05646d6fddf70ca1096ed2974ccfaa338ea74f`, dated2026-10-27.
- Earlier publication evidence in the project conversation names a later main merge; this local cached ref is not current remote proof. No fetch, remote API, branch or deployed check was authorized/performed for this baseline.
- Existing dirty static-page/navigation files and a generated mockup registry were not changed by this task.

Line references identify this inspected snapshot; `source-evidence.json` records hashes. Recheck locations against any later approved checkout.

## Inventory

### C01 — Catalog and content discovery [S, T located]

`homeschool-api/services/catalog_service.py:1–80`: import-time JSON catalog loading, year/book indices and search functions. Eight `data/catalog/year*.json` files exist. Other catalog loaders include visual aids, composer metadata and faith-family orientation. Metadata loaders are not an ingestion license.

`services/content_curation.py:152–205` defines `ContentCandidate`, findings/verdicts; `:221–364` scans content/rights/skill linkage. Existing catalog sequence originated with another curriculum; **do not copy its selection structure or teaching notes into a Bede year**. Independently decide outcomes and source choices. No Grade 8 completion evidence found.

### C02 — Objectives and skill identifiers [S, X partial]

`services/curriculum/models.py:123–189` stores objective IDs and skill IDs. `services/content_curation.py:67` derives known skill IDs; `:323–364` blocks unknown tracked skills. `models.py:224–247` validates variant parent/skills. A free-form objective tuple is not a reviewed Grade 8 outcome taxonomy or prerequisites graph.

Reuse current skill identifiers after reconciliation; propose new identifiers through review rather than silently rewriting mastery history. Future factory must preserve objective/version mappings and assessment constructs. Synthetic checks exercise model invariants, not real mastery calibration.

### C03 — Source/rights/provenance gates [S, T, X model restriction]

`services/curriculum/models.py:21–33,64–80,123–154`: rights statuses, SourceRecord, edition/hash metadata and verbatim restriction. `rights_gate.py:22–131`: staging submissions, SHA-256 shape, source/URL/time/campus assertions and curation integration. A verifier name or evidence reference is **an assertion**, not authenticated identity or a legal opinion.

`tests/test_curriculum_rights_gate.py` covers synthetic staging acceptance/denials; not run here because pytest/Pydantic are unavailable. `licensed` is distinct from `public_domain_verified`; no gate weakening. Original Bede authorship does not permit quoting unlicensed third-party text.

### C04 — Persistence and staging [S, T inspected]

`services/curriculum/persistence.py:18–108`: additive campus/version keys, grants/reviews, encrypted lesson/chunk/variant bodies; explicit `create_curriculum_tables`, flag-off no DDL. `workflow.py:158–219` stages a draft and encrypts its snapshot.

No migrations or table creation run here. Encryption columns do not prove operational key management, backup behavior, source legal status or live retention qualification.

### C05 — Independent human review [S, T inspected]

`workflow.py:45–89`: current educator, credential version, WebAuthn UV, enabled campus/member and administrator-issued reviewer-grant checks; signature-verified token is an upstream prerequisite. `:222–311`: author cannot approve own work, stored evidence/digest revalidated, review encrypted, approval creates a new version and authorization rechecked before commit.

`tests/test_curriculum_workflow.py` contains synthetic SQLite/auth/tamper/independent-review cases; no DB tests executed. `docs/CURRICULUM_ORIGINAL_LESSON_REVIEW.md:8–35` states original/revised lessons need independent review. No public grant issuance/approval UI is established by this module. String heuristics in models reject obvious bot prefixes but **do not authenticate a human**; trusted workflow remains necessary.

### C06 — Local retrieval [S, T, X]

`local_hybrid_index.py:30–123`: trusted `SearchScope`, campus/private-owner/approval/rights filtering before tokenization. `:73–89`: deterministic128-dimensional signed lexical hashing, **not learned semantic embeddings**. `:126–200`: BM25/local-vector ranking with size limits.

`licensed` rights are excluded in current retrieval; original, verified-PD and appropriately private records may qualify. It has no authenticated endpoint or grant/revocation lookup. Source code and synthetic checks demonstrate selected isolation/flag behavior, not genuine campus authorization or safe production ingestion.

### C07 — Objective-gated citations [S, T, X partial]

`citation_retriever.py:29–84` defines reviewed annotations/citation wrappers; `:90–160` requires objective annotation and lexical support; reliability/alignment are asserted reviewed metadata, effectiveness score fixed0. `:161–197` projects only literal excerpts from supplied ranked hits; missing/altered excerpts are dropped.

Caller must authenticate scope, annotations and source/review binding and disclose insufficient evidence. No result is an answer engine, pedagogical validation or benchmark of citation accuracy in real use. No network is required for these primitives.

### C08 — Learner adaptation [S, T, X partial]

`models.py:190–247`: learner-scoped variants refer to approved parent/version, opaque learner ref, evidence refs and expiry. `learner_evolution.py:14–90`: evidence kinds include practice/retention/observations; `summarize_skill` is an equal-weight synthetic estimate with confidence cap0.8, **not a calibrated diagnostic**.

Useful foundations for bounded variants; not proof of accessible adaptation rules, delayed-transfer scheduling or independent performance. Never convert this score into AI-only placement or a disability diagnosis.

### C09 — Reading/accessibility [S, DOC; UI untested]

`homeschool-tutor/src/hooks/useReadingPresentation.ts:94–195`: bounded letter/line-spacing choices, parent defaults and device-local learner choices in localStorage. `docs/ACCESSIBILITY_RESEARCH.md:232–249` explicitly says no Bede child outcome tests. Other text/voice controls require separate verification before adoption.

No complete accessible weekly-packet pipeline, assistive-technology conformance or evidence these options cure dyslexia/ADHD. Device-local settings have a retention/privacy footprint; assess access and cleanup in future tests. TTS/STT need individual access evaluation; do not conflate comprehension with decoding.

### C10 — Planning and assessment [S, T inspected]

`services/lesson_planner.py:1–39,103–250`: orders a permutation of the parent's selected subjects; it does not select/drop subjects or design a Grade 8 year. Existing short-session duration assumptions must not be imported into a new workload model without review. `tests/test_lesson_planner.py` exists; not run.

Practice/mastery/diagnostic services offer inputs, not a complete Grade 8 outcome/assessment/retention/transfer system. Their accuracy and deployed availability are unverified here. Retain independent demonstrations and adult decisions; no transcript/automatic-credit claim.

### C11 — Practice coaching versus human coaching [S, DOC, T located]

`routers/practice.py:37–182` provides parent-gated read/confirm/plan/approve/discard routes. `services/practice/store.py:18–70` checks student existence and encrypts per-student records; queries bind record/student. `services/practice/extract.py` implements reading route/provider consent and image extraction; consult full provider configuration at later authorization.

`docs/PRACTICE_COACH.md:1–49` describes adult review before learner delivery. “Practice Coach” is a software workflow, **not proof of staffed premium coaching**. Its golden evaluation is described as derived from a real quiz; that fixture was deliberately not opened or executed for this baseline.

No evidence inspected establishes goal-linked coach allocation, qualifications, direct/prep time, scheduling/service window enforcement, case handoff, fade/refer decisions or promised weekly capacity.

### C12 — Privacy, consent and family/campus authorization [S, T located; operationally unverified]

`core/deps.py:46–199,241–265` validates tokens/sessions and role/authorization actions, including family read access and parent gates. `services/pilot_authz.py` contains explicit campus/educator/roster authorization helpers. Curriculum workflow adds live checks noted above.

Practice upload consent is per-provider/per-upload, not blanket permission for curriculum corpus indexing, model training or new deployments. Family routes using `student_name` and per-deployment parent roles require a deployment/tenant-boundary review before claiming pooled-family isolation. Existence checks alone are not tenant authorization; this limited review neither proves an exploit nor certifies isolation.

Keep public demo, family installation and teacher-only synthetic school pilot separate. No real learner or production database was read.

### C13 — Deletion/retention [S, T located]

`services/student_deletion.py:25–110` enumerates student-scoped tables, deletes rows and destroys student keys in the transaction; it intentionally excludes differently keyed demo/security records. It also logs a student identifier with counts: do not broadly claim “no identifiers are logged” from this source.

`services/pilot_learner_deletion.py` implements a distinct pilot learner deletion path. `tests/test_student_deletion.py` and `test_pilot_learner_deletion.py` exist; not run. No curriculum-campus deletion/retention/key-destruction integration or backup restoration test was qualified in this baseline. Documentation's deletion intentions are not live verification.

### C14 — Feature flags, routes and deployment side effects [S, X partial]

`services/curriculum/flag.py:1–12`: `CURRICULUM_ENGINE_ENABLED` defaults false. `persistence.py:102–108`: opt-in DDL only. Static search of `main.py` and `routers/*.py` found no call to curriculum `search_chunks`, `rank_citations` or table creation. Existing application practice/pilot routes are separate; absence of a simple string is not proof against all dynamic wiring.

Code comments/docs call several increments draft or pending review; old PR labels do not establish present upstream merge/release status. Cloudflare can deploy branch pushes. No flags, startup hooks, tables, features, branches or production state were changed. Exact-head CI, authentic independent review and separate release/pilot authorization remain required.

## Reuse recommendation

Feed the forthcoming factory specification with these interfaces and gaps. Do not build a parallel catalog, rights gate, reviewer identity mechanism or retrieval system in curriculum research scripts. JSON in this package is a **research register only**, not a runtime approved source table or ingestion manifest.
