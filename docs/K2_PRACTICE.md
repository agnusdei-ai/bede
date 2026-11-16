# K-2 practice: Watch, Together, Your turn

**Status: specification.** The first wave below is not built. Map reading, from
the second wave, shipped in #830 (`docs/MAP_PRACTICE.md`) and set the pattern
this spec follows. The decisions this spec cannot make for itself are
`docs/DECISIONS.md` entry 40; where they are referred to below, the entry is the
one place their answers will live.

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
| Practice pictures, drawn as SVG from numbers and short labels | `services/practice/diagrams.py`, `components/Diagram.tsx` | Clock, money, ruler, number line, base-ten, array and picture groups for practical math. |
| Exact arithmetic | the math practice pack (`services/practice/packs/math/`) | Working out every math answer. |
| The work ledger | `services/diagnostic/activity.py`, `SkillActivityLog` | Recording what the child did. |
| K-2 phonics record | `services/diagnostic/phonics.py` (six domains, below) | Phonics evidence. |
| K-2 math skills | `services/diagnostic/skill_map.py` (24 K-2 skills, below) | Practical math evidence. |
| Spelling practice | `services/practice/packs/spelling/` (look-say-cover-write-check, `item_bank/patterns.json`) | The spelling routine and its words, after the K-2 additions in §5.4. |
| Writing canvas | `components/HandwritingCanvas.tsx` | Handwriting and copying a sentence: composition ruling, finger and stylus. |
| Speech | `hooks/useTextToSpeech.ts`, the server's speech synthesis | Speaking every instruction. |
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

- K-2 only (`GradeStage.foundations`), never in the public demo.
- Only in the subjects that area belongs to (§5), and only if the parent scheduled that subject today. A parent's own lesson focus comes first.
- At most one offer per area per session. Never when too little time is left on the block to finish a round (`time_remaining_seconds`, the same budget `services/action_governance.py` uses).
- It is an invitation ("Shall I show you with the counters?"). The child can say not now, the lesson carries on, and declining records nothing.
- A per-child parent setting with three choices: off; only practice sets I approved; or Bede may also choose from today's subjects. The default is decision 40(a).

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
`services/diagnostic/phonics.py`'s `process_evidence` at a reduced weight
(decision 40(b)). That function takes no weight today; it gains the same
`weight` argument `literacy.process_evidence` already has. This is the phonics
record Bede already keeps; it gains a practice source, not a new skill.

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
- **Private.** No real places, as map practice already rules. No free text is kept from a round. Nothing from a round goes to any AI provider.
- **Reliable.** A lesson rebuilds from its signed id, a reload resumes it, a retried answer counts once, and every check runs without an AI call.
- **Never faith.** No area records anything about prayer, Scripture or devotional text. See §8.

## 7. Animation and voice

**Animation:** there is no animation library in the app, and none is added. Every
animation is SVG moved with CSS transitions or the Web Animations API, driven by
the same data the builder returns, so the demonstration and the answer can never
disagree. With `prefers-reduced-motion`, each step appears in place with no
movement.

**Voice:** every line Bede speaks in a round is written by the server per locale,
like the map practice card, and spoken through the existing speech path. A
spoken answer is transcribed by the existing voice pipeline and counts only when
it matches one of the item's own choices.

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

1. **The shared invitation and phonics.** `invite_practice` with its server-side limits and the parent setting (§4), and the phonics area (§5.1) in `RoutineShell`.
2. **Handwriting** (§5.2): stroke data for the chosen style, the animated pen, and tracing guides on the canvas.
3. **Practical math** (§5.3): counters, ten-frame and number bonds first, then clock, coins, number line and ruler.
4. **Spelling** (§5.4): the K-2 patterns, letter tiles, and delivery of approved word lists and Practice Coach misses as rounds.
5. **Copying a sentence** (§5.5): the sentence from the narration, tracing and copying on the canvas.
6. **The parent "5-minute practice" button**, and browser-journey checks for touch dragging and 175% text on every area.
7. **Memory work** (§8), once decision 40(f) is settled.

Each step needs no new database table: rounds rebuild from signed ids, and
records go to the existing work ledger and evidence paths.

## 10. Not in scope

- The public demo. Changes there need the owner's sign-off (decision 40(g)).
- Grade 3 and up, which have their own reading and spelling record (`services/diagnostic/literacy.py`).
- Any score of handwriting quality, recitation, or a child's response to art, music or faith.
- Any model-written practice item, or a model judging a child's answer.

## 11. Decisions

The UX baseline every area is held to is [`K2_UX_CHECKLIST.md`](K2_UX_CHECKLIST.md),
with the owner's rulings on where it met Bede as built in `docs/DECISIONS.md`
entry 42.

The choices this spec leaves open are recorded as `docs/DECISIONS.md` entry 40,
with a recommendation for each:

- **(a)** the default of the per-child setting in §4;
- **(b)** the weight of practice evidence in the phonics and math estimates;
- **(c)** the handwriting style;
- **(d)** how parents approve word lists;
- **(e)** whether K-2 spelling gets a measured skill;
- **(f)** whether poems in memory work record anything;
- **(g)** whether the demo gets practice.
