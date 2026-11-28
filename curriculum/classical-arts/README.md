# Classical literature and arts: source-independent integration

## Current state

**Local implementation draft; not released, reviewed, or learner-ready.**
Project Gutenberg-dependent source verification is queued at the owner's
direction. No alternate edition has been adopted to bypass that wait.
The original prose in `units.py` drafts twelve three-week units (36 distinct
weekly teaching sequences). It is not a completed source-bound curriculum,
Spanish release, factory result, accepted year, or efficacy evaluation.

The demo and enrolled Parent Setup surfaces now have matching adult-directed
workshop components for grades 4–12. Source-backed lessons are unavailable
until their exact release is reviewed. These local changes have not been
pushed, merged, or deployed. The accepted Grade 8 year is unchanged.

## Completed source-independent implementation

- Unit/week/support selection uses the existing adult editable unit-note and
  parent-save flow. Choosing a unit does not silently save it.
- Rehearsal supports unique roles, ordered partner cues, hidden role text,
  reveal/retry, self-read and typed participation. Drafts stay on the page;
  no microphone, recordings, accent/emotion assessment, or new learner-data
  store is added.
- Both English and Spanish interface states are provided. Exact English
  source passages must be labeled as such rather than presented as a verified
  Spanish translation.
- Fetches are selection-scoped, stale requests are invalidated, failures are
  visible, and an adult cannot apply a unit before its current lesson is loaded
  and a corresponding subject is selected.
- Public source-only API routes are declared and added explicitly to the
  existing public-route inventory. They do not access learner records.
- The backend checks the pinned release digest, every declared week, source
  passage digests, exact rehearsal containment, localized instruction, and
  exclusion of private adult fields. No runtime fetching or quote reconstruction
  is possible.
- Tutor preparation recognizes only an explicit, bounded adult unit-note
  format. Nonmatching notes and subjects keep their existing delivery routes.
  The existing session locale is passed through rather than inventing another
  language setting.
- The unverified release fails with HTTP 503 before streaming or a model call;
  the UI explains that source verification is pending.

## Source-release handoff

The release adapter is `homeschool-api/services/classical_arts_service.py`.
Its intentionally empty pinned digest is a closed source-release boundary,
not an assertion that a corpus exists. Do not fill it merely to make the UI
look available.

When Project Gutenberg returns:

1. Verify the actual chosen editions, precise passage locators, asset rights,
   and source bytes. Maintenance pages are not source assets.
2. Finish the original teaching, differentiated support, delayed/transfer
   prompts, source comparisons, and separate private adult models and keys
   through the existing production contract/factory.
3. Complete and separately review every adopted unit/week and localized
   instruction. Reconcile the art/composer plan and actual rotations;
   present reproductions, scores, recordings, and translations as different
   rights decisions. Do not invent playback or first-hand source exposure.
4. Produce the public student projection with exact source text/digests and
   role cues; keep adult keys and original authoring history private where
   required. Pin the reviewed projection in a source-release change.
5. Integrate with current main, including the already-merged Math selector
   update and any reviewed upper-school work. This checkout predates that
   Math merge; do not revert it during integration.
6. Follow the task's review and authorized publication requirements. Learner
   and browser evaluation remain distinct from code compilation.

## Checks performed

Both frontend TypeScript checks and production builds passed with the existing
workspace dependency cache. Python syntax parsing, repository nomenclature,
and whitespace checks passed. These checks establish code/build integrity,
not learner effectiveness or successful end-to-end teaching. No learner,
browser, or automated test suite was run during this source-independent batch.

## Scope

This increment belongs to the existing Shakespeare/classical-arts task.
Do not duplicate Grades 9–12 full-year authoring already running separately,
replace the accepted Grade 8 year, infer Valor affiliation, publish private
keys, or call the 36 draft teaching sequences a complete K–12 literature
curriculum.
