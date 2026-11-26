# Grade 8 student-facing curriculum review

**Review drafts, not an approved or activated curriculum.**

This pull request shares the student-facing projection of 252 weekly focus
drafts: 36 weeks in each of seven strands. It does not claim to finish Grade 8
or to release these materials to the demo or enrolled tutor.

## Open a strand

| Strand | Student-facing drafts |
|---|---|
| Mathematics | [36 weeks](mathematics.md) |
| Science | [36 weeks](science.md) |
| Literature and composition | [36 weeks](literature.md) |
| History and geography | [36 weeks](history.md) |
| Introductory Spanish | [36 weeks](spanish.md) |
| Computing and research | [36 weeks](computing.md) |
| Wider learning: arts, nature and practical work | [36 weeks](wider_learning.md) |

Each document includes learning focus, prerequisite checks, original teaching
explanations, student activities, guided/independent/delayed/transfer prompts,
access supports, safety notes and attribution where present in the verified
draft. Literature includes 36 original short transfer-reading passages.

These are student-format **review copies**, not self-contained independent
courses. Worked models are intentionally withheld; an adult must teach those
from the separate private material before assigning practice. Later checks
must be withheld until appropriate.

## What is deliberately absent

Adult worked models, answer keys, scoring rubrics, assessor records, private
authoring code, teacher packets and the private commit history are excluded.
The public branch starts from the production repository's main branch, not
from the private authoring commit.

The projection uses an explicit field allowlist, checks each input packet's
hash against its factory evidence and verifies that changing private fields
does not change the public projection. A further scan excludes private solution
text of at least 32 characters; short numbers alone cannot reliably identify a
leak because they also occur in unrelated lesson text. These checks are useful
evidence, not a guarantee that no student could infer an answer from a lesson.

The [manifest](manifest.json) identifies each lesson, the exact published
document hashes and the private input-bundle hashes without publishing the
private inputs. It does not contain solution text.

## Current limits and substantive review requests

- These are weekly focus drafts, not complete daily instruction or a complete
  practice/assessment bank. Expanded practice and quarter assessments remain.
- Historical primary-source documents/maps and complete lawful novel editions
  are not supplied by a title or reading reference.
- Literature selections need reconciliation with the existing
  Shakespeare/Everyman/Plutarch pathways. No replacement decision is implied.
- Artist/composer plans need reconciliation with actual delivered selections.
  Arts, music, movement and oral Spanish need reviewed performance routes;
  written activities alone do not establish performance or proficiency.
- The public student projection cannot establish whether the withheld adult
  keys are correct. Full academic review still requires authorized private
  access to those materials.
- Relevant rights, accessibility, safety and practical-delivery issues still
  need disposition. No pilot results, efficacy, accreditation, credit,
  standards certification or full-year academic approval are claimed.

Review comments should identify the strand, week, lesson identifier and exact
passage, then state **accept**, **revise** or **reject** with a reason. Do not
post private keys or real learner information in public comments. Public
comments are not authenticated institutional approval or permission to
activate content.

## Verification and publication boundary

The private draft work previously passed15 local checks and252 factory builds.
Those checks concern structure, references, deterministic builds and related
local invariants; they do not certify a complete educational year.

This owner-authorized publication is limited to a student-only repository
review. It does not change the app, catalog selectors, retrieval corpus,
runtime flags, billing, onboarding or either deployed product. There are no
new runtime imports or activation instructions.

Copyright2026 Agnus Dei Technologies, LLC. All Rights Reserved.
Original Bede curriculum remains proprietary. Public review availability is
not a grant to redistribute, adapt, train models on, or commercially reuse it.
Third-party works retain their own rights.
