# One Bede install: operator + teacher acceptance

Open `Open-Bede-Teacher-Operator-Acceptance.html` from the approved operator package. It is a **manual evidence form**, not the Bede runtime or a simulation of success.

## Roles and handoff

**Operator (authorized campus administrator):** obtains checksum-verified `arm64` or `amd64` package matching release SHA; launches `Install-Bede.command` on the designated Mac server; uses the private HTTPS/DNS mode only after network authorization; verifies real device/browser passkeys; provisions campus and invites teacher through authenticated server routes; manually grants exactly scoped educator roster access.

**Teacher (invited educator):** opens the same Bede HTTPS application in a supported browser (no Docker installed on workstation), completes passkey enrollment, reviews assigned synthetic learner, separately imports verified official assessment facts and teacher observations, reviews Data Day, approves/edits/rejects source-linked proposal, prepares **teacher-use only** instruction, then records offline/in-person follow-up. No automatic delivery or learner session.

**Operator closure:** revokes an assignment, observes denial with an existing token, invokes confirmed campus stop after #653 is merged and shipped, verifies other campus unaffected, restarts the service and tests recovery. Do not treat a browser-local checkbox as proof that any underlying server action occurred.

## Acceptance evidence

Record approved installer SHA and SHA-256, actual host architecture and OS, Docker/Compose output (redacted), HTTPS origin/certificate trust, passkey success and cancelled challenge, two-campus positive/negative requests, teacher decision IDs and persistence after restart, actual disable result and blocked old tokens, relevant CI runs and synthetic-only recovery.

For this teacher-only prepilot **learner delivery remains disabled**. Do not use real student data. Separate signed engineering evidence acceptance from subsequent founder Pilot GO/HOLD and institution-approved data-processing permission. The HTML review exports a local JSON file with `pilot_go: HOLD`; it never reports automated pass or transmits private data.

### Existing implementation

- `packaging/bundle/Install-Bede.command`, `Verify-Bede.command`, `TWO_MAC_TEACHER_PILOT.md`
- `homeschool-tutor/src/components/PilotTeacherJourney.tsx` and `PilotOfficialAssessmentForm.tsx`
- `homeschool-tutor/src/components/PilotOwnerPanel.tsx` (campus stop requires PR #653)
- `docs/institutional/PILOT_RELEASE_EVIDENCE_CHECKLIST.md`

### Required integration still to validate

The generic installer does not by itself provision campus identity or educator enrollment. These are authenticated operator tasks inside the installed Bede backend. Do not misrepresent a local HTML walkthrough as unified backend provisioning. Validate the actual install-to-invite-to-teacher-to-stop sequence and confirm G3 on a physical Mac before accepting the pilot.
