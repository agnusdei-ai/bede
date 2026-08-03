# Adding curated content to Bede

Bede does not train on new material — it's Claude, prompted, plus a set of
curated static content files this repo owns and version-controls. "Updating
Bede's content" always means editing one of the files below and opening a
PR; there is no live scraping, no fine-tuning, no automatic ingestion. This
doc is the map for doing that consistently, so ongoing contributions (new
saints/feast material, more living books, more poetry, richer per-grade
guidance) stay easy to review and don't quietly drift from the sourcing
standard the existing content already holds itself to.

## The one hard rule: never store copyrighted text

Two very different patterns exist in this codebase — know which one you're
in before you add anything:

- **Metadata only, never the text itself** — the book catalog
  (`data/catalog/year*.json`) and the catechism catalog
  (`data/catechism/faith_and_life.json`) store titles, authors, themes, and
  *broad* topic threads, never excerpts or chapter-by-chapter contents of a
  copyrighted work. See `data/catechism/faith_and_life.json`'s own
  `_comment` field for the exact reasoning — it's the model to imitate.
- **Full verbatim text, because it's confirmed public domain** —
  `services/poetry_catalog.py` is the one place that stores complete texts,
  and only because every poem in it predates 1929 (US public domain) and
  was checked against a primary source. This is the exception, not the
  default — don't extend the "verbatim text" pattern to a catalog entry for
  a copyrighted book.

If you're not sure which bucket something falls into, default to metadata
+ citation, not full text.

## Sourcing standard

Every factual or "exact" claim (a title, a publication date, an exact
quoted line, a scope-and-sequence topic list) needs a real source behind
it, not an LLM's recollection. The precedent already in this repo:

- `data/catechism/faith_and_life.json`'s `_comment` cites Ignatius Press's
  own product pages (`loc.ignatius.com/faithandlife`) and is explicit about
  what it does and doesn't claim (topics are "broad thematic threads, NOT
  a claimed-exhaustive chapter-by-chapter table of contents").
- A prior session verified every poem in `poetry_catalog.py`'s original
  secular rotation against a primary source (e.g. UPenn's digital
  facsimile of Rossetti's 1872 *Sing-Song*) via WebSearch, and caught a
  real transcription error doing so ("By a fountain's brink" → "By the
  fountain's brink"). That rotation was later replaced with a Catholic
  poetry/hymn-text collection (per-entry sourcing is cited in each
  `_entry(...)` call's `source` argument) — verified the same way, via
  WebSearch cross-checked across multiple independent results per poem,
  since direct WebFetch access to primary-source sites (Poetry Foundation,
  Wikisource, sacred-texts.com, even Wikipedia) 403'd across the board in
  that session's environment. Anything that couldn't be corroborated
  consistently across sources was left out rather than guessed — favor a
  short, well-attested excerpt over a longer passage nobody could verify.

When you bring new source material, cite it (a `_comment` field in JSON, a
docstring/comment in Python) the same way, and verify anything presented as
exact against a primary source before merging — don't trust a single
LLM's memory for a quoted line or a specific date.

## Where each content type lives, and its schema

### 1. Living-books catalog — `data/catalog/year{1-8}.json`

One file per Mater Amabilis year (currently Years 1–8 exist). Loaded by
`services/catalog_service.py`'s `_load_catalog()` at import time; consumed
by `get_catalog_note()`/`get_subject_plan()`, which feed
`ai_service._get_catalog_context()`.

```json
{
  "id": "y1-aesop",                 // unique across ALL years — used as a lookup key
  "title": "Aesop's Fables",
  "author": "Aesop",
  "subject": "living_books",        // must match a Subject enum value (models/schemas.py)
  "type": "spine",                  // "spine" (core reading), "supplemental", or "reference"
  "difficulty": 1,                  // 1-3, roughly maps to grade band within the year
  "terms": [1, 2, 3],               // which of the year's 3 terms this is read in
  "concept_tags": ["virtue", "wisdom", "..."],
  "anti_twaddle": true,             // Charlotte Mason term — confirms this isn't diluted/condescending content
  "notes": "Oral narration focus. One fable per sitting. ..."
}
```

A year file can also carry a top-level `"subject_plans"` object (year1.json
onward) for non-book-list subjects (`mathematics`, `art_music`,
`language_arts`, `morning_time`) — see `get_subject_plan()`.

### 2. Catechism orientation — `data/catechism/faith_and_life.json`

One entry per grade (`"1"`–`"8"`; the series doesn't cover kindergarten,
and `get_catechism_note()` correctly returns `None` for `"K"`). Feeds the
`saints` subject.

```json
"5": {
  "book_title": "Credo: I Believe",
  "theme": "One sentence describing the grade's overall arc.",
  "topics": ["Broad thematic thread 1", "Broad thematic thread 2", "..."]
}
```

### 3. Visual aids — `data/visual_aids.json`

Picture study (`art_music`) and history maps/artifacts. No image hosting —
`wiki_title` is resolved client-side against Wikipedia's REST summary API.

```json
{
  "id": "vermeer_girl_pearl",       // unique — this is what show_visual_aid references
  "subject": "art_music",           // only "art_music" and "history" have entries today
  "category": "picture_study",
  "title": "Girl with a Pearl Earring",
  "creator": "Johannes Vermeer",
  "year": "c. 1665",
  "wiki_title": "Girl with a Pearl Earring",   // must be the EXACT Wikipedia article title
  "description": "A luminous portrait study — notice the light on her face..."
}
```

### 4. Bible translation copyright permissions — `data/bible_translations/copyright_permissions.json`

Publisher-stated permission-to-quote limits for the nine modern,
copyrighted translations in `models.schemas.BIBLE_TRANSLATIONS` (KJV and
Douay-Rheims are public domain and not listed here). A licensing-metadata
file, same "metadata only, never the text itself" category as the
catechism catalog above — it stores each publisher's own stated numbers
(verses or words, plus conditions), never any Bible text. Feeds
`services/catalog_service.py`'s `get_bible_translation_permission()`,
consumed by `services/ai_service.py`'s `_bible_translation_note`.

```json
"ESV": {
  "publisher": "Crossway",
  "free_quote_verses": 500,
  "conditions": "not more than half of any one Bible book, nor 25% or more of the quoting work; not permitted in a commentary or other biblical reference work",
  "source": "https://www.crossway.org/permissions/"
}
```

Sourced via WebSearch directly against each publisher's own
permissions/copyright page (cross-checked against an independent
secondary source where the primary page wasn't directly fetchable); see
the file's own `_comment` for the full sourcing note and dated
`researched_on` field. NABRE's entry uses `free_quote_words` instead of
`free_quote_verses` since the USCCB states its own threshold in words, not
verses — don't convert one to the other; keep the field name that matches
what the publisher actually states.

### 5. Poetry — `services/poetry_catalog.py`

Verbatim public-domain Catholic poems/hymn-texts — see the sourcing
standard above before adding here. Rotates weekly off the calendar (ISO
week number), not a parent-set field — see the module docstring for why.
Each entry is tagged with the specific grade(s) ("K"–"8") it fits via the
`_entry(title, poet, source, grades, text)` helper; `GradeStage` is
derived automatically from that grade set (never hand-maintained
separately) and used only as a fallback when a session has a stage but no
specific grade.

### 6. Classical languages — `services/latin_catalog.py`, `services/greek_catalog.py`

Verbatim Vulgate anchors and the six foundational terms behind
`Subject.latin` (Fides, Spes, Caritas, Sapientia, Veritas, Ora et Labora),
plus per-stage shared-Christian vocabulary. Same weekly calendar rotation
as poetry. Three rules specific to this file, all of them enforced by
`tests/test_latin_catalog.py`:

- **Every Latin text must be checked against a published Vulgate edition
  before it lands here** — a stricter bar than the rest of this doc's
  sourcing standard, and stricter than `prayer_catalog.py` was actually
  held to (its docstring records that its texts came from model knowledge
  because a reference site wasn't reachable at the time). Latin is
  inflected: a wrong ending is a wrong meaning, and neither the child nor
  the parent is positioned to catch it. Readings here are the Clementine
  Vulgate's; the two known edition variants are recorded in the module
  docstring so a future editor doesn't "fix" one into the other.
- **Nothing specific to one Christian tradition goes in.** This subject
  exists so a family that holds none of the distinctively Catholic
  doctrines can still teach Latin rooted in the faith; `Subject.saints` is
  where tradition-specific content belongs. Ave Maria, Salve Regina, the
  Sanctus, and the Confiteor are all deliberately absent and should stay
  that way.
- **Attribution gets stated honestly even when it's less tidy.** The
  `ora_et_labora` entry says outright that the motto is a 19th-century
  formulation (Maurus Wolter, 1880) rather than a phrase from St.
  Benedict's Rule, and supplies the sentence that *is* from the Rule to
  quote instead. Anything similar — a beloved phrase whose usual
  attribution doesn't survive checking — gets the same treatment rather
  than a smoothing-over.

Greek adds three rules of its own, on top of all of the above:

- **Never quote a passage where the manuscript traditions differ.** Greek
  has a live and denominationally charged textual divide the Vulgate does
  not: the Textus Receptus (behind the KJV/NKJV) against the modern
  critical text (behind the ESV/NIV/NASB/CSB). A K-8 subject must not
  adjudicate it. Every anchor in `greek_catalog.py` was chosen because both
  traditions read it identically at the phrase quoted — verify that before
  adding a new one, and if a passage has a real variant, pick a different
  passage. Same instinct as Latin's psalm-numbering decision.
- **Transliteration and English are mandatory, never optional.** Any Greek
  a child sees must carry both. Latin needs no equivalent rule; its script
  is already the child's own.
- **Pronunciation is Erasmian and is labelled as a convention, not a
  reconstruction.** Modern and Byzantine pronunciation are closer to the
  living tradition, and an Orthodox or Greek-heritage child may well say
  these words the way their own parish does. The instruction never to
  correct them is load-bearing, not politeness.

Two mappings in `services/ai_service.py` carry the wiring, and they are
deliberately different sets:

- `_CATALOG_NOTE_SUBJECTS` — every subject with its own weekly,
  stage-filtered catalog block (Latin, Greek, Logic), mapped to its
  renderer. All share the signature `(grade, stage, week_salt, today) -> str`.
- `_CLASSICAL_LANGUAGE_SUBJECTS` — the subset that teaches a *language*,
  mapped to its `language_exposure` id. This is what gates the
  Bible-translation note and the own-language-only evidence check.

`Subject.logic` is in the first and not the second, which is the whole
reason they're two mappings rather than one. Adding a language means a row
in both plus a catalog module; adding a non-language catalog subject means
a row in the first only — never another branch in three functions.

### 6b. Logic — `services/logic_catalog.py`

Same fixed-content discipline as the language catalogs, for a sharper
reason: a model asked to invent a syllogism will sometimes produce an
invalid one and label it valid, and catching that error is exactly what
the student is still learning to do. Every syllogism and fallacy example
is fixed, worked out, and carries an explicit verdict.

Three rules specific to this subject, all enforced by
`tests/test_logic_catalog.py`:

- **Nothing here renders for K-2, and the gate is real in four places** —
  `SessionConfig._validate_logic_stage` (drops the subject),
  `subjectsForStage` in `ParentSetup.tsx` (never offers the card),
  `logic_note` (returns `""`), and the absent year-1/2 plans (asserted by
  `tests/test_catalog_coverage.py`). Prompt text alone would not have been
  a gate.
- **Examples stay deliberately dull** — weather, animals, chores,
  homework. An example with real stakes teaches the stakes rather than the
  form, and a family-shaped example teaches a child to audit their
  parents. A test scans every fallacy example for politically, religiously,
  or family-charged material and fails on a hit.
- **The charity guardrails are content, not decoration.** Logic serves
  truth and never winning; Bede never coaches a child in arguing against
  their own parents; Bede rules on no contested political, moral, or
  religious dispute. Each guarantee travels in both the prompt block and
  every year plan, so softening one doesn't quietly soften the feature.

### 7. Subject/stage guidance — `services/ai_service.py`

Not a data file — plain Python dicts that are part of the system prompt:

- `_SUBJECT_CONTEXT` (per-`Subject` teaching approach and tone)
- `_STAGE_GUIDANCE` (per-`GradeStage`: foundations/core_mastery/independent)
- `_GRADE_DESCRIPTORS` (per-grade string like "3rd grade")

These are prose, not structured data — editing them is a normal code PR,
same review bar as anything else in that file.

## Adding something — the checklist

1. Confirm which bucket you're in (metadata-only vs. verbatim-public-domain)
   and match its existing schema exactly — copy a neighboring entry as a
   template rather than inventing new fields.
2. Cite your source in a comment/`_comment`, and verify any exact quote,
   date, or title against that primary source, not memory alone.
3. Keep IDs unique (`tests/test_catalog_data_integrity.py`, added alongside
   this doc, checks this in CI — see below).
4. Run the backend test suite: `cd homeschool-api && python -m pytest tests/ -q`.
5. If you added or changed a `Subject`-scoped file (catalog, catechism,
   visual aids), sanity-check it actually surfaces where expected —
   `_get_catalog_context`/`_get_visual_aids_context`/`_build_subject_prompt`
   in `services/ai_service.py` are the wiring to trace if something added
   doesn't show up in a session.
6. Open a PR — same flow as any other change in this repo (see the root
   `CLAUDE.md`).

## Automated safety net

`tests/test_catalog_data_integrity.py` runs on every push/PR (same CI as
the rest of the backend test suite) and checks, across every catalog file:
every book/visual-aid ID is globally unique, every entry has its required
fields non-empty, every `subject` value is a real `Subject` enum member,
and every catechism grade key is a plausible `"1"`–`"8"` string. It exists
so a future content PR — from you, or a future Claude Code session — fails
loudly in CI on a malformed entry instead of silently shipping a broken
lookup.
