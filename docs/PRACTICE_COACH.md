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

1. **Read.** The parent uploads as many pages as the quiz has, as JPEG or
   PNG photos or as a PDF of scanned pages. There is no page limit: pages are
   rebuilt and read six at a time, one model call per group, and the groups'
   readings are joined into one worksheet (a section that runs across a group
   boundary is joined back into one). Each group's images are released before
   the next group is built, so memory does not grow with the page count. The
   browser sends a long upload in parts of at most six files and 24 MB
   (`utils/uploadParts.ts`), so each request fits the API's 30 MB and nginx's
   42 MB for `/api/practice/`; each
   part continues the same saved reading (`continues_record`; the demo, which
   stores nothing, sends back what the earlier parts read as `continues`). On
   the public demo each group of pages is one model call and counts as one
   message against the visitor's allowance.

   **A progress bar shows how far a reading has got.** Each request carries a
   random `progress_id`; `services/practice/progress.py` records, in memory
   only, the page total once every file is checked and the pages read after
   each group, and the browser polls `GET /practice/progress/{id}` (parent),
   `/practice/educator/progress/{id}` or `/practice/demo/progress/{id}` about
   once a second (`utils/readingProgress.ts`, mirrored in the demo). The bar
   shows the whole upload: finished parts count in full, the current part by
   its pages, and a quiz draft shows "Writing the quiz" near the end. An entry
   holds four numbers and a stage word, nothing from the pages, is keyed by
   who asked as well as the id, and expires ten minutes after its last update.
   A poll that reaches a different API process answers "unknown" and the bar
   keeps its last figure; it never goes backwards.
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
- **On the household's configured cloud AI provider**, when no local model is
  configured, only after the parent confirms it for that upload. This is
  **on by default** (owner ruling 2026-11-04, register entry 39);
  `PRACTICE_CLOUD_READING_ENABLED=false` keeps photo reading local-model
  only, and with it off the server refuses the cloud route outright, so a
  direct API request cannot bypass it, and the reading-route screen offers no
  consent tick. Without the parent's confirmation the request is refused
  before anything is sent, and the response names the provider. Next to the
  tick the screen says that the provider may keep the page images for up to
  30 days to check for misuse, under its own API terms, and that Bede does
  not save them; it also suggests cropping out a full name or student number,
  without requiring it (a first name alone is not a reason to block). Only the
  re-encoded page images go, with one fixed line of text: no learner id,
  roster detail, typed name or file metadata (a test pins the request shape).
  The cloud route is pinned to the provider the
  parent's confirmation names (`services/adapters/router.py`'s
  `resolve_named`): if it errors, the request fails rather than being retried
  on another provider. The named provider follows any primary or backup
  switch the parent made in AI provider settings, so the tick always names
  where the photos actually go.

`GET /practice/reading-route` tells the parent which applies before they
upload.

**A quiz drafted from typed text only** (a topic, or a quiz pasted as text,
with no photos) follows a narrower rule, because no photo leaves the browser:
it is the same kind of text a tutoring turn already sends. It may use the
configured cloud provider without the photo switch, but still only after the
parent ticks the box naming that provider, and it is pinned to that one
provider (`services/adapters/router.py`'s `resolve_named`): if it errors, the
request fails rather than being retried on a backup the parent did not agree
to. Teachers stay on the school's own model for typed drafts too. The route
reports this as `draft_provider`, separate from the photo route's
`cloud_provider`. On the public demo, which has no local model, both typed
drafts and photos go to OpenAI after the tick, and never to a backup provider.
The demo's Privacy Notice describes it.

The photos are not saved to the database or a file by Bede; they are held in
memory while the request runs, and no temporary file is created (a test pins
that). Nothing from an upload is logged. The memory is released when the
request ends; Bede cannot promise anything about a model provider's own
retention once a parent has consented to a cloud read, which is why that
consent is asked per upload. The reading has **no field** for a
name, school, teacher or date, so a reading that includes one is rejected
rather than stored. Readings and practice sets are encrypted with the
student's own key and are removed when the student is deleted.

On the public demo the same routes exist as previews under `/practice/demo/`,
with nothing stored.

## File validation and hardening

This is hardening, **not a guarantee that a file is free of malware**, and the
parent-facing text never says "virus-free". It is `services/practice/upload_safety.py`,
and it runs after the parent is authenticated and after consent and routing are
settled, before anything reaches a model.

- **Type comes from the bytes.** PNG, JPEG (including the multi-picture MPO
  files Samsung and other Android cameras save; only the first picture is
  used), WebP, AVIF (`ftyp` brand `avif`/`avis`, or a generic HEIF brand that
  lists `avif` as compatible), HEIC/HEIF (`ftyp` brands `heic`, `heix`, `hevc`,
  `mif1`, `msf1`, `heif`) and PDF are recognised by their magic numbers only.
  WebP and AVIF are decoded by Pillow itself, so the HEIC hold below does not
  apply to them. The API receives no filename or content type for a page, and
  none is consulted.
- **Native HEIC security hold.** The pinned `pillow-heif 1.8.1` bundles
  `libheif 1.23.6`; upstream libheif 1.23.7 (October 26, 2026) fixes
  multiple high-severity vulnerabilities. HEIC/HEIF is refused before any
  native decode unless the *linked* libheif reports 1.23.7 or newer, and no
  pillow-heif release bundling it existed on 2026-11-04. A HEIC upload is
  refused with "HEIC photos cannot be read. Use JPEG, PNG, or PDF." The file
  picker leaves HEIC out on purpose, so an iPhone hands over a JPEG copy.
  The Practice Coach screens do not list formats Bede cannot read (owner
  direction 2026-11-05); the message above appears only if a HEIC file is
  actually sent, and the tests fail if the screen mentions HEIC.
  HEIC is not part of the Mac pilot's acceptance scope (owner ruling
  2026-11-04), and a refused HEIC never blocks the supported formats. The
  gate lifts on its own once a patched pillow-heif is pinned; it is never
  bypassed.
  Independent native decoder review is still required before enabling HEIC
  in a release. Python package audit alone is not sufficient evidence.
- **Images are fully decoded and re-encoded** with Pillow into a fresh PNG: the pixel count is
  capped from the header before decoding (30 megapixels, 12,000 px a side),
  Pillow's own decompression-bomb warning is turned into an error, `verify()` is
  followed by a real reload, EXIF rotation is applied, and metadata plus anything
  appended after the image (a polyglot payload) does not survive. Pages are
  scaled down to 3,000 px a side.
- **PDFs are rendered, and the rendered page is what is checked.** pypdf
  first refuses an encrypted PDF (even with an empty user password) or one
  where anything in the object graph, object streams and hex-escaped names
  included, is `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFile(s)`,
  `/OpenAction`, `/AA`, `/AcroForm`, `/XFA`, `/RichMedia`, `/SubmitForm`,
  `/ImportData` or `/GoToE`. Every image in the file is then held to the photo
  pixel cap and every compressed stream is inflated against a fixed bound
  (an image: its declared size; anything else: 32 MB) **before** anything
  renders, because a renderer inflates whatever a page asks for. Each page is
  then drawn with **pdfium** (`pypdfium2`, the PDF engine Chrome ships) at no
  more than 3,000 px a side, annotations drawn and form fields not, and the
  result is re-encoded like any photo. So a scanner's stacked layers, typed
  text, drawn marks and a teacher's comments all survive, whatever the page is
  built from (owner ruling 2026-11-04: no assumption about how many images a
  page holds). A page that renders blank is refused. pdfium is not
  thread-safe and two uploads may decode at once, so rendering is serialised
  behind one lock. A generated regression fixture
  (`tests/practice_scanner_fixture.py`) is built exactly like a real
  three-layer office-scanner PDF (background, white cleaning mask, CCITT ink
  mask); the real scan it copies stays out of this public repository.
- **Unclear pages are read, not refused.** The reader is told to read
  blurry, dark, faint, tilted or cut-off pages anyway and to mark what it is
  unsure of. A reply wrapped in prose, cut off part-way or carrying one bad
  field keeps every question that can be read (`extract.parse_reading`), and
  anything repaired waits for the parent's **Looks right**. A group that still
  cannot be read gets one second look at a sharpened copy
  (`upload_safety.enhance_for_reading`: contrast stretched with colours kept,
  small pages enlarged, edges sharpened), charged on the demo like any call.
  A reply carrying a name, school or date field is still refused whole.
  `tests/test_practice_unclear_pages.py`.
- **Every refusal says what to do next.** A damaged or unsupported PDF is
  told to save or export it again or send photos of the pages; a file too
  large, too complex or too slow to check is told to split it or use a lower
  resolution; a busy server asks to try again in a moment. Nothing is
  half-read. `test_every_upload_refusal_in_the_source_names_a_way_forward`
  reads every refusal in `upload_safety.py` and fails on one without a way
  forward.
- **Limits:** up to 1 GB for a whole upload (checked in the browser, which
  sends it in parts; owner ruling 2026-11-05), 25 MB a file and 30 MB a
  request (`/api/practice/` accepts 42 MB in nginx, since base64 adds a
  third), no limit on pages. A single file stays at 25 MB because the server
  holds one file in memory to render it, and the demo server has 512 MB. A
  long quiz source is copied out as text part by part
  (`POST .../quiz/source`), and the draft reads the first 60,000 characters
  of it; the screen says so when a source is longer. The pixel and
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
- **Optional scanner.** Set `PRACTICE_SCANNER_URL` to a clamd on the same
  machine: `unix:///path/to/clamd.ctl`, or TCP on the loopback interface only
  (`tcp://127.0.0.1:3310`, `tcp://[::1]:3310`, `tcp://localhost:3310`).
  Anything else, a hostname, a compose service name, `0.0.0.0` or any non-loopback
  address, is refused when the API starts, and again before every scan; locality
  is judged from the text of the URL and never by looking a name up. The scanner
  is sent the original, unmodified file, which is why. A clamd in another
  container is reached through a shared unix-socket volume, not over tcp. Each uploaded file is
  streamed to it first. A "FOUND" answer, an unreachable or slow scanner, or an
  answer it cannot understand **refuses the upload**. Unset (the default),
  nothing is scanned and no screen or document claims it was. No external
  scanning service is ever contacted.
- **Timeouts do not stop a decode.** A worker thread cannot be killed. When the
  25 s limit passes the caller is told to retry, but the thread runs until it
  finishes, and keeps its slot until then. At most 2 decode jobs run at once
  and a third caller waits 10 s and gets a busy answer, so a slow file cannot
  pile up work, but it can tie up both slots for as long as the decode takes.
  Process isolation would remove this and is not part of this change.
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

**Picture questions, in every subject (`services/practice/diagrams.py`,
`Diagram.tsx`).** When a question's picture is the question, it carries a
`diagram`: one of twenty kinds holding only numbers and short labels
(`models/practice.py`, `extra="forbid"`). For maths: fraction bar or circle,
array, base-ten blocks, clock, rectangle, right triangle, number line, bar
graph, coordinate plane, things laid along a ruler (cm or inches, ends on
whole or half units: "how long", "total length", "how much shorter" are
worked out), coins and bills (the total is worked out), and a thermometer. For any subject: pictures of things to name, sort or
count (a fixed list of about a hundred animals, plants, weather, foods,
objects, people and body parts, each drawn as a picture symbol), a scene (one
thing doing one thing, which is how Latin's "Quid agit?" practice is drawn),
a timeline (BC years as negative numbers), a Venn diagram, a table, a cycle
(the water cycle, a life cycle) and a sequence of steps, where a step written
"?" is drawn as a blank. The recall and reading packs re-ask a missed
question with its own picture, and the Latin pack draws every practice
scene. The reader and the drafting model are given one shared list
(`diagrams.PROMPT_SCHEMA`), so the two cannot drift. A photograph, a map or a
drawing none of these fits is described in plain words by the reader, and
`diagrams.from_stimulus` then draws whatever those words name from the same
list ("dog running" becomes a dog with a running mark; "3 apples and 2
bananas" becomes three apples and two bananas). This runs whenever an
assessment item is built (an `AssessmentItem` validator), so readings saved
before it existed are drawn too; a diagram the reader gave is never replaced.
A named, real thing no drawing fits ("the Battle of Hastings", "Rocky
Mountains", "The Starry Night") becomes an `image` diagram: the title of an
English Wikipedia article, never a link (the model refuses URLs and anything
shaped like a scheme). The browser fetches that article's lead picture with
the same lookup picture study uses, and shows it only when the file is on
Wikimedia Commons, which holds freely licensed files (English Wikipedia's own
uploads can be non-free), with the credit "Picture: Wikimedia Commons, from
the Wikipedia article ..."; a missing article, a disambiguation page, no
picture or no network shows the words instead. A print shows the picture
once the screen has shown it. An adult sees every such picture before a
child does, because practice is approved and quizzes are reviewed. Only a
short, capitalised name is ever looked up, so an everyday description is
never sent off as a title, and a name made only of drawable words ("Dog
Running") is drawn. The reader and the drafter may also ask for an `image`
directly. A written sum with a
picture beside it is still worked out as a sum. The reader
records it, the drafting rules ask for it, and the app draws it itself as SVG
on screen and in print, so a model never writes markup into the page and the
picture and its answer cannot disagree. `diagrams.answer` counts the answer
off the picture (or returns nothing for a question it cannot settle, such as
a bar graph's "how many more", which goes to the adult); `explain` names only
slips a parent can check against the picture (shaded against unshaded parts,
clock hands swapped, rows added instead of multiplied, area for perimeter, x
and y swapped); `new_like` draws a fresh picture of the same kind for
practice, never the missed one. In a drafted quiz the picture decides the
answer: a short answer is replaced by the counted one, a multiple-choice
question with no option matching the picture is dropped, and a diagram
outside the vocabulary drops the question rather than leaving it described in
words. A lettered number line numbers only its ends, so "what number is at
A?" stays a question. `tests/test_practice_diagrams.py` and
`demo/src/Diagram.test.tsx` (which also keeps the app and demo copies equal
and the kinds in step with the API's); each guard was checked by breaking it.

**The parent picks a school subject, not a pack.** Packs group subjects by how
a mistake is checked (worked out exactly, named by spelling pattern, compared
with the teacher's correction), which is not how a parent or a school looks
for them. `_SUBJECTS` in `packs/__init__.py` lists Mathematics, Reading and
language arts, Spelling, Grammar, Science, History and social studies,
Geography, Latin and Other short-answer quiz, each naming the pack that checks
it. That covers the subjects STAAR tests in grades 3-8 (mathematics, reading
language arts, science and social studies), the state test the Valor pilot
notes name, as well as the subjects a homeschool lists. A subject id is accepted
wherever a pack id is, and pages are read under the subject's own name.

**Latin** detects five patterns:

- the general word for the specific one (*avis* for *anas*);
- a confusable pair from the bank;
- a word not in the bank;
- a macron the teacher marked;
- answering *what it is* when asked *what it is doing*.

Other categories (verb endings, noun cases, word order, translation
direction) are in the taxonomy so a parent can name them, but are not
detected yet.

**Mathematics** (`packs/math/`) works each problem out exactly
(`fractions.Fraction`, never floating point), then asks which known slip
produces the child's answer:

- adding without carrying, or taking the smaller digit from the larger;
- a two-digit multiplication whose second row was not shifted;
- a basic fact to 12;
- the wrong operation for the sign;
- adding across a fraction, dividing a fraction without inverting, a right
  amount not in lowest terms;
- a misplaced decimal point;
- a lost or mishandled negative sign;
- working left to right instead of multiplying first.

Practice is new problems of the same shape with computed answers, never a
problem already on the page. Two cases go to the parent instead of being
diagnosed: a problem that is not written as an expression (a word problem,
a variable), and a teacher's correction that disagrees with the pack's own
answer, which usually means the problem was misread.

**Spelling** (`packs/spelling/`) compares each word with the correct
spelling on the page. It names:

- a homophone;
- two letters swapped, or ie/ei;
- a doubled consonant;
- a silent e kept before -ing or left off the end;
- a y not changed to i;
- a vowel or consonant sound spelled another way;
- a letter left out or added.

Practice is look-say-cover-write-check on the missed word itself, which is
the remedy for spelling, then words with the same pattern from
`item_bank/patterns.json`. The bank supplies examples only for a pattern the
child already missed. A word with no correction on the page goes to the
parent.

**Short answers** (`packs/recall/`) covers history, science, geography,
reading questions, grammar terms, vocabulary and multiple choice. It never
supplies a fact. Every practice answer is the teacher's correction or the
child's own right answer, so a miss with no correction goes to the parent.
It names a different answer, a partial answer, another option chosen, or the
right answer spelled differently. Practice asks the missed questions again,
mixed with a few the child knew, because retrieval is the practice for
remembered material.

**Reading and language arts** (`packs/reading/`) is for comprehension
questions on a passage, the kind state reading tests use. A question whose
answer is in the passage is checked against the teacher's correction and
named: a different detail, a different meaning for a word, another option
chosen, a partial answer, or the right answer spelled differently. Practice
sends the child back to the passage to find the answer. A question that asks
for judgement (why, the main idea, the theme, the author's purpose, an
inference) or any answer longer than twelve words is **never marked by Bede**:
it goes to the parent with the child's answer and the teacher's comment. A
multiple-choice item is always checked against the teacher's marked answer,
whatever it asks, because the answer is then on the page.

Each of these four has a golden quiz in its `golden/` folder, written for
this repository, and `tests/test_practice_packs.py`.

## Quizzes and exams

Separate from diagnosing a graded quiz, Bede can **draft a new quiz or exam**
for any Bede subject that is taught and assessed, K-8. The source can be:

- photos or a PDF of an existing quiz, a previous exam or a prep exam;
- the text of one, pasted in;
- or a description of what to cover.

The adult chooses:

- the grade;
- the level (review, on grade level, challenge);
- the type (quick check, quiz, unit test, midterm, final exam, exam prep);
- the number of questions, up to 50.

Bede works out what the source covers, then writes new questions at that
grade and level (`services/practice/generate.py`). Grades 9-12 come later;
the request model accepts K-8 only.

Bede writes both questions and answers, so the draft is checked in code
before anyone sees it:

- **Maths answers are recomputed.** A question written as an arithmetic
  expression is worked out with the maths pack's exact evaluator, and a
  wrong model answer is replaced. These answers show **Worked out**.
- **Every other answer is answered a second time, independently.** The
  second answer is written without seeing the first, from the questions
  alone and any source material the adult gave. When the two agree, the
  answer shows **Double-checked**. When they disagree, it shows **Check**
  with the second answer beside it. If the second pass is unsure, or fails,
  the answer shows **Check**.

  This is a cross-check by the same kind of model against the material
  provided, not a search of outside sources. It makes a wrong answer key
  less likely; it does not rule one out.
- **Multiple-choice and true/false answers must be one of the options**, or
  the question is dropped.
- **A question copied word for word from the source is dropped.**

Nothing reaches a student until the adult approves the quiz.

Some subjects are not offered:

- **Scripture, Saints & Catechism and Morning Time** are never quizzed or
  scored. A child's spiritual life is not measured.
- **Free Study** has no content of its own to quiz.
- **Logic** starts in grade 3.

Reading and drafting use the same route as photo reading: the household's
local model, or the configured cloud provider only with consent for this
request. Nothing is stored.

- **In the app**, the parent prints the quiz and its answer key from the
  student's Progress page.
- **Teachers** have the same builder on the classroom page
  (`/practice/educator/quiz/generate`, passkey-verified teacher session).
  Teacher drafts run on the school's own local model only, never a cloud
  provider, because a teacher's upload can hold students' work; with no
  local model the teacher is told so. No learner is named, read or written.
- **In the demo**, an approved quiz is delivered into the chat, questions
  only. Each draft counts twice against the demo's message quota, since it
  is two model calls.

Tests are in `tests/test_practice_quiz_generation.py`. Each guard was
verified by breaking it.

## Teacher quizzes with answer keys

On the classroom page, a teacher can use their own quiz, approve its answer
key, and then score a student's completed work against it. This is the card
**Your own quiz, with an answer key**
(`homeschool-tutor/src/components/TeacherQuizStudio.tsx`,
`services/practice/teacher_quiz.py`). The steps are:

1. **Write or bring the quiz.** The teacher writes it on screen (questions,
   choices, the answer, other accepted answers, points, and for a written
   response a rubric and optional scoring guidance). Or they bring one they
   already have: paste its text, or add photos or a PDF through the
   same file checks as every other upload. Bede reads the
   questions, describes any diagram in a short line, and copies an answer key
   or the teacher's marked answer when the page shows one. A quiz Bede
   drafted in **Make a quiz or exam** can be handed over too, with
   **Edit the key and score students' work**.
2. **Review the key.** Every answer says where it came from: **Your answer**
   (typed by the teacher), **Read from your page**, or **Suggested by Bede**.
   Only the first counts as approved. The other two, and anything Bede was
   unsure of reading, are highlighted and count only after the teacher
   presses **Looks right**, the same step the Practice Coach uses for a
   flagged reading. A suggested maths answer is worked out with the maths
   pack's exact evaluator; when a key read from the page disagrees with the
   computed answer, Bede flags it and leaves the teacher's key in place.
   **Check and approve the key** asks the server, which refuses while
   anything is unsettled and says what.
3. **Print and give the quiz.** The blank quiz has a name line for the
   student to fill in by hand. The answer key prints separately, with
   accepted answers and rubrics.
4. **Upload one student's work.** Photos or a scan of the completed quiz,
   with a tick for that upload, or the answers typed in.
5. **Review Bede's proposals.** Bede reads the work against the questions
   only. **The reader never sees the answer key or the rubric**, so it
   copies what the student wrote rather than what the key says. Each answer
   is then compared with the approved key **in code**:
   - multiple choice and true or false, by the choice's text or its letter;
   - numbers exactly, with the maths pack's evaluator (`1/2` and `0.5` agree);
   - short answers with case, accents and punctuation ignored, against the
     answer and the teacher's other accepted answers.

   A short answer that does not match the key is set to the teacher, never an
   automatic zero, because the wording may differ and still be right. Only a
   written response **with a rubric** gets a score from the model, rounded to
   a half point and always marked for the teacher. Without a rubric the
   teacher scores it. Any reading Bede was unsure of is marked too.
6. **Approve or correct the results.** Results marked for review count only
   after the teacher presses **Looks right** or types a score; the teacher
   can change any score. **Approve these results** totals them on the server,
   which refuses while any result is unsettled. Bede never settles one.

**Where it runs.** Every page and every answer here is read on the school's
own local model through `resolve_local_only()`, never a cloud provider, by
the standing ruling that a teacher's upload can hold students' work
(register entry 39). A page upload needs the teacher's tick for that upload,
naming the school's own model, before anything is parsed. With no local
model the teacher is told so: pages cannot be read, but a quiz can still be
written, and typed answers are still scored (all but rubric proposals need
no model).

**What is stored.** Nothing. The quiz, its key, the student's pages, their
answers and the results exist only in the request and on the teacher's
screen. The teacher keeps a quiz by saving it as a file with **Save as a
file** (`bede.teacher-quiz` JSON, version 1) and opens it again with **Open a
saved quiz file**, which the server checks before it is used. Results are for
the teacher's printout.

Why nothing is stored:

- **A blank quiz and its key hold no learner data**, so a server table would
  add a retention category and a deletion obligation for something a file
  does as well. The cost is that a saved quiz lives on the teacher's device,
  not in their account.
- **A student's results are not kept on the server.** The pilot's evidence
  record (`routers/pilot_journey.py`) is campus-mode and UUID-scoped through
  `_assigned`, and takes externally administered assessment reports
  (`EducatorAssessmentSubmission`), not a classroom quiz score. The classroom
  page's quiz tools name no learner at all. Recording quiz results against a
  learner would need a new evidence type, school data authorization and an
  owner decision on what a quiz score may mean in a learner's record. Until
  then, results are review and print only.

The quiz never names a learner and has no field for one; neither does a
reading. Faith subjects are refused here as everywhere (never scored), and
Logic starts in grade 3.

**Pages and size.** There is no page-count limit. Every PDF page is drawn as
you would see it, so a scanned page, a PDF of typed text, a diagram and a
teacher's or student's drawn marks are all kept, the same as in the Practice
Coach. Every file is checked first, then the pages are read six at a time,
one model call per group (`upload_safety.page_groups`): the quiz's questions
are joined in order and numbered again, and a student's answers are joined by
question number, a question answered on one group's pages keeping its answer
and the more confident of two readings winning (`teacher_quiz.merge_responses`).
A teacher upload goes in one request, so the limits are bytes: 25 MB a file
and 24 MB together (30 MB at the server). Over that, the screen says so
before anything is sent and suggests smaller scans or pasting the text.
Sending a larger teacher upload in several requests, as the Practice Coach
does, and a progress bar for teacher uploads are not built yet.

Routes (all `require_educator`, under `/practice/educator/teacher-quiz/`):
`review`, `approve`, `extract`, `score`, `finalize`. Tests are in
`tests/test_teacher_quiz.py` (over HTTP through the real practice router),
`TeacherQuizStudio.test.tsx`, `utils/teacherQuiz.test.ts`,
`services/teacherQuizApi.test.ts` and `pages/EducatorDesk.teacherQuiz.test.tsx`
(the hand-off from the drafting tool, through the real classroom page). Each
guard was verified by breaking it.

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
4. **Done:** Mathematics, Spelling and Short-answer packs. **Not yet:** feeding
   their results into the phonics (K-2) and reading-and-spelling (3-8)
   mastery engines, and the optional game wrapper. Rewards count **days
   practised**, never streaks, and never speed.

**Not yet:** pages are not straightened or cropped before reading. That
needs an image library this backend doesn't carry, and the reader copes with
ordinary phone photos.
