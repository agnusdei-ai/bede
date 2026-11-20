# Grade 9 correction re-review — Algebra, biology safety and computing

## Identity and scope

- Agent identifier: **grade9-algebra-biology-computing-review** (actual assigned identifier; earlier entries used the shorthand algebra-biology-computing).
- Agent/model version: **not exposed by platform**.
- Date: **2026-11-12 UTC**.
- Independent review run: **delegated algebra-biology-computing correction re-review after main-agent revisions, 2026-11-12**. This is a descriptive identity, not a platform job ID.
- Authoring run: **main Replit Agent correction run; original author identity unavailable**. Authoring and this delegated reviewing run are separate.
- Original review: [algebra-biology-computing.md](algebra-biology-computing.md), preserved unchanged. This addendum supersedes only the correction dispositions below; it does not rewrite historical results or claim that previously defective physical procedures were safe.
- Scope: independently re-read the actual A1/B1/B2/C1/C2/C3 corrections, relevant subject instructions/assessment timing, revised investigation categories and supplied-data interpretation, current classifier/loader/tests/fixture, and corrected program scope. Changes to humanities/Latin sharing these files are not reviewed here. The original subject review remains the evidence for the unchanged authored mathematics and other inspected procedures; this is not a fresh full-year review.
- No external textbook was fetched or verified. OpenStax section/figure/exercise fidelity, edition/accessibility checks and permissions remain **outside this approval and blocked where AI ingestion would be needed**. No license, rights crosswalk or publisher approval is inferred.

## Three domain statuses

| Domain | Status | Precise conclusion |
|---|---|---|
| Algebra | **agent-reviewed** | A1 is closed: the readiness administration now matches 30m unaided +10m oral and fits the 60m session. No new defect found in the reviewed Algebra correction. Original mathematical-key findings and full-year/source limitations remain scoped as before. |
| Biology safety | **changes required** | B1/B2 physical hazards are removed from the authorized activities, rather than “made safe” by an unverified recipe. Counts/alternatives are coherent. One residual authored instruction, B4 below, still refers to a nonexistent physical indicator procedure and needs alignment before this corrected subject packet receives agent-reviewed status. This is not safety certification. |
| Computing | **agent-reviewed** | C1/C2/C3 are closed for the teaching contract: malformed widths/duplicate headers rejected, numeric pseudo-booleans rejected, and paper traces align with implemented abstention. Thirteen tests and independent checks pass with original fixture results preserved. This is not approval of a public upload service, student-data use or learning efficacy. |

## Correction dispositions and independent interpretation

### A1 — closed

`04-starter-lessons.md:54` now allocates **30m unaided +10m oral**, number-line model10m, supports10m; total60m. It explicitly places oral explanation before feedback and forbids teaching during the unaided portion. This matches `05-assessments.md:28`; it does not shorten the diagnostic or add extra learner time. Placement still depends on reasoning and conference/bridge evidence, not the ten-point total alone.

The stale program inclusion statement is also corrected at `01-program-and-delivery.md:118`: nine-week materials are included; complete weeks10–36 lessons are not. Neither correction establishes Algebra I completion, Geometry readiness or jurisdictional standards equivalence.

### B1 — closed by exclusion/replacement, not by physical-method approval

`06-biology-labs.md:35–41` now specifies **paper/accessibly presented synthetic descriptions only**, no liquids/food/heat/chemical handling and no adult-demonstration bypass. This removes the unspecified-product exposure path reviewed under B1. The coded descriptions are explicitly invented: A purple/purple, B pink/pink, C blue/blue-green.

Independent interpretation: A and B have matching within-sample repeat descriptions; C has differing descriptions. Neither the coded labels nor color words alone supply an indicator identity, calibration, chemical identity, exact pH or safety determination. The new document06 key correctly says no acid/base identity is established. Read-aloud words/tactile labeled tokens preserve the evidence-reasoning objective without making color discrimination a graded requirement.

`03-scope-and-sequence.md:32` and `04-starter-lessons.md:136–138` now describe supplied/model evidence and expressly forbid physical preparation/demonstration. The 90m day3 allocation independently totals10+30+15+15+10+10=90m. There is **no approved former physical indicator method** to revive by implication. See B4 for the remaining inconsistent key wording.

### B2 — closed by exclusion/replacement, not by mold-disposal approval

`06-biology-labs.md:83,90` excludes seeds, containers, damp materials, mold inspection/handling/disposal and daily growing time. The new paper comparison is in the existing90m slot; there is no biological waste or hidden after-hours inspection. `03-scope-and-sequence.md:216` aligns with synthetic counts and no growing/mold handling.

Independently recomputed the hypothetical day7 outcomes:

- A replicates8/10 and7/10: total15/20 = **75%**.
- B replicates4/10 and5/10: total9/20 = **45%**.
- Difference = **30 percentage points**, not a30% relative increase. If requested separately, relative difference from B would be30/45≈66.7%; that is not the authored question.
- The defined observation is an **emerged radicle**, not presumed viability. Preserve the two replicates rather than presenting20 independent experimental treatments. Invented counts establish neither a real effect nor causal attribution.

The revised categorization at `06-biology-labs.md:9` is internally consistent: **6 bench/organism measurements** (1,3,4,6,8,32), **3 field studies** (20,24,30), **9 models/evidence activities** (2,10,12,14,16,18,22,26,28); 6+3+9=18. Eighteen90m designated slots still total27h;54h scheduled studio remains explicitly **not**54h bench experimentation. These are scheduled categories, not verified hours of actual learner participation.

### B4 — open, instructional alignment correction required

`04-starter-lessons.md:141`, immediately after the revised paper-only week2 agenda, still says: **“See investigation2 for no-hot-liquid student procedure.”** There is now no liquid procedure in investigation2; it is expressly excluded. The same key's unqualified statement about relative acid/base behavior can also be misapplied to coded, uncalibrated synthetic descriptions, although document06 correctly disallows that inference.

This does **not** negate the explicit no-handling prohibition or mean a physical lab has been approved. It is nevertheless an incorrect learner/teacher cross-reference in the actual authored key, not a concern that can be closed by test success. Required closure: replace the obsolete liquid-procedure reference with the paper-only interpretation and its limits; clarify that these coded descriptions establish neither acid/base identity nor numerical pH without calibration/reference information. Retain the explicit physical exclusion. Re-read that key against document06 and rehash document04 after correction. No new chemical recipe or mold-containment method is requested.

### C1 — closed for the stated teaching schema

`project/leaf_baseline.py:38–45` now checks header count **and** required-name set, rejects duplicate headers, rejects `DictReader` surplus keys and any missing-field `None`, and provides row-ending line numbers for width failures. Blank field versus absent field is distinguished. Independent in-memory reruns of the original three failures:

| Check | Observed corrected behavior |
|---|---|
| Six-column header, seven-field row | `ValueError`, row-ending line2/exactly-six-fields message |
| Six-column header, five-field row | `ValueError`, same actionable width message |
| Seven-column header with repeated `id` | `ValueError`, exact-schema/no-duplicates message |
| Six fields with a present empty final note | Accepted; note is the empty string, not `None` |

The new test methods explicitly cover these regressions (`test_leaf_baseline.py:39–59`). This verifies widths/header uniqueness for the curriculum contract, not arbitrary adversarial CSV syntax, file-size bounds, encoding recovery or a hardened network-facing service. No such service is part of this scope.

### C2 — closed

`leaf_baseline.py:16` now uses `divided is False or divided is None`, eliminating equality-based acceptance of0/0.0. Independent branch checks rejected numeric0/0.0/1/1.0, strings, empty lists and dictionaries for needle/flat/unknown inputs. Valid booleans/None behaved as documented:

`needle+False→needle_like; needle+None→needle_like; needle+True→unknown; flat+False→simple_broad; flat+True→compound_broad; flat+None→unknown`.

`test_needle_rejects_numeric_and_string_division` adds a targeted regression without changing the existing inconsistent-input test. CSV parsing still admits only `"true"`, `"false"` or blank, so the direct-function contract and loader-mediated contract are now consistent.

### C3 — closed

`07-computing-project.md:50–54` now explicitly states the inconsistent needle/divided case, invalid numeric/string types, missingness differences, schema width/uniqueness and blank-note exception. The four paper traces at line52 match actual code; in particular needle+True abstains and needle+missing does not. The rule remains a fixed teaching rule, not learned prediction or species identification. Beginner responsibility still excludes authoring the entire CSV/evaluation scaffold by week4.

## Tests, evidence and limits

Executed with existing Python3.13.11 and bytecode disabled; no packages/runtime/app/export changes:

1. `python3 -B curriculum/grade-9/validate.py`: passed document/map/timetable checks, two literal snippets and missing/zero checks, and **13 unit tests**.
2. Baseline command on the actual unchanged fixture: known-reference5, correct3, wrong1, abstain1, unknown-reference1; aggregate accuracy0.6, coverage0.8, correctness-when-covered0.75. No labels were edited to improve results.
3. Separate stdin-only checks replayed all three original malformed CSVs and a present blank note with in-memory file handles; asserted the type/valid-input matrix above, both literal teaching snippets (`30 6`, `4.8`), corrected diagnostic/session arithmetic, paper investigation timing, germination fractions and6/3/9 category arithmetic. All passed.
4. Read the current actual code/tests/project instructions and biology procedure document, affected map/starter/assessment sections, correction diffs and the review-gate schema. Existing ten tests remain present; three added methods strengthen coverage. This reviewer edited no curriculum or tests.

No new external fetching was needed for this correction audit; independent lawful-source checks in the original report remain historical supporting evidence only. The original exhaustive authored-algebra solution audit is not represented as newly rerun in full here. Shared-file humanities/Latin revisions are excluded from this review's conclusions even though whole-file hashes bind the evidence.

## Remaining conditions and disagreements

- **Biology authored correction B4 remains open.** A claim that all six corrections are therefore a clean subject pass would be too broad: A1/B1/B2/C1/C2/C3 are closed, but the replacement left a stale authored key/cross-reference. The required change is textual alignment, not restoration of excluded activities.
- Original A2/B3 limitations remain: weeks10–36 lesson/exam content and later physical methods are not all authored/reviewed. Review complete exact methods before future physical use. The paper week22 replacement does not make other later ledger rows executable protocols.
- Original site-specific controls remain: actual adult competence/supervision, approved specimens/products/equipment, emergency/disposal arrangements, and appropriate access alternatives must be implemented; paper alternatives do not demonstrate instrument operation or bench skills.
- Rights/source-dependent verification, actual accessible editions, local credit/lab designation and learning outcomes remain unestablished. Do not treat these scoped agent conclusions as publisher permission, safety certification, human endorsement or full-year readiness.
- Missing human subject appointments are not routine production blockers under the owner-directed policy. No appointments, qualifications or permissions are fabricated.
- Changed hashes require affected re-review. Corrections do not authorize contact, purchase, publication, enrollment, corpus use, real student-data use or deployment.

## Local evidence hashes

Relative to `curriculum/grade-9/` except the explicitly marked policy path. Hashes identify the actual reviewed revision, not an invented source commit. The preserved original report has its own historical hashes; they are not replaced with these current values.

| Local evidence | SHA256 |
|---|---|
| `../REVIEW-POLICY.md` | `2ee66970f24e9421bf02e14bfac42ad7e6a66879ba190cec3948338deec072e9` |
| `01-program-and-delivery.md` | `8f541df0b770f31783e8a88156f6b42895ab9672651c491fee0d564fc88e2855` |
| `03-scope-and-sequence.md` | `cbbf2be31955f7b8b47eb26410067fe1fd17cb2720b01ef4d1ed83ff32fae852` |
| `04-starter-lessons.md` | `49bddcc0fae61a2328415c5cac2dbfa595f968194c958665fa094e0daee9c572` |
| `05-assessments.md` | `fa39cc5f411bb8c60d1e0cfda3721d896bb5f744ec8750053996108c09164f90` |
| `06-biology-labs.md` | `5b1e8a1cd8beffae9450edaed13417b283678236983b13b7b76d4033b184b0d8` |
| `07-computing-project.md` | `19fdab8384b71f1f45b3de51aa5ee8516e4113bd3aead66af231224d5ea47365` |
| `project/leaf_baseline.py` | `c5163e54b9ed550135e1b6819603a818d8c96c555876dc586a030b6a0f8392bb` |
| `project/test_leaf_baseline.py` | `62eb4731c283b8cadcb913b8a55f58cbbb6cb7a32d71838bd0a96161354dd2ca` |
| `project/observations.csv` | `6496972cad93fe740003dd3adab8cb8d79265a671904f2e0b9dc423094865092` |
| `validate.py` | `fbc4774b0aaafaffac436793be2d5d3ded54a3a3ddb0e73183418a318024d68d` |
| `review_gate.py` (evidence schema only) | `8cc1962782d122534570ef04b25b92f4a3d134764be9f0ac9036eaa1b97408d7` |
| `reviews/algebra-biology-computing.md` (preserved history) | `143a452aefe3d3da96b4b9739e053a5fb167cc131a6c4b3f4ca57d423ff7eb25` |

## Final limited disposition — B4 closed, 2026-11-12 UTC

Reviewer: **grade9-algebra-biology-computing-review**; version **not exposed by platform**. Independent review run: **delegated final B4 paragraph recheck after main Replit Agent correction, 2026-11-12**; authoring run: **main Replit Agent correction run; original author identity unavailable**. These descriptive identities are not invented platform job IDs.

Read the corrected actual week2 key at `04-starter-lessons.md:141` against the paper-only agenda and document06 investigation2. It now states that coded, uncalibrated synthetic descriptions establish neither acid/base identity nor exact pH; A/B agree across repeats while C differs; calibration and controls are absent; investigation2 is paper-only; no chemical preparation, handling or physical demonstration is authorized. This matches the actual synthetic evidence and removes the obsolete liquid-procedure reference. **B4 is closed.** Earlier B4 findings and the earlier biology status above are preserved as historical dispositions, not current open findings.

**Change-isolation evidence:** in memory, replaced this single new paragraph with the exact previous paragraph and SHA256-hashed the reconstructed document04. Result `49bddcc0fae61a2328415c5cac2dbfa595f968194c958665fa094e0daee9c572` exactly matches the prior reviewed bytes. Thus this paragraph is the **sole document04 content change** since the recheck, not an assumption from a repository-wide diff. All other source hashes in the three domain records remain unchanged. No broader subject re-review is claimed or needed for this isolated correction.

Current document04 SHA256: **`74c3edec230b8758ee20cc2583b7f63fadaa7763eddf986ecd8f358ddf898108`**. The evidence-hash table above records the preceding recheck revision; this final value supersedes its document04 entry for current evidence. All three document04-dependent records are refreshed to this value.

Re-ran the unchanged validator: map/timetable checks, teaching snippets/missing-data checks and **13 unit tests pass**. This reviewer edited no curriculum or tests and fetched no external book material.

### Current three domain statuses

- **Algebra — agent-reviewed**, within the previously recorded authored scope; no Algebra content changed.
- **Biology safety — agent-reviewed**, for the reviewed authored procedures and paper-only replacements, with B1/B2 closed through physical exclusion and B4 now closed. This does not approve the excluded physical methods, later unauthored methods, any site or laboratory certification.
- **Computing — agent-reviewed**, within the recorded corrected teaching contract; no computing content changed.

No specific authored correction findings remain open in this scoped review. Earlier source-dependent, later-method, rights, supervision, accessibility and local-credit limitations remain **scope exclusions and implementation conditions**, not inferred approvals. No OpenStax verification, AI-ingestion permission, physical-safety certification, human endorsement or full-year readiness follows. Changed hashes still require affected review; no publication, deployment, enrollment or student-data use is authorized.
