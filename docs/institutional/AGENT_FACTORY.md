# Bede institutional agent factory — bounded execution design

This is a work allocation and merge policy, NOT evidence that autonomous agents have been deployed or scheduled.

| Lane | Agent | Branch prefix | Owned surface | No-touch areas |
| --- | --- | --- | --- | --- |
| Teacher AI | Scholastica | feat/valor-teacher- | institutional teacher routes and UI under isolated modules | constitution, shared auth and reporting schema |
| Evidence | Benedict | feat/valor-report- | institutional reporting adapters, evidence services and presentation | tutor prompts, shared auth |
| Campus onboarding | Isidore | feat/valor-deploy- | onboarding scripts, appliance profiles, docs and diagnostic tooling | learner model, shared auth |
| Pilot validation | Anselm | test/valor-pilot- | pilot fixtures, performance, privacy and contract tests | production runtime, unless separately reviewed |
| Integration/security | Aquinas | feat/valor-contract- | canonical schemas, authorization registry, migration coordination, release gate | neither bypass security review nor auto-merge |

## Collision prevention
1. One branch per task and one declared write-owner per path; shared surfaces are owned by Aquinas.
2. Each PR lists touched paths, schema/API changes, migration and security effects.
3. Never cherry-pick speculative agent output directly into main. Only reviewed PRs from main-based branches.
4. Create contract-first mocks and fixtures to parallelize backend and frontend development without shared file editing.
5. Rebase after contract merge and before final integration; verify commit ancestry.
6. Run focused tests on each PR, then one integrated security+performance gate on candidate releases. No redundant full qualification on every small PR.
7. Changes touching authorization, child data protection, constitution or assessment claims need explicit independent review. Constitutional change control is separate and never overridden by agent instructions.
8. No background agent execution exists until a real runner, credentials, bounded permissions and scheduling are set up.

## Iteration gates
- Loop A: current-state inventory, contracts, threat review and fixture generation
- Loop B: thin vertical slice for educator view of assigned pod and approved lesson draft
- Loop C: append-only learning events, evidence review and teacher override
- Loop D: reports, CSV/PDF export with scoped redaction, and supervised onboarding
- Loop E: pilot load qualification, failure recovery, user acceptance and go/no-go record

Each loop requires passing tests and evidence before advancing. Never represent a planned feature as complete.

## Agent task contract
Input: issue ID, main SHA, explicit paths, API version, fixture set, acceptance tests.
Output: isolated branch/PR, implementation summary, tests and logs, privacy/security delta, migration notes and known limitations.
Abort on: unexpected shared-file modification, unknown auth path, cross-campus access, data export leak, unreviewed constitution changes, or broken required gates.
