# Practice Coach

A parent photographs a graded quiz, test or worksheet. Bede reads it, works
out *why* each miss happened, and drafts a short practice set and a follow-up
re-check. **The parent reviews and approves everything before the child sees
it.** The ruling behind each design choice is `docs/DECISIONS.md` entry 39.

## What it is not

Bede is not an assessment platform. It never assigns a grade, never keeps a
score of its own, and never reports to a school. The "12 of 13" a parent sees
is the **teacher's** count, read off the page and labelled as such.

## How it works

1. **Read.** The parent uploads up to six JPEG or PNG pages. They are sent to
   the model the same way the handwriting canvas sends a child's drawing, as
   base64 image blocks, and come back as a structured reading: sections,
   instructions, word banks, each item's prompt, the child's answer, the
   teacher's mark, and any correction the teacher wrote.
2. **Confirm.** Anything the reader was unsure of is flagged with what is
   uncertain ("the macron on the ī is unclear"). Nothing flagged is diagnosed
   until the parent settles it. A quiz can also be typed in by hand.
3. **Diagnose.** Deterministic rules, not the model, decide what each miss
   means. Core checks apply to every subject and report to the parent only:
   - **answer format**: answers didn't take the form the instructions asked
     for (single words where sentences were asked);
   - **unanswered**: an item left blank and not marked correct. An item the
     teacher marked correct is never called unanswered. A colour circle left
     white for *alba* is the answer, not a blank;
   - **worth a look**: an unmarked answer that doesn't match the word bank.

   Then the subject pack explains each miss the teacher marked, and names
   what was solid.
4. **Plan.** The pack drafts about 5–10 minutes of practice on the *pattern*.
   It uses new scenes, never the missed item again, and only words the child
   has already met in that worksheet's word banks. It ends with a short
   retrieval check and schedules re-checks at +3 and +7 days.
5. **Approve.** The parent sees a summary, the diagnosis, the practice set
   and a script for hints. They approve it (optionally with edits) or discard
   it. A decided set can't be changed again.

The parent's screen is the **Practice from a graded quiz** card on each
student's Progress page (`homeschool-tutor/src/components/PracticeCoach.tsx`);
`docs/PARENT_SETUP.md` §5 walks a parent through it. Delivery to the child,
the re-checks themselves, and pattern history arrive in later pull requests
(see "Build order" below).

## Where the photos go

The photos are read in one of two places:

- **On the household's own model**, when one is configured. This is the
  default, and it never falls back to a cloud provider.
- **On the household's configured cloud AI provider**, only when the parent
  confirms it for that upload. Without that confirmation the request is
  refused before anything is sent, and the response names the provider.

`GET /practice/reading-route` tells the parent which applies before they
upload.

The photos exist only inside the request that reads them. They are never
written to the database, a file or a log. The reading has **no field** for a
name, school, teacher or date, so a reading that includes one is rejected
rather than stored. Readings and practice sets are encrypted with the
student's own key and are removed when the student is deleted.

Not on the public demo: these routes are parent-only.

## Subject packs

The core never changes when a subject is added. A pack is a folder under
`homeschool-api/services/practice/packs/`:

| File | Purpose |
|---|---|
| `manifest.json` | id, name, grade bands, which categories it detects automatically |
| `taxonomy.json` | every error category, each with a `remediation_strategy`, plus the strengths it can name |
| `extract_hints.md` | what to look for when reading this subject's worksheets |
| `item_bank/` | curated meanings and relations; never a source of new vocabulary |
| `golden/` | hand-typed fixtures, never real photos |
| `__init__.py` | `classify_errors`, `find_strengths`, `generate_practice` |

Register a new pack with one line in `packs/__init__.py`.

**Latin** detects five patterns:

- the general word for the specific one (*avis* for *anas*);
- a confusable pair from the bank;
- a word not in the bank;
- a macron the teacher marked;
- answering *what it is* when asked *what it is doing*.

Other categories (verb endings, noun cases, word order, translation
direction) are in the taxonomy so a parent can name them, but are not
detected yet.

## Golden tests

Golden test #1 is a parent's real graded Latin quiz, hand-typed into
`packs/latin/golden/latin_quiz_1.expected.json`. The photos are not in this
repository: they show a child's handwriting and a school's own worksheet.

- **In CI:** `tests/test_practice_coach.py` checks the diagnosis and practice
  from the typed file. Expected results:
  - item 5's *avis* for *anas* is diagnosed;
  - the full-sentence gap is reported to the parent only;
  - Alba is not flagged;
  - "vīta"'s unclear macron is not diagnosed;
  - every practice answer uses only words from the child's own banks.
- **By hand:** `homeschool-api/scripts/practice_golden_eval.py` checks the
  reading against the real photos on your own machine:

  ```
  python scripts/practice_golden_eval.py latin latin_quiz_1 page1.jpg page2.jpg [--cloud]
  ```

  It fails if any item is misread, and also if the reader is confident about
  "lentē" or "vīta", which the photos genuinely don't settle.

## Build order

1. **Done:** core pipeline, Latin pack, reading, confirm, diagnose, plan,
   approve, parent-only API.
2. **Done:** parent screens. Upload, review with flagged fields highlighted
   (planning is blocked until each is settled), approve with items removed,
   discard, printable worksheet, English and Spanish. Typing a quiz in by
   hand is available in the API but not yet on screen.
3. **Delivery to the child, inside an ordinary Bede session:** re-checks at
   +3/+7 days, mixed review of mastered items, pattern history recorded as
   events about the work, never labels about the child.
4. **Spelling pack**, built on the existing phonics (K-2) and
   reading-and-spelling (3-8) engines, and the optional game wrapper.
   Rewards count **days practised**, never streaks, and never speed.

**Not yet:** pages are not straightened or cropped before reading. That
needs an image library this backend doesn't carry, and the reader copes with
ordinary phone photos.
