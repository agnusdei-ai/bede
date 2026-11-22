# Logic, Computing & AI Foundations I — studio

## Purpose and boundaries

Ninety hours across36weeks, included in the timetable. Beginners learn computational reasoning alongside classical argument: a claim needs reasons; a program needs a specification and tests. This half credit is not an additional full logic credit and does not double-count humanities time.

The local-nature project is **broad leaf-form classification**, an entry point to identification, not a reliable species-recognition product. Never use its output for edibility, medicine, land management or protected-species decisions. A botanical identification requires appropriate references, context and expert verification. No learning accuracy claim about Bede follows from this exercise.

Use public, non-sensitive observations on adult-approved safe sites. No exact coordinates, faces, names, home addresses, student IDs or private-school schedules in data. No public posting required. A teacher can supply observations or safe plant samples for learners who cannot access a site.

## Concepts in sequence

- Weeks1–4: rules, sequences, variables, values, conditions and tests.
- Weeks5–9: lists/loops, means/range, separate development/held-out tests, version1.
- Weeks10–18: Boolean logic, types, functions, source verification, error counts, generated-prose audit, data card, version2.
- Weeks19–27: classification key, bounded observations, median/mean, causation limits, CSV, charts, decomposition, refactoring, version3.
- Weeks28–36: privacy review, rule/prediction/generation distinctions, trade-off analysis, reproducibility, held-out evaluation, oral defense, safe archive/deletion.

The weekly map supplies specific tasks. Document04 authors agendas through week9, including loops, missing-data means, spread and a fresh-card test plan. Teacher prepares lessons after week9.

## Three kinds of system

1. **Rule:** explicit conditions written by a person. The included baseline does not learn from data.
2. **Statistical prediction:** a fitted pattern estimated from data with uncertainty. A teacher can demonstrate a majority-label rule fitted on a small training table using paper; it is a model of estimation, not modern AI capability.
3. **Generated answer:** output from a generative model can sound coherent while containing errors; language fluency is not evidence of truth. A teacher-written plausible paragraph with two planted errors is an adequate offline verification exercise.

No student account on a commercial AI service is necessary. An adult may demonstrate an approved service only after age, consent, privacy and school review; do not upload learner work/identifiers. A disconnected Python interpreter can run this project's code. **This does not imply Bede operates offline**.

## Student delegation rules

Students must personally formulate questions, read cited evidence, collect/label observations honestly, choose a method, attempt core work, explain code, analyze errors and defend conclusions. Do not delegate required unaided mathematics, thesis/argument formation, graded translations, lab observations, source verification or oral defense to generation tools.

After an independent attempt and adult approval, tools may help explain a syntax error, suggest a test case, reformat a table or offer a critique for the student to evaluate. Log assistance and preserve before/after work. Generated citations/labels are unverified until checked against an actual source. Never fabricate measurements, interviews, results or resource permissions.

## Runnable baseline — learner instructions

Files in `project/`: `leaf_baseline.py`, `observations.csv`, `test_leaf_baseline.py`. Python3 standard library only; no network, installation of packages, secret, account or paid API. Adult installs an approved interpreter if absent.

From this curriculum directory:

```
python3 project/leaf_baseline.py project/observations.csv
python3 -m unittest discover -s project -p 'test_*.py'
```

All included records are **fictional teaching records**, not actual scientific observations. Do not relabel them as a field study. The test table deliberately includes a recording error and an incomplete observation. Expected initial result: among5 known-label test cases,3 correct,1 mistaken classification and1 abstention;4/5 receive a known prediction;1 additional unknown-reference row is handled separately. Small example datasets cannot establish real-world accuracy.

### Starter rule

If blade is needle-like and division is False or missing (None), label `needle_like`; if division is True or any invalid type, label `unknown` because that combination is inconsistent or invalid. Otherwise, if blade is flat and division is a boolean, use `compound_broad` for True and `simple_broad` for False. Otherwise label `unknown`. Numeric 0/1 and strings are not booleans for this contract. This simplistic rule illustrates explicit logic, missing information and error; it cannot cover the diversity of real leaves.

**Paper trace:** needle + True → unknown; needle + missing → needle_like; flat + missing → unknown; flat + False → simple_broad. Explain why missing division prevents the flat decision but not the needle decision. CSV headers must be the six unique schema fields; every record must have six fields. A present blank note is allowed, an absent note field or surplus field is an error.

Week1 use printed cards to trace the rule before code. Week2 run tiny variables/print statements from document04. Week3 run/trace the function. Week4 predict tests before execution and write a limitation statement. The full CSV/evaluation machinery is teacher-supplied scaffolding, **not code a beginner is expected to author by week4**. Unpack it later when lists, functions and tables are taught.

## Integrated local-nature project specification

**Question:** how well does a transparent rule classify our approved broad leaf-form observations, and where does it fail?

1. **Plan:** adult approves safe site, broad categories, public/anonymous records and collection method. Use ID such as `L01`; record generalized habitat (“public garden”), not a location trace. Prefer original sketches or approved public-domain/lawfully used reference images.
2. **Observe:** collect12–20 lawful, safe observations across at least two broad forms if feasible. Record blade type, division status, length with units if used, missingness and uncertainty. No picking needed; adult supplies safe material where necessary.
3. **Reference:** check each proposed label against an adult-approved botanical key/book and qualified review. Store title/edition/page or URL, access date, and uncertainty. If no justified reference label exists, mark `unknown`; do not treat an AI output as ground truth.
4. **Split before tuning:** adult freezes a development subset and a held-out subset. Student may revise rules on development examples only. A tiny convenience sample is not representative science; state this explicitly.
5. **Baseline:** use unchanged rule first. Compute known-reference correct/wrong/abstain counts; report coverage and denominator. Keep unknown-reference cases separate.
6. **Revise:** one justified rule or data-quality improvement; record what changed and why. Do not tune against held-out rows. If held-out cases are inspected to revise, retire them as tests and obtain genuinely new held-out cases with adult oversight.
7. **Compare:** show both versions on the same frozen evaluation set after finalizing each. Report failures, not just favorable percentages. Separate observational/label mistakes from rule shortcomings.
8. **Defend:**5-minute demonstration plus questions: “Which branch ran? What would change your conclusion? Is a label verified? What data were excluded? What can this program not tell us?”
9. **Archive:** code, minimal non-sensitive data, source/license log, test output, README, assistance record, error analysis and reflection. Adult approves retention/deletion; no public repository required.

## Worked error analysis

The supplied test record with flat blade/undivided observation but compound reference label is an intentional **data-entry/observation mismatch**. The rule follows its input yet disagrees with the reference. Inspect collection and labeling before adding arbitrary special cases. Another record is missing division status: abstention is more honest than a confident guess.

Report:

- Known-reference test cases =5.
- Correct known predictions =3; wrong known predictions=1; unknown/abstentions=1.
- Known-case accuracy including abstentions =3/5=60% on this example table.
- Coverage=4/5=80%; correctness among covered cases=3/4=75%.
- Unknown-reference cases=1, not evidence for species accuracy and not included in known-label denominators.

Never advertise these example percentages as Bede efficacy or scientific validation. When using real learner data, results will differ.

## Teacher-only no-AI verification exercise

Give this **invented unreliable paragraph**: “All broad leaves belong to oak trees. Because a program prints a species name, the species has been scientifically verified. A five-leaf sample proves the classification works everywhere.”

Learner identifies at least three errors: broad leaves occur across many plants; program output does not verify a label; convenience sample cannot justify universal generalization. Require a real reference for the first claim and a design critique for the third. This meets evidence-verification objectives without pretending an actual AI generated the paragraph.

## Final deliverable checklist

Question and limitations; lawful references and licensing; minimal data/provenance; transparent rule baseline; readable code; frozen tests and error table; comparison with revised version; oral explanation; accessibility adaptations and AI-assistance disclosure. Use project rubric, not popularity or interface polish.

