# Essay Studio

**Your ideas. Your words. Bede helps you make them stronger.**

Essay Studio is a lesson activity for grades 6-12 where a student writes an
essay with Bede coaching beside the draft. It is built on classical writing
practice: read an excellent model, say what it does, then write your own,
reason about it, and revise. It is not an essay grader and not a general chat.

The student is the author. **Bede never writes the student's text**: no
thesis, outline, paragraph, sentence or model answer, and nothing Bede says is
ever inserted into the draft.

Starting SHA for this build: `4e53b265`.

## Where it lives

- **In the lesson, like Sound Time and Number Time.** Bede offers it with the
  `invite_essay_studio` tool, in Language Arts or Living Books, when that
  subject is in today's plan. The tool puts an "Essay Studio" card in the chat.
  The card shows **Continue writing** when the student has an unfinished draft,
  and **Start an essay** otherwise. There is no menu item, no header control and
  no Practice hub.
- **Not inside Practice Coach.** Practice Coach reads marked work and plans
  practice with code; Essay Studio is live coaching. Practice Coach, Quiz
  Builder and Teacher Quiz Studio are unchanged.
- **The draft is the workspace.** On a large screen the coaching panel sits
  beside the draft. On a small screen a two-way switch shows the draft or the
  coaching, and switching keeps the text, cursor and scroll position.
- **The handwriting canvas is not used.** `HandwritingCanvas.tsx` is a drawing
  surface (strokes on paper), not a text editor, so Essay Studio has its own
  text editor.

## Exercises

Three exercises from the progymnasmata, the graduated rhetorical exercises, in
order:

| Exercise | What the student does | Opposing view step |
| --- | --- | --- |
| `narrative` | Tells an event clearly and in order | no |
| `refutation` | Shows why a claim does not hold | yes |
| `thesis` | Argues a general question, answering the other side | yes |

Which exercises a student may start depends on their **stage**, which comes
from the student's saved grade and a per-student setting:

- `essay_rhetoric_from_grade` (`SessionConfig`, default 9, allowed 6-12) is the
  grade at which the rhetoric stage begins. Grades below it are the logic stage.
  Classical schools draw this line differently, so it is a family setting with a
  conservative default, not a fixed rule.
- Logic stage: `narrative`, `refutation`. Rhetoric stage: all three.

The full fourteen-exercise sequence is deferred.

## The writing flow

Understand the task, model, position, plan, draft, examine, revise, reflect.
The student can move between stages freely; none is forced. A draft resumes at
its saved stage.

- **Task.** The question or topic (from Bede's invitation, or the student's own).
- **Model.** The student reads a passage from their assigned book that does what
  this exercise does, notes which passage, and says in their own words what it
  does. **No model passages are bundled in this build** (see Limitations), so
  the model is always the student's own book. The model area is labelled as a
  model and kept separate from the draft.
- **Position.** What the student will show or argue.
- **Opposing view** (refutation and thesis only). The student states the other
  side fairly, before replying to it. Bede asks for this; Bede never argues the
  other side for them.
- **Plan.** Up to six points, in the student's words.
- **Draft.** One paragraph at a time. Saving is automatic.
- **Examine and revise.** "Ask Bede" returns one focused note and one question.
- **Reflect.** A fixed question about honesty and fairness (did I represent the
  source and the other side fairly; did I invent anything). Written by the app,
  not by a model.

**Finish for today** saves and closes. **Mark complete** finishes the essay.
Neither grades anything.

## Coaching

Each request returns one criterion, one short note and one question. The
criteria reuse the five composition dimensions where they fit
(`services/diagnostic/composition.py`), plus two for argument and one for
audience. Emphasis follows the task:

| Tier | Criteria | Offered at |
| --- | --- | --- |
| Clarity and form | `sequence`, `language_quality` | every stage |
| Reasoning and evidence | `completeness`, `detail`, `synthesis`, `position`, `opposing_view` | every stage |
| Audience and persuasion | `audience` | examine and revise only |

`position` and `opposing_view` exist only for refutation and thesis. Coaching
is labelled formative. It is never a grade, score or level.

**It writes nothing to the mastery record.** Narration's `assess_narration`
remains the only input to the writing estimate, and Essay Studio reuses the
dimension names, not the scoring. No quiz weight or new formula is used, and
completing an essay writes no work-ledger row in this build.

## Rules the code enforces

- **Authorship.** Drafts hold only what the student typed or pasted; the editor
  reports typed and pasted character counts and the parent sees the pasted
  count. A coaching note is at most 240 characters, a question must end in a
  question mark, and a note or question that quotes words not in the student's
  own draft is dropped, so Bede cannot hand over sentences or invented
  quotations. There is no "insert" or "apply" action anywhere.
- **Eligibility, on the server.** Grades 6-12, Language Arts or Living Books,
  a parent or the signed-in child for that learner only. Educators and the
  public demo are refused.
- **Time.** A new essay is refused with under three minutes left in the block
  (the same floor as narration). Saving, coaching on an existing draft and
  leaving are never blocked.
- **Safety.** Before coaching, the draft goes through the same deterministic
  safeguarding check as a chat message; a match gets the safeguarding response
  and the usual alert, and no coaching.
- **Routing.** Coaching uses the same routed client as the lesson
  (`ai_service._client`), so it follows the installation's adapter order and
  any `BEDE_FORCE_ADAPTER` pin. A local-only installation has no cloud adapter
  to fall back to.
- **Privacy.** Drafts are encrypted with the student's own key, bound to the
  draft's id, included in the parent's export, and deleted with the student.
  Credential-shaped text is redacted before a draft reaches the model. No
  draft content is logged.
- **Consent.** Saving and coaching require collection consent.
- **One unfinished draft per student.** Starting a new essay while one is
  unfinished needs an explicit, confirmed replace.
- **Stale writes.** Every save carries the draft's version; a stale version is
  refused (409) instead of overwriting newer text.
- **Limits.** 20,000 characters of draft, 12 coaching requests per draft per day.

## Persistence

`ESSAY_STUDIO_SAVE_DRAFTS` (default `true`). When `false`, drafts are kept only
in the server's memory for that sign-in (up to 6 hours) and are gone after
it; the studio says so before writing begins. Saved drafts are kept until a
parent deletes them or the student is deleted.

## Who can do what

| Action | Student | Parent |
| --- | --- | --- |
| Start, write, ask Bede, finish for today, mark complete | yes | yes |
| Replace an unfinished draft (after confirming) | yes | yes |
| See finished essays and delete drafts | no | yes |

## API

All routes are under `/essay-studio/{student_name}`.

- `GET /status?subject=<Subject>` → `{available, reason, persistence: "saved"|"session",
  stage_band: "logic"|"rhetoric"|null, exercises: [{id, label}], active: DraftSummary|null}`.
  `reason` is null when available, else `grade`, `subject` or `role`.
- `POST /drafts` with `{subject, exercise, prompt, replace?: bool, time_remaining_seconds?: int}` → `Draft`.
  409 `{"detail": {"code": "active_draft_exists", "active": DraftSummary}}` without `replace`;
  409 `{"detail": {"code": "not_enough_time"}}`; 422 for an exercise not offered.
- `GET /drafts/active` → `Draft` (404 when none). `GET /drafts/{id}` → `Draft`.
- `PUT /drafts/{id}` with `{version, stage?, model_source?, model_observation?, position?,
  opposing_view?, plan?: [str], text?, reflection?, typed_chars?, pasted_chars?}` →
  `{version, updated_at, persistence}`. Counts are increments. A stale version →
  409 `{"detail": {"code": "version_conflict", "current_version": int}}`.
- `POST /drafts/{id}/coach` with `{version}` → `{coaching: Coaching}` or
  `{safeguarding: true, message}`. 409 stale, 429 past the daily limit, 503 when
  the model cannot be reached (the draft is untouched).
- `POST /drafts/{id}/complete` → `Draft`.
- `GET /drafts` (parent) → `{drafts: [DraftSummary]}`. `DELETE /drafts/{id}` (parent) → 204.

```
DraftSummary = {id, title, exercise, stage, status, word_count, updated_at}
Draft = {id, subject, exercise, prompt, title, stage, status: "active"|"finished",
         model_source, model_observation, position, opposing_view, plan: [str], text,
         reflection, next_step, version, word_count, paragraph_count, typed_chars,
         pasted_chars, coaching: Coaching|null, reflect_questions: [str],
         uses_opposing_view: bool, criteria: [{id, label, tier}], persistence,
         created_at, updated_at}
Coaching = {draft_version, created_at, stage, formative: true, criterion, label,
            tier: "form"|"reasoning"|"audience", note, question,
            analysis: {word_count, paragraph_count, sentence_count}}
stage ∈ task | model | position | plan | draft | examine | revise | reflect
```

## Extension points

- **Oral delivery** (deferred). The reflect stage is where a future spoken
  delivery step would sit. No speech provider is added, and nothing here speaks.
- **Bundled models.** A reviewed, public-domain passage per exercise could be
  added as read-only `model_text` on the status response. It must stay a
  separate, labelled panel and never enter the draft.

## Decisions recorded in this build

Minor and reversible.

- The stage line is a per-student setting (`SessionConfig`), since a household
  has no family-wide settings table.
- Offered at most once per session, only when the subject is in today's plan.
- The model step uses the student's own assigned book only.
- No work-ledger row on completion.
- The repository bans one of the words the brief used for test data; tests use
  "sample" data.

## Limitations

- **Classical-educator review is pending.** The exercise sequence and the
  coaching prompts have been reviewed by an agent, not a classical educator.
  Until that review, copy says "built on classical writing practice" and never
  calls Essay Studio classical or a classical curriculum.
- **No bundled model passages.** No passage text is approved for this use in
  the installed content (the catalog holds book titles, not text, and the
  Shakespeare supplement in #925 is unmerged). The student reads from their own
  assigned book.
- Grades 3-5, a Practice Coach hand-off, teacher-authored prompts and models,
  oral delivery and the rest of the fourteen exercises are deferred.
