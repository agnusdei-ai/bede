# Review checks — November 5, 2026

**Historical record:** the checks below describe the November 5 package. Subsequent owner-directed agentic subject reviews, corrections and current file hashes are in [the adoption register](ADOPTION-REVIEW.md) and `reviews/`. The routine human subject-review requirement below is superseded by [the replacement policy](audit/REVIEW-POLICY.md); it is not a claim those human reviews occurred.

## Completed

- All 36 week headings occur once, with one objective/input/assignment/check entry for each of six academic subjects: 216 entries.
- Index links resolve; eight core documents plus index present.
- Five 180-hour courses plus three 90-hour strands total 1,170 hours and 6.5 planned credits under the stated convention.
- Family, co-op and school schedules independently reconcile to 32.5 hours/week.
- Nine authored weeks each contain six subject teaching blocks. Extension weeks5–9 have five daily agendas per academic strand, explicit PE/arts plans and a quarter demonstration replacing rather than adding assessment time.
- The 18-investigation ledger reconciles to 27 designated investigation-slot hours; the additional 27 hours are labeled lab-related studio, not bench experimentation.
- Ten executable baseline tests pass, including missing/inconsistent inputs, fixture denominators and malformed/duplicate CSV data.
- Textbook publisher prefaces and six public-domain catalogs inspected; World History regional section references checked against chapter introductions.
- Combined HTML internal anchors and 390px viewport width checked.
- Tagged PDF exported; extracted text includes beginning/end of the full-year map, starter lessons, lab, project and cost sections. Reading-edition cover visually inspected.

## Extension checks and limits

- Reading sequence remains two Odyssey books/week: IX–XVIII in weeks5–9; XXIII–XXIV and completion remain week12. Scene boundaries and reading time caps identify narrated versus directly read material.
- Publisher history headings checked for Mediterranean/Persia/Indus and South Asia (§5.4). D'Ooge contents checked for second declension (IX–X) and present *sum* (XVIII); only taught forms are assessed.
- Latin passage/key internally checked for case, number, verb agreement and vocabulary; the nine-sentence demonstration has explicit parsing guidance. This is not independent human-specialist review; the instructor sign-off remains a pre-use gate.
- Two literal Python teaching snippets and missing/all-missing/zero cases run in the validator. Existing project fixture tests remain separate; held-out recipe uses the loader's actual schema.
- Weeks6/8 have detailed supervised procedures and labeled example-data alternatives; weeks5/7 are design/model/data work, not physical experiments. Week9 revisits safe observation without adding a designated ledger investigation.
- Prerequisite/assessment/access matrix and a no-double-counting timetable are in document04. Mathematical worked answers and biological denominators were checked; automated text coverage is not evidence of educational validity.

## Not established by these checks

Pedagogical effectiveness, learner outcomes, mastery, local standards equivalence, legal credit approval, accreditation, comprehensive accessibility conformance, commercial redistribution permissions, current retail prices or specialist availability. No physical classroom trial or physical-device testing was conducted. Subject-specialist review and adoption decisions remain necessary.

## Reproduce

From the workspace root:

```
python3 -B curriculum/grade-9/validate.py
python3 -B curriculum/grade-9/project/leaf_baseline.py curriculum/grade-9/project/observations.csv
node curriculum/grade-9/export.mjs
```

The validator uses only Python's standard library; the export uses the existing workspace toolchain. The curriculum does not depend on a paid AI account or on any unimplemented Bede feature.

