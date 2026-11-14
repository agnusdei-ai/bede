# Bede institutional educator journey — design-to-code release contract

Status: approved implementation target; not evidence of completed runtime. This design belongs to the institutional workstream and does not change Bede's family/demo authority model.

## Non-negotiable decisions
- Passwordless adult educator authentication using WebAuthn passkeys with user verification required (UV). Support browser-compatible macOS, Windows Hello, Linux with roaming/cross-device authenticator or compatible passkey provider, and mobile.
- Device PIN/biometric stays inside the authenticator or OS. Bede never requests/stores it and never overrides device lockouts. A canceled native passkey prompt is retryable and not an account authentication failure.
- School-affiliated email invites, notifies, and initiates supervised recovery only. No email-only sessions, password fallbacks, SMS/TOTP downgrade, or administrator impersonation.
- Teacher sees only expressly assigned learners. Campus authorization is verified on every server request and before model invocation. No implicit permission from campus membership or email domain.
- Educational evidence is dated, sourced, contextual and explicitly distinguishes independent work from assisted work. No learner rankings, character scores, fake benchmark precision or causal learning-efficacy claims.
- One to five owner-only mock live usability sessions constitute the usability acceptance gate; outside participants are optional. Institutional/customer pilots are separately contracted engagements and never required to release a software build.
- Campus commercial offer is defined in VALOR_PRICING.md. Do not include pricing in credential or classroom API contracts.

## Journey 1: campus invites teacher
Actor: independently authenticated campus administrator with explicit tenant authority.
1. Admin selects campus and enters authorized school email; server validates campus administration and unique educator invitation.
2. Invitation transaction stores only scoped educator/campus identity, hashed single-use token, bounded expiration, requested role, audited inviter, and contact verification status. No student roster is attached to unactivated invitation.
3. Email link opens same-origin HTTPS Bede enrollment, showing recognizable campus name and unambiguous passkey CTA. Email-link verification sets *invitation verified*, not *authenticated*.
4. Browser feature-detects WebAuthn; primary button registers discoverable credential with required UV. Offer another device/security key; don't assume availability of built-in Linux authenticator.
5. Server verifies credential registration against challenge, RP ID/origin, invitation, account and UV; stores public key and metadata and atomically consumes challenge. Only after persistence may UI say 'Passkey enrolled'.
6. Encourage second independent authenticator, then require fresh assertion to enter educator desk. Audit completion.
Alternative states: invitation expired/consumed, wrong campus, wrong origin, duplicate account, unsupported browser, user cancellation, missing UV, server unavailable, compromised invitation. All fail closed with actionable text and no learner data.

## Journey 2: returning teacher
1. Landing chooses 'Continue with passkey', no password field.
2. Server issues short-lived anti-replay WebAuthn challenge with RP ID and rate limits; allow discoverable credentials or account hint without enumeration.
3. Browser obtains assertion from available provider (macOS, Windows Hello, Linux-compatible FIDO2, mobile/cross-device).
4. Server checks challenge once, type, signature, UV, RP ID, origin, credential owner/revocation, tenant affiliation and enabled account; verifies any sign-count anomaly according to authenticator semantics.
5. Issue short-lived, scoped session and enforce live version/roster checks on every operation. Privileged operations require fresh passkey step-up.
Alternative: canceled prompt => retry; missing credential => alternate authenticator; school departure => denied; revoked credential => denied.

## Journey 3: teacher desk, lessons and evidence
1. Select assigned campus/pod (no implicit switching across campuses).
2. Load only server-authorized learner roster and approved lesson resources; do not trust learner ID or settings provided by browser.
3. Review source-grounded draft questions, edit and approve before assignment. 'AI draft' is labeled until teacher approval; don't allow background publication.
4. Open student lesson with approved SessionConfig reloaded server-side; verify roster + campus at model boundary.
5. Review dated work evidence with assistance and source. Show incomplete or insufficient evidence without sample scores.
6. Export or share only with role-authorized educational contacts under institutional consent/data policy; log access and purpose.
Alternative: unauthorized learner => indistinguishable 404; weak evidence => explicit 'not enough evidence'; inference offline => non-destructive failure and retry.

## Journey 4: lost passkey and school recovery
1. Existing backup passkey => fresh verified assertion permits registering replacement; invalidated lost credential.
2. All authenticators lost => teacher contacts school using affiliated email; email confirmation *requests* recovery but never issues session or replaces key.
3. Independently authenticated campus admin verifies active affiliation out-of-band; approval must be bound to requested account and cannot be self-approved. Issue short-lived, one-use recovery enrollment with narrow rights, only after approval.
4. Educator registers new UV-verified passkey. Server rotates credential/session version, revokes lost authenticator(s), audits actor and approval; sends notifications to school security and verified address.
5. Never unlock child data until new educator login through verified assertion.
Alternative: stolen email, unapproved admin, expired link, already-used link, out-of-campus actor => denied and audited.

## Minimal API contracts (proposed; endpoint names are design targets)
- POST /educators/invitations (campus-admin step-up) -> nonsecret invitation identifier and pending state.
- POST /auth/educator/passkeys/registration/options (verified invitation or eligible fresh step-up) -> RP-bound public challenge.
- POST /auth/educator/passkeys/registration/verify -> server-verified persisted credential, never token on failure.
- POST /auth/educator/passkeys/login/options -> anti-enumeration public challenge.
- POST /auth/educator/passkeys/login/verify -> scoped educator session only after verified signature/UV.
- GET /educators/me/credentials and POST /educators/me/credentials/{id}/revoke (step-up).
- POST /educators/recovery/request (generic response, throttled), POST /educators/recovery/approve (independent campus-admin step-up), POST /educators/recovery/complete (restricted verified ceremony).
- GET /educators/me/roster and GET /educators/me/learners/{id}/evidence (every request checks tenant and assignment).

Each route needs explicit pydantic validation, authorization, anti-CSRF/origin protections where applicable, audit metadata with no credential secrets, transactional token consumption, and a documented error/status contract. Existing password+TOTP routes in #553 must be retired/disabled before production passwordless launch.

## Implementation lanes, no collision
A / identity security: exclusively homeschool-api/core/educator_webauthn*, authentication endpoints and migrations. Never change frontend outside a reviewed contract PR.
B / educator UI: exclusively homeschool-tutor/src/institutional/ and scoped login/enrollment wiring. Follow real backend contracts; no fake success.
C / school recovery: dedicated service and endpoints; only campus admin with strong separate credentials. Coordinate shared migrations with A.
D / evidence/lessons: teacher workspace backend evidence contracts, assignment enforcement, approved content and UI after contract freeze.
E / integration owner: sole owner of App.tsx, core/deps.py, main.py, shared schemas and CI gates. Serial integration order A -> C -> B -> D; no parallel edits to these files.

## Test matrix and gates
- Unit: challenges single-use, expired/replayed/changed, malformed CBOR, wrong RP/origin, signature and UV, revoked keys and wrong tenant, sign counter/backup metadata.
- API integration: invite -> register -> assert -> scoped roster -> lesson -> evidence -> logout; independent admin approved recovery -> new key -> old key revoked; offboarding revocation.
- Negative authorization: all educator routes tested against parent/child/demo/recovery tokens and unassigned students; no widening of parent privileges or leaking learner existence.
- Browser E2E: Safari/macOS, Windows Chromium/Hello, Linux Chromium with FIDO2 or cross-device and one mobile profile. Test feature unavailable and cancellation without lockout.
- Accessibility/usability: keyboard and screen reader labels, clear state and progress, reversible navigation, no ambiguous success; owner runs 1-5 sample sessions and signs off with scenario, platform, outcome and friction.
- Quality: full backend/frontend tests and typecheck/build, CodeQL offline SARIF gate, dependency audits, real hardware qualification and rollback. A successful unit test or storyboard does not certify throughput, hardware or institution deployment.
- Gate verdict is binary: all relevant checks on current integrated commit green AND owner usability approval AND no unresolved critical security issue, otherwise blocked.

## Mathematics lifecycle: every skill, and one representative skill per grade (K-8)

`homeschool-api/tests/test_valor_pilot_g2_journey.py::test_math_lifecycle_per_grade`
is one implementation run over nine rows of scenario data. Each row goes
through the whole lifecycle on the real pilot routes:

campus-scoped educator access, then a prerequisite gap and a hinted attempt,
then a teacher approval, then an approved local-model tutoring turn, then an
independent attempt, then the encrypted outcome read back, then an
authorized educator view, then learner deletion and a refused resumption.

| Grade | Band | Skill | Prerequisite gap |
| --- | --- | --- | --- |
| K | K-2 | `cc.count_objects_20` | `cc.rote_count_20` |
| 1 | K-2 | `cc.number_bonds` | `cc.count_objects_20` |
| 2 | K-2 | `nbt.add_within_100` | `nbt.place_value_tens` |
| 3 | 3-5 | `oa.order_of_operations` | `oa.multiplication_facts` |
| 4 | 3-5 | `fr.mixed_numbers` | `fr.add_subtract_fractions` |
| 5 | 3-5 | `fr.divide_fractions` | `fr.multiply_fractions` |
| 6 | 6-8 | `ns.absolute_value` | `ns.integers` |
| 7 | 6-8 | `ee.variables_both_sides` | `ee.multi_step_equations` |
| 8 | 6-8 | `ee.systems_of_equations` | `fn.linear_functions` |

Each skill is one that grade's own year plan teaches, has a one-to-one
probe, and its prerequisite is a real edge in the skill map. The test checks
all three for every row.

A grade changes behaviour in only one place. `grade_to_stage()` maps it to
a band, and the band sets the cold-start seeds and the on-band probe filter.
The pilot tutor, recommender and deletion paths read no learner grade. Each
row therefore also checks the stored seeds of two unprobed skills, which is
the only stored state a grade can move.
`homeschool-api/tests/diagnostic/test_grade_band_boundaries.py` pins the
2-to-3 and 5-to-6 boundaries.

`test_math_lifecycle_every_skill` runs the same lifecycle for every skill in
`services/diagnostic/skill_map.py`: 95 skills, 24 in K-2, 28 in 3-5 and 43
in 6-8. Its rows are generated from the skill map, so a skill added to the
map is covered when it lands. Each skill runs at a grade inside its own
band, rotating through that band's grades, so every grade K-8 is exercised.
The gap is the skill's first direct prerequisite. The two root skills,
`cc.rote_count_20` and `geo.identify_shapes`, have no prerequisite, so each
is its own gap. `test_every_math_skill_row_covers_the_whole_map_and_every_grade`
fails if a skill is missing from the rows, if a grade K-8 is not reached, or
if a skill is run at a grade outside its band. When the skill under test is
one of the two seed sentinels, the row reads an alternate untouched skill
instead.

Limits, stated with the result:

- The tutor's reply comes from a deterministic stub of the local model.
  These are model-stub integration results; no real provider was called.
- "Later" means a later-dated record. No real time passes, so this is not
  evidence of retention over time.
- Hinted and independent attempts are sample observations; no model
  grades a learner's answer.
- Each skill is checked through its first prerequisite only. Skills with
  several prerequisites are not checked against each one.
- This verifies the software path for each skill. It says nothing about
  whether a learner reaches mastery, which needs real learners over time.

The supported claim is: every mathematics skill lifecycle verified in
software, K-8, with one representative lifecycle per grade. It is not a claim
of complete curriculum coverage, a full diagnosis of prerequisite gaps, or
demonstrated learning gains.

## Immediately actionable implementation sequence
1. Merge safe isolated docs/policy and visual prototypes only after current checks pass; keep new auth inaccessible.
2. Implement persistent invitation/challenge/credential tables and atomic consumption. Include encrypted contact where appropriate, unique binding, migration/backward compatibility and audit.
3. Implement real WebAuthn ceremonies, credential revocation and session-liveness checks; negative/replay tests first.
4. Implement independently authenticated campus-admin recovery and no-mailbox-only replacement; test lost-device, offboard and theft scenarios.
5. Connect real frontend states, teacher roster/lesson/evidence screens and failure handling; replace legacy educator password form and ensure no downgrade.
6. Run E2E browser/security checks, then owner-only usability sign-off; merge sequentially and release only supported scope.
