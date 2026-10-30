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

1. **Read.** The parent uploads up to six pages as JPEG, PNG or iPhone HEIC
   photos, or as a PDF of scanned pages (each PDF page counts toward the six).
   Every file is first checked and rebuilt (see "File validation and
   hardening" below), and the rebuilt PNG pages are sent to
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

The photos are not saved to the database or a file by Bede; they are held in
memory while the request runs, and no temporary file is created (a test pins
that). Nothing from an upload is logged. The memory is released when the
request ends; Bede cannot promise anything about a model provider's own
retention once a parent has consented to a cloud read, which is why that
consent is asked per upload. The reading has **no field** for a
name, school, teacher or date, so a reading that includes one is rejected
rather than stored. Readings and practice sets are encrypted with the
student's own key and are removed when the student is deleted.

The real routes are parent-only and a demo visitor cannot reach them; the
public demo has its own, different copy (see "On the public demo" below).

## On the public demo

A visitor to the public demo can try the Practice Coach end to end from the
parent controls (gear menu, **Practice from a graded quiz...**). It is the same
reading, diagnosis and planning code, and the same upload hardening, with
these differences, each a decision and each pinned by
`tests/test_practice_demo.py`:

- **Its own routes and auth.** `/practice-demo/*`, demo-code sessions only
  (policy action `demo.practice`). A family session cannot use them and a demo
  code cannot reach `/practice`. The prefix is not `/practice/demo` because
  the real routes are `/practice/{student_name}/...`, and a child named
  "Demo" would otherwise be shadowed.
- **Nothing is stored.** No table, and no write to `practice_assessments` or
  `practice_sets`. The reading, the visitor's corrections and the draft
  practice set live in memory (`services/practice/demo_store.py`), keyed by the
  demo code, and are deleted on logout, by the sweep that clears the demo
  tables, and after 6 hours. The page itself is never held at all. Approving a
  set keeps nothing past the session, and the screen says so.
- **Always read by the demo's cloud provider, after a tick.** There is no
  local-model route. The visitor ticks a box naming the provider, for every
  upload; without it the request is refused (409) before any file is decoded
  and without spending the visitor's allowance. A backup provider may read
  the page if the first is unavailable, and the tick says so.
- **A small allowance, spent before the model is called.** 3 uploads of up to
  3 pages per demo code (a PDF counts each page), plus a process-wide ceiling of
  60 uploads an hour. An upload we refuse (a bad file, no provider) gives its
  slot back; one that reached the model does not. Over quota is a 429 and an
  `AuditEvent.RATE_LIMITED` entry with `detail=demo_practice_quota`. The counts
  are in memory, so a backend restart resets them; the hourly ceiling is the
  backstop.
- **Same gates as the real card.** A reading the reader was unsure of cannot be
  planned until each flagged answer is settled with **Looks right** (or
  corrected), items can be unticked before approving, the worksheet prints
  prompts only, and another quiz starts from nothing. The demo card
  (`demo/src/PracticeCoach.tsx`) is a mirror, not an import;
  `demo/src/practiceCoachParity.test.ts` checks it against the app's.
- **Not claimed:** the demo says nothing about delivery to a child or
  re-checks, which are not built even in the product.

## File validation and hardening

This is hardening, **not a guarantee that a file is free of malware**, and the
parent-facing text never says "virus-free". It is `services/practice/upload_safety.py`,
and it runs after the parent is authenticated and after consent and routing are
settled, before anything reaches a model.

- **Type comes from the bytes.** PNG, JPEG, HEIC/HEIF (`ftyp` brands `heic`,
  `heix`, `hevc`, `mif1`, `msf1`, `heif`) and PDF are recognised by their magic
  numbers only. The API receives no filename or content type for a page, and
  none is consulted.
- **Images are fully decoded and re-encoded** with Pillow (HEIC through
  pillow-heif and the libheif it bundles) into a fresh PNG: the pixel count is
  capped from the header before decoding (30 megapixels, 12,000 px a side),
  Pillow's own decompression-bomb warning is turned into an error, `verify()` is
  followed by a real reload, EXIF rotation is applied, and metadata plus anything
  appended after the image (a polyglot payload) does not survive. Pages are
  scaled down to 3,000 px a side.
- **PDFs are never rendered.** They are parsed with pypdf and refused if
  encrypted (even with an empty user password) or if anything in the object
  graph, object streams and hex-escaped names included, is `/JavaScript`,
  `/JS`, `/Launch`, `/EmbeddedFile(s)`, `/OpenAction`, `/AA`, `/AcroForm`,
  `/XFA`, `/RichMedia`, `/SubmitForm`, `/ImportData` or `/GoToE`. Only the one
  scanned image on each page is taken out and re-encoded like any photo. A
  page of typed or drawn content, or an image in a format other than JPEG or
  8-bit gray/RGB, is refused with a plain message; there is no rasteriser here.
- **Limits:** 6 MB a file, 6 pages in total across the upload, the pixel and
  decoded-memory caps above (a decoded page is at most pixels x 4 bytes), a
  25-second processing time per file, and at most two decode jobs at once
  (others wait up to 10 seconds, then are asked to try again with a 503). A
  job that times out or whose request is cancelled keeps its slot until the
  worker thread really finishes.
- **Isolation, honestly:** decoding runs in a worker thread inside the API
  process. That is **not** process isolation; it has the container's network
  and filesystem (which is `read_only` with all capabilities dropped). A
  malformed file that crashes a native decoder (libheif, libjpeg, zlib) is a
  risk this design reduces but does not remove. Bundled native libraries are
  covered by `pip-audit` only to the extent PyPI advisories name them.
- **Optional scanner.** Set `PRACTICE_SCANNER_URL` to a clamd you run yourself
  (`tcp://host:3310` or `unix:///path/to/clamd.ctl`). Each uploaded file is
  streamed to it first. A "FOUND" answer, an unreachable or slow scanner, or an
  answer it cannot understand **refuses the upload**. Unset (the default),
  nothing is scanned and no screen or document claims it was. No external
  scanning service is ever contacted.
- **Temporary files:** none are created. Everything is held in memory
  (`io.BytesIO`), so there is nothing to clean up after success, error,
  timeout or cancellation.

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
