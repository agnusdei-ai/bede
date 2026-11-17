# Grades 8–12 interactive demo selection

## Scope

Grade 8 retains its existing behavior. Grades 9–12 are selectable interactive
practice sessions, with distinct grade-specific guidance for mathematics,
reading/writing, science, and history. Other existing subjects remain available,
with readiness-led language, logic, art/music, or family-selected faith practice.
These sessions do not establish complete full-year courses, accreditation,
curriculum approval, demonstrated learning gains, or school deployment readiness.

The selected grade is preserved in demo-code personalization, reloaded session
configuration, and Parent Setup. Both English and general Spanish entry screens
include the choices and a short scope note.

## Compatibility and boundaries

- `VALID_DEMO_GRADES` is separate from the existing K–8 `VALID_GRADES`.
- The existing `6-8` stage value remains a session-tool compatibility envelope
  for upper-school demos (including handwriting ruling), not a claim that the
  learner selected Grade 6–8. The exact grade drives upper-school tutor prompts.
- Upper-school subject prompts exclude the K–8 curated catalog, term targets,
  and diagnostic check-in prompts. Parent unit/focus, language, timing,
  transitions, and applicable faith preferences remain available.
- Unsupported high-school mastery previews are hidden in the demo and rejected
  by the diagnostic API guard. Diagnostic evidence recorders reject upper-school
  sessions rather than promoting K–8 evidence.
- Existing Socratic, anti-cheating, privacy, safety, and access protections
  remain. Practice does not activate a curriculum corpus or advance full-year
  production approvals.

## Verification

Performed against upstream base
`33348a35621b235964397579d37d7fe19e4b818b`, in an isolated detached worktree,
without changing the older dirty website/demo checkout.

- 23 frontend tests passed across `UpperSchoolDemo`, `App`, `api`, and locale
  tests. Includes Grade 8–12 choices, session request values, remembered
  selection, and reload in English and Spanish.
- TypeScript `tsc --noEmit` passed.
- Vite production build passed. The existing large-bundle warning remains.
- 83 backend tests passed across upper-school, demo personalization, Parent
  Setup, AI-literacy guardrails, diagnostic router, and diagnostic quota tests.
  Includes persisted grade/config, grade-specific English/Spanish tutor
  instructions, K–8 behavior, and upper-school diagnostic rejection.
- Mobile-width screenshot confirmed the built app renders its existing consent
  screen. Consent was not bypassed for that screenshot; selection/start
  behavior was checked by component and backend tests above.

Tests used sample data and isolated SQLite fixtures, not a production
database or live model requests. Python 3.13 Nix dependencies were supplied
through process-local `PYTHONPATH`; missing WebAuthn, SSE, and PDF parser test
imports were installed as environment dependencies, without changing upstream
application lockfiles. Existing Pydantic/pytest deprecation warnings remain.
This is local verification, not deployed end-to-end or physical-device
certification.

## Release

No GitHub push, PR, merge, production deployment, real-learner session,
curriculum activation, or full-year approval was performed. Release requires
separate owner authorization. Frontend and backend must be released together;
a new selector alone would leave the old backend discarding upper-school grades.
