# K-2 practice: Watch, Together, Your turn

**Status: steps 1 and 3 built; the rest is specification.** Step 1 of §9 (the
shared `invite_practice` invitation, the per-child setting, and phonics) and the
first part of step 3 (practical math's counters, ten-frame and number bonds) are
built. Number Time, Sound Time and Map Practice are also available as direct,
temporary activities in the public demo; their limits are described in §5.3. Step 3 was built before step 2,
handwriting, because handwriting waits on decision 40(c), the handwriting
style, which is still open. The rest of the first wave is not built. Map
reading, from the second wave, shipped in
#830 (`docs/MAP_PRACTICE.md`) and set the pattern this spec follows. The
decisions this spec cannot make for itself are `docs/DECISIONS.md` entry 40;
(a) and (b) were ruled by the owner on 2026-11-16, and (c) to (h) are open.

## 1. What this is for

Short, hands-on practice in the fundamentals a child needs before the rest of
schooling can stand on them, for kindergarten through grade 2. Bede shows the
child how, does it with them, then lets them try alone. It is imitation, the way
these skills have always been taught, with an animated demonstration and every
word spoken aloud.

Two waves:

| Wave | Areas | State |
| --- | --- | --- |
| First | Phonics and blending, handwriting, practical math, spelling, copying a sentence | This spec |
| Second | Map reading | Shipped in #830 |
| Second | Memory work and recitation | This spec, §8, with firm limits |

Phonics and handwriting come first because spelling and composition stand on
them: spelling at this age is phonics run in reverse, and copying a sentence
needs letters a child can form.

It is practice inside lessons Bede already teaches, not a new subject. A round
takes about five minutes.

## 2. What already exists, and is reused

Nothing here starts from scratch. Each area below plugs into pieces already in
the code.

| Piece | Where | Used for |
| --- | --- | --- |
| The routine screen | `homeschool-tutor/src/components/routine/RoutineShell.tsx` | The Watch, Together, Your turn frame for every area. It holds no lesson logic. |
| Lessons built by code and rebuilt from a signed id | `homeschool-api/services/map_practice.py`, `routers/map_practice.py` | The model for every area's builder and routes. Nothing about a lesson is stored. |
| Spoken answers matched only to offered choices | `map_practice.match_spoken` | Voice answers in every area. |
| Practice pictures, drawn as SVG from numbers and short labels | `services/practice/diagrams.py`, `components/Diagram.tsx` | Existing clock, money, ruler, number line, base-ten, array and picture-group pictures. Practical math's counters and ten-frames use the separate `PieceDiagram` vocabulary and `MathPieces.tsx`. |
| Exact arithmetic | the math practice pack (`services/practice/packs/math/`) | Working out every math answer. |
| The work ledger | `services/diagnostic/activity.py`, `SkillActivityLog` | Recording what the child did. |
| K-2 phonics record | `services/diagnostic/phonics.py` (six domains, below) | Phonics evidence. |
| K-2 math skills | `services/diagnostic/skill_map.py` (24 K-2 skills, below) | Practical math evidence. |
| Spelling practice | `services/practice/packs/spelling/` (look-say-cover-write-check, `item_bank/patterns.json`) | The spelling routine and its words, after the K-2 additions in §5.4. |
| Writing canvas | `components/HandwritingCanvas.tsx` | Handwriting and copying a sentence: composition ruling, finger and stylus. |
| Speech | Bede's own voice (`useTextToSpeech`, the server's `/tutor/speak`), the same as the chat | Every instruction is spoken in the voice the child already knows (owner direction 2026-11-18). |
| The invitation pattern | `invite_map_practice` in `services/ai_service.py` and `services/tool_registry.py` | How Bede offers a round (§4). |

## 3. The routine

Every area runs the same three steps, so a five-year-old learns the routine once.

| Step | What happens | Records |
| --- | --- | --- |
| **Watch** | Bede demonstrates one example: an animation, with every word read aloud. The child only watches. | Nothing. |
| **Together** | Two items with the model still visible and hints on screen. A miss shows the answer straight away. | Nothing. |
| **Your turn** | Three new items with no hints. Two tries; then the answer is shown and the child moves on. Bede never says "wrong": it shows the move again. | See below. |

These counts match map practice (`TOGETHER_TASKS = 2`, `YOUR_TURN_TASKS = 3`),
which is deliberate: the same rhythm everywhere.

**What a round records.** Watching and Together record nothing. A Your turn item
answered correctly writes one work-ledger row: unaided on the first try, "after a
nudge" on the second. An item that ended with the answer shown writes nothing,
the same rule the ledger already keeps for a miss. Whether a Your turn item also
feeds a mastery estimate is set per area in §5. A question claims its row once,
so a retried submission cannot record twice. This is the same idea as the turn
id in `docs/RELIABILITY.md`.

**Checked by code.** Every item and every answer comes from a server builder,
the same way map practice works. No model writes an item, decides whether an
answer is right, or sees anything the child does in a round. So practice keeps
working when the AI provider is down, and nothing from a round leaves the
household. This follows the owner's v1.0 ruling that child-level learning
content stays local (`docs/DECISIONS.md`, v1.0 reconciliation, entries 20 and
39).

## 4. How a round starts

**Bede offers it.** This is the main way in. A fixed rule on the server decides
whether an offer is allowed; the model only chooses the moment. Allowed when:

| Trigger | Example |
| --- | --- |
| A parent-approved practice set is due | A spelling re-check three days after a quiz |
| The child needed help on the same skill several times in the ledger | Counters for number bonds instead of asking again in words |
| A skill has not been practised for a while | A telling-time round after a long gap |
| The lesson reaches a natural moment | The child has just told a story back, so Bede offers to copy a sentence from it |

**Limits, checked when the prompt is built and again when the tool is
dispatched**, the way `_map_practice_allowed` does it:

- K-2 only (`GradeStage.foundations`). The lesson invitation remains unavailable
  in the public demo; Number Time, Sound Time and Map Practice have their own
  direct demo actions (§5.3).
- Only in the subjects that area belongs to (§5), and only if the parent scheduled that subject today. A parent's own lesson focus comes first.
- At most one offer per area per session. Never when too little time is left on the block to finish a round (`time_remaining_seconds`, the same budget `services/action_governance.py` uses).
- It is an invitation ("Shall I show you with the counters?"). The child can say not now, the lesson carries on, and declining records nothing.
- A per-child parent setting with three choices: off; only practice sets I approved; or Bede may also choose from today's subjects. The default is the third (decision 40(a), owner ruling 2026-11-16), with three limits: Bede picks only from subjects already in that child's routine today and only from authored content, never inventing a word or an item; the parent sees each offer, as the server-written card in the conversation, and can switch it off with one tap per child; and practice sets made from uploaded quizzes still need the parent's approval. "Only practice sets I approved" never lets Bede choose on its own; step 1 has no approved phonics sets, so it offers no phonics.
- A parent's own lesson focus comes first. This is prompt guidance, not a server gate: the invitation note tells Bede not to offer practice when today's lesson focus or the subject's "where we left off" note points elsewhere.

**The tool.** One `invite_practice` tool with a closed `area` field (`phonics`,
`handwriting`, `math`, `spelling`, `copy_sentence`). The card and its wording
are written by the server per locale, never by the model, the same as
`invite_map_practice`'s card. `invite_map_practice` stays as it is; it is not
renamed or folded in, so nothing that already works changes.

**Other ways in.** A parent can tap "5-minute practice" on the dashboard, and an
approved practice set can be delivered as a round instead of today's text box.

## 5. The first-wave areas

Each area lists its grade levels, what each step does, how the child answers,
and what it records. Grades stay distinct, as map practice keeps them: a child
gets the level for the grade saved in Parent Setup, never one chosen in the
request.

### 5.1 Phonics and blending

**Subjects:** Language Arts and Living Books.

**Skills:** the existing phonics domains, in their existing order:
`phonological_awareness`, `letter_sound`, `cvc_blending`, `blends_digraphs`,
`long_vowel_patterns`, `sight_words`. K starts at the first, grade 1 at
`cvc_blending`, grade 2 at `blends_digraphs`. The next domain follows the
same developmental order `phonics.py`'s summary already walks.

- **Watch:** a word's letters appear one at a time, each lighting up as Bede says its sound, then slide together while Bede blends them.
- **Together:** the same with a new word. The child taps each letter to hear it, then taps the picture that matches the blended word.
- **Your turn:** new words, no sound on tap. The child picks the matching picture, or the letter for a first sound.

**Answers:** a tap on one of the offered pictures or letters. A spoken answer
counts only when it matches one of those choices, exactly as `match_spoken` does
for maps. Speech recognition is not accurate enough to judge a young child's
sounds, so Bede never judges pronunciation.

**Words and pictures:** a fixed, authored list of decodable words per domain,
each with a picture from the existing practice icon set (`models/practice.py`'s
`ICONS`) or a small addition to it. Nothing is generated.

**Records:** a work-ledger row as in §3, and a phonics observation through
`services/diagnostic/phonics.py`'s `process_evidence`, which now takes the same
`weight` argument `literacy.process_evidence` has (a caller that passes none
behaves as before). The weights are decision 40(b), ruled by the owner on
2026-11-16. They are product defaults the owner chose, not research-backed
values:

| Your turn answer | Ledger row | Phonics observation weight |
| --- | --- | --- |
| Right on the first try | one, unaided | 0.5 (`QUIZ_EVIDENCE_WEIGHT`) |
| Right on the second try | one, with a hint | 0.25 |
| Answer shown, or the round left | none | none |

A missed try is never an observation of its own, so the estimate moves only on
a right answer. Practice answers move the estimate by their weight alone, without the early-evidence boost Bede's in-lesson check-ins get, by owner ruling 2026-11-16: from a fresh start one right first try takes a domain from 0.5 to 0.75, a second to 0.875 (secure), and one right second try to 0.625. Only right answers count, so guessing can still raise the estimate, but from a fresh record, no single practice answer can make a skill secure; two right first tries can. With `RETAIN_MASTERY_PROFILES` off, only the ledger row is
written. This is the phonics record Bede already keeps; it gains a practice
source, not a new skill.

**Two more owner rulings (2026-11-16, product defaults).** Practice answers do not count
toward the early-evidence window: they move the estimate by their weight but do not advance
`evidence_count`, so Bede's own in-lesson check-ins keep the full early boost and the
parent's summary stays "calibrating" until enough check-ins exist. And one round is recorded
per area per sign-in, with at most three recorded answers; "Another one" still works and
records nothing. A round counts once its first answer is recorded, not when it is served:
opening a round and leaving, a lost response followed by "Try again", or a round that needs
sound on a device that cannot give it leaves the sign-in's round unused, and if two rounds
are answered at once only one is recorded. The server keys this on the learner, the area and
a digest of the sign-in's token, so a reload or a new lesson id does not reset it and a new
sign-in does; it is held in memory, so a server restart forgets it. Progress tells the parent
of a K-2 child whose practice is not off that the extra rounds were practice only, and while
the reading picture is still calibrating it names the practice answers apart from Bede's own
lesson check-ins ("0 lesson check-ins so far, plus 3 practice answers"), so the line never
reads as though nothing had been recorded.

**Limitations of the record (product defaults, no research behind any number here).** A child tapping at random still ends up "correct" within two tries this often:

| Choices | Repeats possible | No repeats |
| --- | --- | --- |
| 3 | 56% | 67% |
| 4 | 44% | 50% |

In Bede as built, a wrongly tapped choice stays tappable on the second try (the screen re-enables every choice and the server accepts the same choice again as the second miss), so the "repeats possible" column is what the code does; the owner treats "no repeats" as the realistic case either way. Kindergarten and grade 1 get three choices, grade 2 four. The one-recorded-round cap bounds this to three recorded answers per area per sign-in, and the record only picks the next practice domain, never a placement or a label.

Negative evidence for an item that ended with the answer shown is decision 40(h), open.

**Built (step 1).** `services/k2_practice/phonics.py` builds a lesson from
(level, domain, seed) with an authored word list per domain; the level comes
from the saved grade and the domain from the saved phonics record, never from
the request. `routers/k2_practice.py` serves it under a signed lesson id. The
screen is `components/K2PhonicsPractice.tsx` inside `RoutineShell`. In "Your
turn", where reading the word is the skill, neither the word nor the letters'
sounds are sent, so narration cannot give the answer away. The words are
English phonics; in a Spanish session the instructions are Spanish and the
words stay English. Answering by voice inside the screen is not built; the
server accepts a spoken answer and counts it only when it matches one offered
choice.

### 5.2 Handwriting (letter formation)

**Subjects:** Language Arts.

**Levels:** K, lowercase and uppercase letter forms and numerals 0-9; grade 1,
all letters, with spacing between letters; grade 2, words with even size and
spacing.

- **Watch:** an animated pen draws the letter stroke by stroke on handwriting lines, while Bede describes each stroke ("start at the top, pull down").
- **Together:** the child traces over a faint copy with the start point and direction shown.
- **Your turn:** the copy hides and the child writes the letter alone, then reveals the model and compares.

**Checking:** none by Bede. The child compares their letter with the model. This
is how copywork has always been corrected, and it keeps a child's handwriting
from being sent anywhere (§3). Handwriting is never scored, marked or judged.

**Stroke data:** authored for this repository as plain stroke paths per letter.
The style is decision 40(c), because families use different handwriting programs
and Bede should not teach a different form from the one at home.

**Records:** a ledger row that the round was done (unaided), and nothing else. No
mastery estimate, no quality score.

### 5.3 Practical math

**Subjects:** Mathematics.

**Skills:** the existing K-2 skills in `skill_map.py`. No new skill ids. The ones
practice uses first:

| Piece | Skills |
| --- | --- |
| Counters and ten-frame | `cc.count_objects_20`, `cc.compare_quantities`, `oa.add_within_20`, `oa.subtract_within_20` |
| Number bonds | `cc.number_bonds`, `oa.fact_fluency_20` |
| Base-ten blocks | `nbt.place_value_tens`, `nbt.add_within_100`, `nbt.subtract_within_100` |
| Number-line hops | `cc.skip_count_2_5_10`, `oa.add_within_20` |
| Clock hands | `md.tell_time` |
| Coins and bills | `md.money` |
| Ruler | `md.measure_length` |
| Equal groups | `oa.arrays_equal_groups`, `oa.even_odd` |
| Everyday stories | `oa.one_step_word_problems`: setting the table, sharing snacks, a small shop, what time lunch is |

- **Watch:** Bede moves the pieces to show one problem, saying each step.
- **Together:** the child drags the pieces, such as counters into a ten-frame or a clock's hands, with the target faintly shown.
- **Your turn:** a new problem with no target shown.

**Pictures:** clock, money, ruler, number line, base-ten, array and picture
groups already exist as diagram kinds. Counters, a ten-frame and a number bond
are new kinds, added to `diagrams.py`'s closed vocabulary in the same way. Every
piece is draggable with a large touch target, and has a tap-only alternative.

**Answers:** computed with the math pack's exact evaluator. A word problem's
numbers come from the builder, never from a model.

**Records:** a ledger row as in §3, and an observation for the skill through the
existing math evidence path (`process_evidence`'s `confidence`, in
`services/diagnostic/__init__.py`) at a reduced weight, the same approach `QUIZ_EVIDENCE_WEIGHT`
(`services/practice/evidence.py`) takes for a marked quiz (decision 40(b)).

**Built (step 3, first part).** `services/k2_practice/practical_math.py` builds a
lesson from (level, topic, seed). Five topics, each one existing K-2 skill:

| Topic | Skill | Pieces |
| --- | --- | --- |
| count | `cc.count_objects_20` | counters to count; a ten-frame to fill to a number |
| compare | `cc.compare_quantities` | two rows of counters: more red, more yellow, or the same |
| add | `oa.add_within_20` | a ten-frame (two past ten) with red and yellow counters |
| subtract | `oa.subtract_within_20` | a ten-frame with some counters crossed out or taken away |
| bond | `cc.number_bonds` | a number bond with one part missing |

Kindergarten walks count, compare, bond, add, subtract; grade 1 add, subtract,
bond, compare; grade 2 add, subtract, bond, with numbers past ten on two
ten-frames. The level is the saved grade and the topic the first whose skill the
saved math record does not show as secure, in that order, never anything in the
request. Every topic but compare has a building question in Watch, Together and
Your turn: the frame starts with some counters and the answer is how many are on
it when the child taps **Check**. Counters move three ways, so dragging is never
the only one: drag a counter from the tray onto the frame or off it; tap a box;
or tap the large **Put in a counter** and **Take one out** buttons. The other
questions are a tap on a number or on which row has more.

Every answer is worked out twice, by the math pack's exact evaluator on the
question's arithmetic and by counting the picture (`diagrams.answer`), and a
question where the two disagree is never built. The child's answer is a tap, a
count on the frame (itself one of the offered choices), or speech matched to
exactly one offered choice; nothing typed is accepted or kept, and the answer
model refuses any extra field. `match_spoken` has its own English and Spanish
table for numbers, quantities ("the same", "iguales") and clock times ("ten
thirty", "diez y media"), where a longer phrase wins over a shorter one inside
it, so "ten thirty" names 10:30 and not 10:00. A question whose spoken
instruction says its own answer ("Put 7 counters in the ten-frame") takes no
spoken answer. Answering by voice inside the screen is not built, as for
phonics; the server accepts a spoken answer.

Speech is exactly as for phonics (§7): every line is shown and spoken in
Bede's own voice, and Bede's chat voice does not read the turn over a round it
opened. No math question works only by ear, so with Bede's voice off the child
gets the same lesson, shown without speech.

The three new pictures are `counters`, `ten_frame` and `number_bond`
(`models/practice.py`'s `PieceDiagram`, drawn by `components/MathPieces.tsx`):
numbers and two counter colors only, a red counter solid and a yellow one a
ring. They are a sibling vocabulary rather than members of `Diagram`:
`Diagram` is what a quiz reader or drafter may emit, and every kind in it must
be drawn by `Diagram.tsx`, whose app/demo copies stay mirrored. Number Time
uses `MathPieces.tsx` in both the app and public demo, so this practice activity
does not add kinds to that separate contract.

**Public demo.** A demo visitor can open Number Time from its own action and
select any implemented topic, without a learner profile or a claim about saved
mastery. The server resolves the level from the live demo session's validated
K-2 grade (or its configured K-2 default); the visitor cannot override it.
The demo uses the same authored builders, pictures, and deterministic answer
checks as the family activity. Every answer response says `demo=true` and
`recorded=false`: answers and attempts are temporary, with no writes to
household `StudentConfig`, learner keys, work-ledger, mastery, or demo
progress/activity stores, and no AI/model calls. Demo lesson ids are separate
from family practice ids, bound to the live sign-in and no longer than its
expiry. If the in-memory attempt state disappears on restart, that lesson is
refused and the visitor can start another round; attempts are never reset by
rebuilding the lesson from an old id. This support does not enable
`invite_practice` in demo tutoring turns.

Sound Time and Map Practice joined the demo on 2026-11-19 at the owner's
request, under the same boundary (`services/k2_practice/demo_rounds.py`): the
household builders and checks, level from the live demo session's K-2 grade,
attempts held in a bounded in-memory store for no longer than the sign-in (at
most 15 minutes), `demo=true` and `recorded=false` on every answer, and no
model calls. Every round speaks only in Bede's own voice, the chat's
text-to-speech path, never the browser's or an on-device voice.

The demo's screens and wire types are mirrored under `demo/src/` so the demo
builds with its own dependency tree; `demo/src/k2MathParity.test.ts` checks those
copies against the household implementation. Decision 40(g) records the
approval and boundary.

Which skill an answer counts for (owner ruling 2026-11-16, a product
default): **a building question records counting only.** Putting the right
number of counters on a ten-frame, whether the question was framed as adding,
taking away, a number bond or a plain count, is evidence for
`cc.count_objects_20` and nothing else, because the frame does the arithmetic
for anyone who counts the boxes. It never moves the addition, subtraction,
comparison or number-bond estimate. A question where the child picks the
answer from the choices (how many in all, how many are left, the missing part,
which row has more) records the topic's own skill. The ledger row names the
skill recorded (`practical_math.recorded_skill`).

What a Your turn answer records follows phonics exactly (decision 40(b) and
the two later rulings): right first try, a ledger row (unaided) and an
observation for the recorded skill at `confidence` 0.5; right second try, a
ledger row (with a hint) at 0.25; answer shown, nothing. The observation goes
through `process_evidence` with `skip_calibration_boost=True` and
`count_toward_calibration=False`, two keyword arguments only this route passes,
so it never gets the early-evidence boost and never advances `evidence_count`;
Bede's own `record_skill_evidence` check-ins and marked quizzes behave exactly
as before. With `RETAIN_MASTERY_PROFILES` off only the ledger row is written.
One round is recorded per area per sign-in, so a child's Number Time round and
Sound Time round are counted apart, each at most three answers. The math
summary's `practice_answers` counts the practice rows apart from check-ins, as
phonics does.

Sizes are in rem, as for phonics. A ten-frame is five boxes across, and on a
phone with larger text five boxes no longer fit: squeezed into five columns
they overlapped, so a tap could land on the wrong box. When five boxes do not
fit, the frame turns on its side instead, two boxes across and five down,
filled down the first column and then the second, so it is still two fives.
The switch is a CSS container query in rem on the frame's own wrapper
(`MathPieces.tsx`'s `FRAME_CONTAINER`, `BUILD_FRAME_GRID`,
`PICTURE_FRAME_GRID`), so it follows the app's own text-size control, which a
viewport breakpoint would not. Measured in real Chromium (Playwright, a
harness rendering the frames inside the real `RoutineShell`): at 375 px wide
and 100%, 125%, 150%, 175% and 200% text, and at 820 px wide at the same
sizes, with one and with two frames, no box overlaps another, none is off
screen, the round never scrolls sideways, every box of the frame the child
fills is at least 3.5rem square and 8 px from its neighbours, and a tap at the
centre of each box reaches that box. At 375 px the frame the child fills turns
on its side from 125% and the picture of a frame from 150%; at 820 px both
stay five across up to 200%. With the query removed the same check found
overlapping boxes from 125% and boxes off screen at 175% and 200%.

In Your turn, a picture's accessible name never states the quantity being
asked for (the echo rule applied to screen readers): a row is "a row of red
counters" and a frame "a ten-frame with counters", where Watch and Together
name the counts. On a Together take-away question the counters to take away
are outlined, since the boxes below the target start full and an outline of
empty boxes would show nothing.

Not built yet, and next: clock hands, coins and bills, number-line hops, the
ruler, base-ten blocks, equal groups and everyday stories. These activities
are not part of the public demo. `oa.fact_fluency_20`
is deliberately not recorded: fluency means recalling a fact quickly, and a
round has no timer and must not have one (§6), so a right answer here says
nothing about speed. The spoken-forms table already covers clock times, so the
clock can use it as it stands.

### 5.4 Spelling

**Subjects:** Language Arts.

**Levels:** K, short CVC words drawn from the phonics domains the child has
practised; grade 1, blends, digraphs and silent e; grade 2, vowel teams and
common endings. These are the K-2 end of the pattern bank. The current bank
(`item_bank/patterns.json`) is pitched at grade 3 and up, so K-2 patterns are
added to it, authored for this repository.

The existing look-say-cover-write-check, turned into something the child does:

1. **Look:** the word appears and Bede says it, lighting up each sound (the same animation as phonics).
2. **Build:** the child drags letter tiles to make the word, with the word visible. This is Together.
3. **Cover and build:** the word hides and the child builds it from memory, with tiles or on the canvas. This is Your turn.
4. **Check:** the child uncovers the word and compares it themselves.

**Words come from:** a list the parent approves, words missed on a quiz the
parent uploaded (Practice Coach), or the pattern bank. Approval is decision
40(d).

**Records:** a ledger row as in §3. Bede has no K-2 spelling estimate today;
whether to add one is decision 40(e). The recommendation is the ledger only for
now, with a measured K-2 spelling skill added later as its own reviewed change,
since a skill id is permanent once stored.

### 5.5 Copying a sentence (early composition)

**Subjects:** Language Arts, Living Books, History and Nature Study, wherever the
child has just told something back.

At this age composition is telling, then writing one sentence.

1. **Watch:** right after a narration, Bede shows one sentence of the child's own words on ruled lines and reads it aloud. The sentence comes from what the child just said in the chat, so nothing new is collected.
2. **Together:** the child traces the sentence, then copies it underneath with the model visible.
3. **Your turn**, by grade:
   - K: draw what happened and copy one word from the sentence.
   - Grade 1: copy the sentence, then add one sentence of their own.
   - Grade 2: add two or three sentences of their own.

**Checking:** the child compares their copy with the model, the same as
handwriting. Bede may name one thing to look for before the child starts ("a
capital at the start, a full stop at the end"), from a fixed list per grade. It
never marks the result.

**Records:** a ledger row that the round was done, and nothing else. The child's
own added sentences stay on the canvas page, which `utils/canvasPersistence.ts`
already keeps for the tab only.

## 6. Rules every area keeps

- **No pressure.** No timer, speed, score, streak or leaderboard is shown to the child. The standing rule never to hurry a child applies (`_WORK_SCORING_NOTE`).
- **Honest record.** Only what is in §3 and each area's "Records". A blank is never shown as a low mark.
- **The parent decides.** Parents approve word lists and practice sets before a child sees them, choose the setting in §4, and see every ledger row on Progress. A child never sees a record of their own practice.
- **What helps this child applies.** A child's `learning_support` and reading settings carry into the round. For example, tiles instead of writing for a child who answers better that way, and the letter and line spacing the parent set.
- **Accessible.** 56 px touch targets, 64 px for the main action, 8 px apart; usable at 200% text; every instruction spoken and shown, motion that respects `prefers-reduced-motion`, and English and Spanish from the start, with the same keys in both locale files.
- **Private.** No real places, as map practice already rules. No free text is kept from a round. Nothing the child gives in a round goes to any AI provider. A round's own fixed lines are spoken in Bede's voice, which sends that text to the configured speech provider (§7).
- **Reliable.** A lesson rebuilds from its signed id, a reload resumes it, a retried answer counts once, and every check runs without an AI call.
- **Never faith.** No area records anything about prayer, Scripture or devotional text. See §8.

## 7. Animation and voice

**Animation:** there is no animation library in the app, and none is added. Every
animation is SVG moved with CSS transitions or the Web Animations API, driven by
the same data the builder returns, so the demonstration and the answer can never
disagree. With `prefers-reduced-motion`, each step appears in place with no
movement.

**Voice:** every line Bede speaks in a round is written by the server per locale,
like the map practice card.

**Every round speaks in Bede's own voice (owner direction 2026-11-18).** Rounds
used to speak through a voice installed on the device, so that nothing from a
round reached a provider. That voice sounded unlike Bede, so a child heard one
voice in the chat and a different one in the round. Sound Time, Number Time
and Map Practice now speak through the same `useTextToSpeech` path as a chat
reply, in the app and in the demo, and stop speaking when the child closes
them, with the chat's rules: a browser voice only when no speech
provider is configured at all, and silence rather than another voice when one
is configured but a line fails. They default to no other voice, and no shipped
file outside `useTextToSpeech` may speak through the browser directly or
request `/tutor/speak` itself (`bedesVoiceOnly.test.ts`). The rule holds for
every feature, including ones added later (Practice Coach speaks nothing
today; if it ever does, it speaks in Bede's voice): in the chat, every
practice screen that speaks is handed the one Bede-voice callback, and the
same test fails if a screen is wired to anything else.

What this sends to the speech provider is the round's fixed, server-written
lines: the instruction, the worked example, a letter's sound when it is tapped,
and "That's it" or "Let's look again". It never sends the child's taps or
spoken answers, but the feedback line spoken does show whether an answer was
right. With Bede's voice turned off, the round is shown without speech, and the
items that only work by ear (sight words) are not served or recorded; a child
whose practice is sight words is told it needs sound. Bede's chat voice does
not read the turn over a round it opened. A spoken answer is transcribed by the
existing voice pipeline and counts only when it matches one of the item's own
choices, and never when the spoken instruction already said the answer (a sight
word), since repeating it is an echo rather than a reading.
`SocraticChat.k2Practice.test.tsx` and the demo's `k2MathParity.test.ts` pin the
wiring.

## 8. Second wave

**Map reading** is built (#830). What remains is listed in `docs/MAP_PRACTICE.md`
under "Not built": answering by voice inside the screen, and the public demo.

**Memory work and recitation** (poems, math facts, short passages): Bede says a
line, the child echoes it, then says it from memory. Two firm limits:

1. **Never marked.** Speech recognition cannot judge a young child's recitation, so Bede recites alongside and never decides whether it was right.
2. **Nothing recorded for anything devotional.** Prayers, Scripture and hymns record nothing at all, not even a ledger row, because the constitution forbids measuring a child's spiritual life. Bede only recites alongside. Math-fact chants may write a ledger row; poems are decision 40(f).

## 9. Build order

Each step is its own PR, with tests that fail when the behavior is broken, and
the docs updated in the same PR.

1. **The shared invitation and phonics.** `invite_practice` with its server-side limits and the parent setting (§4), and the phonics area (§5.1) in `RoutineShell`. *Built.* Its 200% layout is pinned in this step by a class contract (rem sizes, no fixed widths); the real 200% browser check is step 6.
2. **Handwriting** (§5.2): stroke data for the chosen style, the animated pen, and tracing guides on the canvas.
3. **Practical math** (§5.3): counters, ten-frame and number bonds first, then clock, coins, number line and ruler. *Counters, ten-frame and number bonds built*, before step 2, which waits on decision 40(c); clock, coins, number line and ruler are next.
4. **Spelling** (§5.4): the K-2 patterns, letter tiles, and delivery of approved word lists and Practice Coach misses as rounds.
5. **Copying a sentence** (§5.5): the sentence from the narration, tracing and copying on the canvas.
6. **The parent "5-minute practice" button**, and browser-journey checks for touch dragging and 200% text on every area.
7. **Memory work** (§8), once decision 40(f) is settled.

Each step needs no new database table: household rounds rebuild from signed
ids, and records go to the existing work ledger and evidence paths. Demo
Number Time, Sound Time and Map Practice use separate bounded in-memory
attempt stores and record nothing.

## 10. Not in scope

- The `invite_practice` offer in the public demo. Demo Number Time, Sound
  Time and Map Practice open from their own actions (decision 40(g)); other
  areas join the demo as each is built.
- Grade 3 and up, which have their own reading and spelling record (`services/diagnostic/literacy.py`).
- Any score of handwriting quality, recitation, or a child's response to art, music or faith.
- Any model-written practice item, or a model judging a child's answer.

## 11. Decisions

The UX baseline every area is held to is [`K2_UX_CHECKLIST.md`](K2_UX_CHECKLIST.md),
with the owner's rulings on where it met Bede as built in `docs/DECISIONS.md`
entry 42.

The choices this spec leaves open are recorded as `docs/DECISIONS.md` entry 40,
with a recommendation for each:

- **(a)** the default of the per-child setting in §4 (ruled 2026-11-16: Bede may also choose from today's subjects, with the limits in §4);
- **(b)** the weight of practice evidence in the phonics and math estimates (ruled 2026-11-16: 0.5, 0.25, and nothing for an answer shown; applied to phonics in step 1, §5.1, and to math in step 3, §5.3);
- **(c)** the handwriting style;
- **(d)** how parents approve word lists;
- **(e)** whether K-2 spelling gets a measured skill;
- **(f)** whether poems in memory work record anything;
- **(g)** whether the demo gets practice (decided 2026-11-17; see entry 40).
- **(h)** whether an item that ends with the answer shown records weak negative evidence (recommended; a small separate PR).
