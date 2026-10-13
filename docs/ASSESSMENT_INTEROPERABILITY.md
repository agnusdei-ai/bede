# Assessment interoperability for classical instruction

**First implementation:** educator-entered evidence alongside Bede's existing
Diagnostic area. This is not a new assessment engine, a DIBELS implementation,
or proof of standardized-test interoperability with vendor systems.

## Parent workflow

1. Sign in as **parent** and open **Pod Dashboard → Progress**.
2. Choose the appropriate student. Locate **Educator assessment records** under
   Bede's own mastery diagnostic.
3. Select **DIBELS 8th Edition**, **Classical observation**, or **Other external
   assessment**. Enter the date, measure, and where the result came from.
4. For DIBELS 8, choose the **grade and assessment window stated by the report**.
   Bede displays the expected **measure-specific unit** (oral reading
   accuracy is a percentage, oral reading words correct is per minute, and
   composites and Maze are reported as points). Enter the score **exactly
   as independently reported**, not a score calculated by Bede. For other
   external assessments, choose the unit shown in the source report.
   Record a DIBELS risk category only when the original report supplies it.
5. For classical observations, record how a task was completed:
   independently, with a hint, or with help. Never score virtue or character.
6. Review the source-labeled records in the same card. The parent may remove
   an incorrect record and enter a corrected one. Deleting the student
   removes these records and destroys the per-student encryption key.

The existing Bede Diagnostic mastery profile, work ledger, and adaptive
math recommendation history remain unchanged. Entered external results are
NOT fed into mastery posteriors, lesson-selection weights, tutor prompts,
screening flags, rankings, or child-facing performance labels. They are
stored and shown as educator-entered, *not independently verified by Bede*.

## DIBELS 8th Edition: external administration only

Bede supports **manual recordkeeping for external assessment results**,
not test administration, automatic scoring, or benchmark calculation.

Recognized DIBELS result labels: LNF, PSF, NWF-CLS, NWF-WRC, WRF, ORF
words correct, ORF accuracy, Maze, and the educator-provided composite.
For **new** DIBELS entries, Bede now requires reported grade (K–8) and
assessment window (beginning, middle, end of year, or progress monitoring).
The measure-specific unit is taken from the validated backend framework
catalog rather than a user-selectable unit list. The four official
instructional-support categories are Core/Negligible Risk (blue),
Core/Minimal Risk (green), Strategic/Some Risk (yellow), and
Intensive/At Risk (red). Parents may also choose "not reported."
These are educator-entered labels, not classifications calculated by Bede.

Existing encrypted entries from the earlier release remain readable.
Records missing the grade/window or containing older generic labels
or unit inconsistencies are **flagged for source review**, not silently
rewritten, deleted, or substituted with guessed values. Correct them by
reviewing the original report, removing the old record and re-entering
a verified result. Never infer a grade, date, period or benchmark band.

The app does not decide which measures apply to a grade or testing
window; a trained assessor follows the official guide. This is a
provenance and data-entry integrity check, not standardized
administration or psychometric interpretation.

**2026 source freshness:** The University of Oregon revised its
administration-and-scoring guide July 1, 2026 without changing scoring
rules. On September 17, 2026, it reported that certain Grade 1 PSF
scoring materials contained incorrect phoneme counts and published
corrected materials. Educators recording Grade 1 PSF results should
verify the official corrected materials, especially if working from
older copies. See https://dibels.uoregon.edu/news.

Official source: https://dibels.uoregon.edu/materials/dibels

DIBELS® is a registered trademark of the University of Oregon.
The official materials have specific usage conditions. Bede does not
distribute, rehost, modify, copy, prompt with, or silently reproduce test
items, scoring booklets, benchmark lookup tables, or proprietary norms.
Nothing in this implementation implies endorsement or certification.

## Classical formative evidence

The initial catalog offers oral narration, oral examination, composition,
translation, academic observation, and applied academic work.
Each entry records *how the work was completed*, not personality, religious
commitment, comparative standing, learning styles, or any claim about
underlying aptitude. The parent or instructor is responsible for recording
the actual observation.

## Other external assessments

An educator can enter the measure name, numeric reported result, source
and unit from an independent instrument. The system does not map it to
DIBELS, compare scores between frameworks, assume norms, or invent grading
rules. Approval for a future formal integration must consider a publisher's
usage rights, age/grade applicability, standardized conditions, validity,
and safe cross-framework interpretation.

## Security and data lineage

- API: `GET /diagnostic/assessment-frameworks`; parent-only
  `GET /diagnostic/{student_name}/assessment-records`,
  `POST /diagnostic/{student_name}/assessment-records`,
  `DELETE /diagnostic/{student_name}/assessment-records/{record_id}`.
- Input contract: `services/assessment_interop.py` keeps a legacy-safe
  `EducatorAssessmentInput` reader and a stricter
  `EducatorAssessmentSubmission` for **new writes**. The new-write
  validator checks measure/unit correspondence, reported grade, testing
  window, nonfinite or impossible percentages, and official risk labels.
  `extra="forbid"` rejects raw answer/item fields and unrecognized
  scoring metadata. Invalid historical content cannot be silently
  promoted to new evidence.
- Storage: additive `educator_assessment_evidence` table, student-scoped
  authenticated encryption under the existing student key and AAD.
  An external framework identifier is indexed in plaintext for schema
  management, but all scores, provenance and measure details are encrypted.
- Retention: until the student is deleted or an incorrect record is
  individually removed. Removal is an actual database delete; destruction
  of the student key makes prior encrypted copies unreadable. No new
  cloud sync, background agent, or model-training export is created.
- Access: parent only, enforced in the assembled-app route guard matrix;
  no demo or child-role access. The panel is shown only in Progress.
- Locales: English and Spanish use matching assessmentStudio keys.
  The parent UI fetches the framework's allowed measures and reporting
  units from the server, rather than maintaining a second divergent list.
- Tests: strict input validation, database encryption, student isolation,
  tampering exclusion, deletion, parent-only dependencies, real API invocation,
  and existing student-deletion regression.

## Scope still needed for the full Teaching Desk

The first version is a **recording and review experience**, not a full
classroom assessment dashboard. Genuine vendor-based integrations require
documented permission and supported data exchange. Before any attempt at
automated benchmark interpretation, complete formal psychometric validation
and review with qualified educators. A co-op/classical-school deployment
requires separate authorized educator accounts, parent consent, and
household-scoped access, not a reused parent password.

Next: lesson-aligned assessment evidence views, curriculum mappings with
source provenance, verified instructional delivery, and independently
evaluated outcomes, with suitable separate consent for research.
