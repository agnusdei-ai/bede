# Black Hat / AIUC-1 Readiness

Executive status for two related but distinct goals: surviving an independent
professional security assessment (penetration test, red team), and passing
AIUC-1 certification. Companion to `docs/SECURITY.md` (the detailed
gap-by-gap log this document summarizes and prioritizes) and
`docs/INCIDENT_RESPONSE.md`. Like those, this is a factual snapshot of where
the code stands — **not a certification, not legal advice, and not a
substitute for the actual third-party engagements both goals ultimately
require.**

## Why these two goals are listed together

They overlap more than they first appear to. A control that exists on paper
but doesn't execute — this pass's headline finding was exactly that — fails
both a pentest and an audit for the same reason: an independent reviewer
finds it in minutes, and it reads as a systemic signal ("what else here is
inert?"), not an isolated bug. **Fixing what's self-findable before anyone
external looks is the correct sequencing for either goal, and it's cheap
compared to what a professional engagement costs per finding.**

Where they diverge: a pentest report is a point-in-time technical
assessment. AIUC-1 certification requires that *plus* an accredited
third-party audit against 130 specific controls across six pillars, quarterly
re-testing, and — for the pillars that are organizational rather than
technical (Accountability's vendor due diligence, SOC 2's policy set) —
artifacts no codebase change can produce by itself.

## Status at a glance

| Pillar | Status | Notes |
|---|---|---|
| Security | 🟡 Improving | Headline control (exfiltration guard) was inert; now fixed and regression-tested. Adversarial-detection/prompt-injection defenses are genuinely strong. Independent red team still outstanding. |
| Accountability | 🟡 Improving | Incident response's top-severity item (`MASTER_SECRET` leak) had no real containment step; now closed. Vendor due diligence is still a disclaimer, not an assessment. |
| Data & Privacy | 🟡 Partial | Deletion is logical, not cryptographic (real gap for the public demo specifically). No AAD binding on encrypted columns. Self-hosted single-tenant risk is inherently lower than the shared demo. |
| Safety | 🟢 Strong | Two-tier moderation, physical-safety guardrails, safeguarding patterns — substantively good. No single enumerated harm-taxonomy document; the controls exist, scattered across five files. |
| Reliability | 🟡 Thin | Tool-call restrictions solid. No systematic factual-accuracy evaluation harness for a K-8 tutor's core claim — highest-risk gap in this pillar. |
| Society | 🟢 Strong | Architecturally grounded scope statement (no code execution, no open web-fetch, closed domain, single-tenant). Holds up under scrutiny. |

🟢 strong · 🟡 partial/improving · 🔴 not started

## Closed this pass (2026-08-02, branch `claude/security-hardening-blackhat-aiuc1`)

Each fix below is independently committed, tested against the real dispatch
path (not just unit-tested in isolation), and documented in
`docs/SECURITY.md`'s "Closed gaps" log with full detail. Summarized here for
the readiness view:

1. **ExfiltrationGuard was inert against any gzip-eligible response.**
   `main.py`'s middleware registration order made `GZipMiddleware`
   compress responses *before* `ExfiltrationGuard` scanned them — every
   `_BLOCKED_PATTERNS` check (leaked `data_key`, `device_salt`, voice
   embeddings) was scanning gzip magic bytes, not the JSON it existed to
   inspect, on any response over 500 bytes from a client sending
   `Accept-Encoding: gzip` (i.e. every browser). This is the archetype of
   "a control that would certify a false sense of security" — a pentest
   or auditor finds it in minutes, and it calls the rest of the layer
   into question. Fixed by correcting the middleware order so GZip is
   genuinely outermost; verified with a reproduction of the original bug
   and a new assembled-stack regression test (the existing per-middleware
   unit tests structurally couldn't have caught an ordering bug, since
   each tests one middleware alone).

2. **`MASTER_SECRET` had no rotation path.** The incident response plan's
   own "Critical" severity item — a leaked `MASTER_SECRET` — had a
   documented non-answer: rotating it destroyed all data, so the plan
   said not to. Added `rotate_master_secret()`, which re-wraps the
   *existing* `DATA_KEY` under a new secret without touching `DATA_KEY`
   itself or anything encrypted under it, plus an operator-facing CLI
   (`scripts/rotate_master_secret.py`). Verified that `DATA_KEY` bytes
   are provably identical before/after rotation and that the old secret
   genuinely stops working afterward — the actual containment property
   this exists for.

3. **`.env.example`'s sample `CHILD_PIN` (`602656`) passes production
   validation.** It's a real, `pin_is_strong()`-passing PIN published in
   this public repo, so a hand-copied `.env` that never touched that line
   boots in production with a PIN anyone can find on GitHub. Rejected
   outright in production now, and the example value itself replaced
   with a non-numeric placeholder so it fails even the basic digit check.

4. **`production-regression.yml`'s license-gate check could fail silently
   for an extended period.** `continue-on-error: true` (a deliberate,
   still-correct choice — an unrelated stale test secret shouldn't block
   Postgres backup/restore coverage) meant the step's failure was easy to
   miss: the job stays green in the PR checks list, and finding out
   requires opening that specific step's log. Now emits a loud `::error::`
   annotation and a `$GITHUB_STEP_SUMMARY` banner at the point of
   failure, plus a final always-run step that re-surfaces the same signal
   as the last thing in the job summary.

**Verification:** full backend test suite (1,343 tests) passing, plus
targeted reruns of every touched area against the real dispatch path (not
mocked). The only 2 failures across the entire suite are a pre-existing
missing optional `soundfile` import in the verification sandbox, unrelated
to any change in this pass.

## Outstanding — prioritized

Carried forward from the original review, ranked the same way: does leaving
this open let a pentest or audit certify a false sense of security, or is it
a real but bounded gap.

| # | Item | Pillar | Why it matters |
|---|---|---|---|
| 5 | No AAD (associated data) binding on encrypted columns | Data & Privacy | `core/encryption.py`'s AES-GCM calls carry no AAD, so ciphertext is portable across rows/columns/tables — anyone with DB write access can swap `bookmark_enc` between subjects undetected. Needs a version bump and a migration/read-path fallback for existing rows, so it's a larger change than the four closed above, not a same-day fix. |
| 6 | Deletion is logical, not cryptographic | Data & Privacy | `student_deletion.py` issues real SQL `DELETE`s, but Postgres retains dead tuples until VACUUM, in WAL, and in `make db-backup` dumps — all still decryptable under the still-live global `DATA_KEY`. Fine in substance for a self-hosted family instance; a real gap against `README.md`'s "permanently delete" claim for the shared public demo, which holds strangers' children's data. Crypto-shredding (per-student record keys, destroy-the-key-not-the-row) is the fix and is a natural addition given `student_name`-scoped tables already. |
| 7 | Child PIN has no lockout | Security | Only defense is the per-IP `auth` rate bucket (10/min), keyed on IP alone — trivially defeated on a LAN or with IPv6. Parent role already has DB-backed lockout (`core/parent_lockout.py`); child role guards the same student data with none. Should reuse that existing pattern. |
| 8 | Voice verification is advisory only; enrollment-method mismatch unhandled | Security / Reliability | No server-side code consumes `verify_student`'s result — enforcement is client-side only, which `README.md`'s "voice biometrics authenticate children" overstates. Separately, `enroll_student` records which extractor (`resemblyzer` vs. MFCC fallback) was used and `verify_student` never checks it; mismatched extractors compare incompatible feature spaces, and MFCC-vs-MFCC across different speakers can exceed both confidence thresholds. |
| 9 | No enumerated harm taxonomy | Safety | The controls are real and effective (safeguarding patterns, moderation categories, physical-safety guardrails, the constitution) but scattered across five files rather than existing as one document mapping harm → control → test. Certification will want this as a single artifact — a writing task, not an engineering one. |
| 10 | No factual-accuracy evaluation harness | Reliability | One excellent worked example exists (the Scripture-translation-copyright fix), but nothing systematic measures factual accuracy across K-8 subjects generally — the core claim of a tutoring product. Likely the hardest place an assessor pushes. |
| 11 | Vendor due diligence is a disclaimer, not an assessment | Accountability | `docs/VENDOR_DATA_FLOW.md` accurately documents what data flows where, then tells the reader to review each vendor's terms themselves. AIUC-1's due-diligence control wants an actual assessment (retention, training-use, subprocessors, DPA) recorded per vendor, not a pointer. |
| 12 | Independent adversarial testing | Security / Safety | `scripts/adversarial_probe.py` and `docs/adversarial-probes/` are real, reusable, git-SHA-pinned tooling — but self-run. AIUC-1's control language specifically calls for a **third-party** red team; this tooling is what that engagement tests against, not a substitute for it. |
| 13 | Environment/infrastructure pentest | Security | `docs/environment-pentests/README.md` is a tracker with no entries yet — network exposure, auth/session binding, TLS config, container hardening as actually deployed has not been independently verified, only reasoned about from the code. |
| 14 | SOC 2 policy set | Accountability | `docs/SECURITY.md` already states this plainly: Information Security, Access Control, Change Management, Vendor Management, and Risk Assessment policies remain undocumented, and none of them can be satisfied by a codebase change. |

## Path to each goal

**Black Hat / independent pentest ready:**
1. Close #5–#8 above (all code-level, all bounded).
2. Run the environment pentest (#13) — this is likely the actual first
   external engagement, since it tests the deployed reality rather than
   the code's account of itself.
3. Commission the independent red team (#12) once #5–#8 are closed, so it
   isn't spent re-finding what a code review already caught.

**AIUC-1 certification ready:**
1. Everything in the pentest path above, plus:
2. Write the harm taxonomy (#9) and stand up the factual-accuracy harness
   (#10) — both are pure documentation/tooling work, no architecture
   change required.
3. Do the real vendor due-diligence assessment (#11) — per-provider,
   recorded as an artifact, not a disclaimer.
4. Only then engage AIUC for the formal audit. Quarterly re-testing is a
   standing commitment once certified, not a one-time gate — the tooling
   built for #12 is what makes that sustainable rather than a fire drill
   each quarter.
5. SOC 2 (#14), if pursued, is a separate track requiring an accredited
   CPA firm and 6–12 months of observed control operation — not
   something this readiness plan accelerates.

## What this document is not

Not a certification, not a guarantee either engagement passes cleanly, and
not a replacement for `docs/SECURITY.md`'s per-fix detail or
`docs/INCIDENT_RESPONSE.md`'s operational procedures. It exists to answer
one question honestly: what's actually closed, what's actually open, and in
what order closing the rest is worth the most.
