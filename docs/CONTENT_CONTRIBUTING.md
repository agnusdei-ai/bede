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

### 4. Poetry — `services/poetry_catalog.py`

Verbatim public-domain Catholic poems/hymn-texts — see the sourcing
standard above before adding here. Rotates weekly off the calendar (ISO
week number), not a parent-set field — see the module docstring for why.
Each entry is tagged with the specific grade(s) ("K"–"8") it fits via the
`_entry(title, poet, source, grades, text)` helper; `GradeStage` is
derived automatically from that grade set (never hand-maintained
separately) and used only as a fallback when a session has a stage but no
specific grade.

### 5. Subject/stage guidance — `services/ai_service.py`

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
