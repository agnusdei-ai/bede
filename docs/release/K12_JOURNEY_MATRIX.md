# Grades 9-12 journey matrix (parent and educator)

Built from the routes in `homeschool-tutor/src/App.tsx` (`/setup`, `/pod`, `/progress`, `/session`, `/sandbox`, `/classroom`, `/classroom-setup`, `/lesson-planner`, `/educator-enroll`) and the actions on them. Evidence is kept in two columns on purpose: code/test evidence says the path is wired; browser evidence says it renders and behaves. A row with no browser evidence is **unverified in a browser**, not passed.

Date: 2026-11-20. Browser = headless Chromium at 390x844, English and Spanish, driven by a by-hand script against the Vite dev UI with **the API stubbed in the browser** (no backend, no model, no provider call, no configuration change). It shows the UI's behavior for a grade 10 learner given the responses a real server returns; it does not exercise the server.

| # | Journey step | Upper-school (9-12) expectation | Code / test evidence | Browser evidence |
|---|---|---|---|---|
| 1 | Setup: add learner, pick grade | Grades K-12 selectable; stage 6-12 | `ParentSetup.grade.test.tsx`, `FAMILY_GRADES`; backend `VALID_GRADES`, `grade_to_stage` | 390px en/es: grade 10 and 12 options present, no overflow, no console errors |
| 2 | Pod dashboard: learner cards, actions | Reachable, usable on a phone | `PodDashboard.focusedLesson.test.tsx` | **Defect found and fixed:** header buttons forced the page to 603px at 390px; now wraps (`flex-wrap`), 390px, no overflow en/es |
| 3 | Learner selection (parent) | Active learner drives Progress | `Progress.upperSchool.test.tsx` | Switching works in the screenshot run (two learners) |
| 4 | Quiz creation (parent) | Grade list K-12; server accepts 9-12 | `QuizGrade` K-12 (`models/practice.py`), `GET /practice/quiz-options` grades; `test_demo_upper_school.py` | 390px en/es: all 13 grades listed ("Grade 9..12", "9.º..12.º grado"); generation call itself stubbed, not exercised |
| 5 | Practice Coach (photo quiz) | Subject-level, not grade-limited | `test_practice_coach.py` | Card renders at 390px en/es; upload not exercised |
| 6 | K-2 practice (Sound Time, Number Time, Map) | Not offered above grade 2 | `_practice_allowed` K-2 gate, `test_k2_*` | Not applicable to grade 10; not browser-checked |
| 7 | Results / work ledger | Records as usual | `WorkLedger.test.tsx` | Renders empty state en/es (stub data only) |
| 8 | Progress: mastery | Math skill map and reading engine are K-8: rows omitted with one sentence, no request made | `Progress.upperSchool.test.tsx` (verified by breaking it), `isUpperSchoolGrade` | 390px en/es: note shown, no math/literacy row, composition/language/music rows present, no overflow |
| 9 | Educator: roster and learner select | Grade shown per learner | `EducatorDesk.journey.test.tsx` | Works at 390px |
| 10 | Educator: DIBELS report grade | K-8 range stated; grade 9-12 learner must choose the report grade; nothing carried over from the previous learner | `EducatorDesk.journey.test.tsx` "never carries a report grade from one learner to the next" (fails when the reset is removed) | Grade 4 learner -> pick 6 and type a score -> switch to grade 10 learner: grade blank, score cleared, options K-8 only, save with no grade sends **0** requests; after choosing 8, **1** request |
| 11 | Educator: quiz studio, teacher quiz | Local model only; K-12 grade list | `test_teacher_quiz.py`, `TeacherQuizStudio.test.tsx` | Not browser-checked (needs local model route) |
| 12 | Child session at grade 10 | Tutor prompt uses exact grade, stage 6-12 | `test_demo_upper_school.py`, `ai_service` upper-school guards | Not browser-checked (needs a model) |

## What changed in this pass

- **Educator DIBELS screen.** The report grade is now blank until chosen, unless the learner is K-8 (then it defaults to that learner's own grade). Switching learner resets grade, score, source, band and message, so nothing typed for one learner can be saved against another. Save also requires the grade to be one the framework lists. The screen states the supported range (read from the framework, falling back to "kindergarten through grade 8") and says the grade is the one printed on the report, not necessarily the enrolled grade.
- **Pod dashboard header** wraps on a phone.

## Not verified

- Real backend, real model, voice, printing, and any physical device. Hosted or headless browser checks do not replace the owner-only acceptance on the pilot Mac and Safari.
- Rows 6, 11 and 12 in a browser.
- The stubbed profile card showed a raw plural key because the stub omitted its count; the real response carries it. Not a product defect.
- "Instructors & rosters" on the Pod page is English-only text (teacher screens are English-only by decision).
