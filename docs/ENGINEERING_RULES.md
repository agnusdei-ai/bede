# Engineering Rules v1.0 — Bede

Status: proposed repository engineering contract; changes to branch protection or CI are separate implementation work.

## Purpose
Optimize for correct, maintainable, secure code with the fewest useful checks. Automate routine engineering; preserve explicit owner and school-administrator Pilot GO authorization and synthetic-only HOLD.

1. **Dependency-aware PRs.** Declare stacked PR dependencies and review only the incremental changes against their parent. Merge parent before child, revalidate the final integrated head, and never merge a draft without meeting its acceptance criteria.
2. **One dependency resolution.** Coordinate changes to the same lockfiles and dependency manifests. Resolve to a single compatible set on current main, retain hashes, and run one applicable dependency/security audit on the final resolution.
3. **Detect overlap early.** Identify shared files, symbols, APIs, tests, data models, and behavior among open PRs. Reuse existing components; remove duplicate logic and tests. Shared filenames are a signal to inspect, not automatic blockers.
4. **Failure-directed repair.** Diagnose failed jobs from logs, repair root causes, and rerun affected jobs/tests first. Do not rerun a passing full suite merely to repeat unchanged evidence.
5. **Affected-code QA by default.** Run relevant unit, contract, integration, lint, type, and security checks selected by changed behavior and dependency impact. Expand coverage for unclassified changes or changed shared boundaries. Require one green, complete set of applicable checks at the final exact head before merge.
6. **Draft means incomplete.** Draft PRs can build and test but cannot merge until declared implementation and acceptance requirements are met. Documentation and manual checklists do not substitute for executable functional evidence.
7. **Review according to risk.** Ordinary reversible changes use automated checks and can merge without redundant manual approval when repository protections permit. Authentication, passkeys, consent, learner data, tenant/campus isolation, and authorization changes require focused independent review of the affected trust boundary. Never bypass existing protections. Curriculum intelligence PRs under epic #685 are an explicit exception to the ordinary-change rule: every curriculum PR requires a human review, its documented exit gate, and green applicable exact-head CI; never auto-merge those PRs.
8. **One integration validation.** After resolving dependent or overlapping PRs, validate the combined behavior once on the integrated commit. Reuse prior unchanged evidence; do not count PR-local green CI as integrated proof.
9. **Merge is not release.** Passing CI or merging code does not qualify a native installer, authorize production deployment, permit real learner data, or lift Pilot HOLD. Verify platform-specific artifact provenance, installation, security, and physical-device acceptance independently. Pilot GO requires separate owner and school-administrator authorization.
10. **Small, current changes.** Prefer narrow PRs; synchronize with main only when necessary for conflicts, security, or integration. Close superseded PRs only after verifying their work is incorporated or intentionally abandoned, with traceable rationale.

## Curriculum and release governance boundaries
- Epic #685 permits curriculum development behind `CURRICULUM_ENGINE_ENABLED` (default OFF), but requires a human-reviewed promotion path and **human review of each curriculum PR before merge**. A passing CI run or routine-change review policy never overrides its exit gates or no-auto-merge rule.
- Issue #709 was closed NOT PLANNED at the owner's direction. Do not reopen it or require additional branch-protection/required-status-check ruleset configuration to merge otherwise qualified PRs. Continue to run and inspect the existing security, provenance, dependency, and regression checks without bypassing failures.
- Pilot GO, real learner-data approval, and physical Mac acceptance are separate from PR merge readiness and remain on HOLD until evidenced and authorized.

## Operational merge checklist (minimal)
- Functional intent and edge cases inspected; no duplicate or conflicting implementation.
- Relevant security/data boundary reviewed at appropriate risk.
- Required affected-code checks green at exact head; unresolved failures addressed.
- Dependency and cross-PR overlap reconciled; integrated tests green when applicable.
- Required independent review complete; branch protections honored.
- Release HOLD and authorization state unchanged unless separately approved.

## Initial application to open PR queue (2026-10-31)
- #752 -> #760: stacked consent authorization; preserve parent-first review.
- #757, #753, #759: coordinate dependency lockfiles and validate one resolved state.
- #750, #752: inspect shared chat/setup behavior; #750 had a failed workflow.
- #758: repair security-patch workflow failure and validate branch lease safety.
- #748: retain focused AEO contract test mapping.
- #742, #741, #735, #734: check functionality, security boundaries, platform-specific requirements, and draft readiness independently.

Do not weaken required CI, security controls, or release authorization to improve throughput. Changes to workflow/branch protection require separate tested implementation.
