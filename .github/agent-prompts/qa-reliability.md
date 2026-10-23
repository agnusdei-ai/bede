# Bede QA Reliability — permanent repository instructions

Read docs/engineering/QA_RELIABILITY.md and scripts/qa/ before any PR.
Use U.S. English and simple product copy.

1. For each PR, calculate the correct git merge-base and generate a
   deterministic affected-test plan. Trace imports, consumers, contracts
   and security/persistence boundaries. Fail closed on unmapped paths.
2. Run static/dependency checks, affected unit tests and relevant synthetic
   positive/negative/recovery/authorization tests locally when possible.
   Never replace G1's non-superuser PostgreSQL check with a mock.
3. If failing, retain original log and SHA, identify root cause, reproduce
   narrowly, repair underlying code or outdated deterministic test, add a
   regression test, and verify affected contracts. At most two repair
   iterations per invocation; escalate with diagnosis if unresolved.
4. Never disable security, privacy, license, audit checks or reduce assertions,
   nor classify missing evidence as passing. No identifiable learner data
   or production credentials in synthetic tests.
5. Reuse existing dependency-remediation and demo-watchdog agents; do not
   create a competing scheduler, runner or CI framework.
6. Record source-keyed QA evidence, changed files, selected tests, diagnoses,
   attempted repairs, skipped-test explanations, test duration and
   applicable external gates. Never invent CI billed-minute savings.
7. Merge only when exact-head required CI, independent reviews, high-severity
   security screening, scope mapping and branch protections pass. The
   repository's opt-in event-driven merge policy and separate human
   Pilot GO authority remain unchanged.
