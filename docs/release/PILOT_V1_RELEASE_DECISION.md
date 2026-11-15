# Bede v1.0 pilot release decision packet

**Decision: HOLD.** This packet names the candidate, what was checked and
what still blocks a release. It does not approve anything. Scope is frozen
to the existing pilot agreement
([VALOR_TEACHER_REVIEW_CONTRACT](../institutional/VALOR_TEACHER_REVIEW_CONTRACT.md))
and release contract
([PILOT_RELEASE_EVIDENCE_CHECKLIST](../institutional/PILOT_RELEASE_EVIDENCE_CHECKLIST.md)).

```yaml
release:
  name: Bede
  version: "1.0"
  target: pilot
candidate:
  source_sha: the merge commit of the pull request that adds this file (base d7c99b1f)
  content_revision: pilot-content/2026-11-15
  package_digest: none; no operator package has been built from this candidate
gates:
  required_content: reviewed, with open sign-offs (see below)
  teacher_journey: passes in automated checks; not run on the pilot Mac
  automated_qualification: not met on this candidate
  required_mac_verification: not run
  independent_review: not done
blockers: listed below
decision:
  status: HOLD
  owner_approval_ref: none
```

## Gates

**Required content.** Every required item is inventoried in
[PILOT_CONTENT_INVENTORY](PILOT_CONTENT_INVENTORY.md). Seven wording and
print findings were fixed in content revision `pilot-content/2026-11-15`.
All required items are `accepted` on an automated review. No educator has
read the wording, so this gate is not signed off.

**Teacher journey.** Evidence, suggestion, approve / edit / reject, the
approved plan, its print, and the same state on reopening are covered by:

- `homeschool-api/tests/test_valor_pilot_g2_journey.py` and
  `test_valor_release_journeys.py` (suggestion journey, ledger, denial cases)
- `homeschool-api/tests/test_canonical_assessment_api.py` (official record
  to proposal, decision, plan, over real HTTP)
- `homeschool-tutor/src/components/PilotTeacherJourney.test.tsx` (a decision
  already on the server is shown on open, with its print; no print before
  approval; no delivery claim)
- a print to PDF in headless Chromium: one sheet, plan only, nothing clipped

Delivery stays `NOT_REQUESTED` throughout. Not yet done: the same journey by
hand on the pilot Mac (G3-04, G3-05).

**Automated qualification.** Sample qualification last passed on
`d6d8bbf3` (run 247), which is not this candidate. It has to pass on the
candidate SHA. The cross-platform browser journeys were still failing on
their latest run (run 35, `d6d8bbf3`); see the WebKit blocker.

**Required Mac verification.** Every row of
[MAC_G3_CERTIFICATION_RECORD](../institutional/MAC_G3_CERTIFICATION_RECORD.md)
is NOT RUN.

**Independent review.** None recorded.

## Blockers

1. **Physical Mac acceptance (G3-01 to G3-11) is not run.** Needs the pilot
   Mac, a built operator package with its digest, and a real passkey.
2. **The release checklist's evidence record is empty.** The mandatory
   order (backup and restore, WebAuthn, isolation, installer) has no dated
   row with a SHA and result.
3. **WebKit page crash on reload after an API restart, macOS runner.** With
   its current owner. No terminal result has come back. Last known state:
   it fails on `main` and on every macOS run since run 20; the crash report
   points at `WebCore::Navigation::initializeForNewWindow`; the service
   worker is ruled out; it has not been tried in real Safari. A finished
   content review does not change this: the required browser check is
   failing, so it counts as failing. The owner of that work is asked for
   one of: reproduced (with variant, environment and stack comparison), not
   reproduced under the tested variants, or blocked on a named prerequisite.
4. **Sample qualification has not run on this candidate SHA.**
5. **No educator has read the teacher-facing wording.**
6. **Print from Safari on the pilot Mac is not checked.**
7. **Counsel has not reviewed the school data notice.** This blocks real
   learner data, not a sample-data pilot.
8. **Two scope decisions for the owner:** whether Teacher Quiz Studio and
   model-drafted quizzes are in the pilot. Both are on the teacher desk and
   neither is named in the pilot agreement. Drafted quizzes cannot be
   accepted as content without an educator reading drafts from the pilot's
   own local model.
9. **No operator package, so no package digest.**

## Not reopened

#834 (ending a lesson turn when the chat screen goes away) is merged and
its regression tests are kept. Nothing here changes it.

## What would move this to a decision

Build the operator package from the candidate SHA and record its digest;
run sample qualification on that SHA; run the G3 rows on the pilot Mac
including the teacher journey and a Safari print; get the WebKit result;
record the educator and counsel reviews; then the owner records GO or HOLD
with a dated reference in `owner_approval_ref`.
