# Localization

Bede supports running a deployment in a language other than English. This
page covers what's implemented, what's deliberately deferred, and why —
see the architecture discussion in this repo's history for the fuller
reasoning behind each call.

## Scope model: one locale per deployment, not a runtime switcher

A self-hosted family instance runs in **exactly one language**, chosen once
at setup via the `LOCALE` env var (backend) and `VITE_LOCALE` build-time env
var (frontend) — not a live language picker in the UI. That matches how
every other per-family setting works in this app (`PARENT_PASSWORD`,
`CHILD_PIN`, etc.): configured once, not switched mid-session.

The public demo (`demo/`) is a different problem — one deployment serving
visitors worldwide at once — and needs its own runtime language switcher
rather than a build-time bake. That's out of scope for this pass; the demo
still ships English-only until that's built separately.

## What's implemented

**Backend — native generation, not translation** (`core/config.py`'s
`LOCALE` setting, `services/ai_service.py`'s `_locale_directive`): when
`LOCALE` is set to a supported non-English value, Bede's system prompt
gains one instruction telling Claude to converse with the student directly
in that language. This is deliberately **not** a translation pipeline —
there's no English draft generated and then translated. Claude is natively
multilingual, so asking it to write in Spanish from the start costs nothing
extra in latency (same single generation pass as English today, still
streamed token-by-token over the existing SSE pipeline) and — unlike a
machine-translation engine — it can simultaneously apply the grade-level
reading-complexity judgment `_STAGE_GUIDANCE` already asks for. An NMT
engine translates exactly what it's given; it can't "simplify this to a
3rd-grade reading level" on its own.

Tool names and structured data (`request_narration`, `celebrate_discovery`,
etc.) stay in English regardless of locale — the frontend matches on the
literal tool name string, so only Bede's own spoken/written words change
language.

`LOCALE=en` (the default) is a strict no-op: `_locale_directive` returns an
empty string, so the static prompt is byte-for-byte identical to a
deployment that never heard of this feature.

**Frontend — `react-i18next`** (`homeschool-tutor/src/i18n/`): resource
bundles per locale (`locales/en.json`, `locales/es.json`), loaded once at
`VITE_LOCALE` build time. `src/i18n/locales.test.ts` guards against a
common real failure mode — a string added to `en.json` and silently
forgotten in `es.json`, which i18next doesn't error on, it just falls back
to showing the raw key to the parent. The test checks key parity,
non-empty values, and matching `{{interpolation}}` variables between
locales.

**Currently translated:** `Login.tsx` only, as the first end-to-end proof
slice (build, typecheck, and both the English and `VITE_LOCALE=es` bundles
verified to actually contain the translated strings). The rest of the UI —
`ParentSetup`, `PodDashboard`, `TutorSession`, `SocraticChat`, voice
enrollment/verification, etc. — is **not yet translated**; each is a
follow-up slice using the same `t('namespace.key')` / `Trans` pattern
established here.

## Sex, not gender-neutral hedging

Spanish, Italian, and Polish all require grammatically correct address —
"bienvenido"/"bienvenida", and in Polish even past-tense verbs agree with
the subject's sex. The first version of this feature sidestepped that with
gender-neutral phrasing ("¡Hola!" instead of "¡Bienvenido/a!") because the
data model had no way to know a student's sex at all — not a deliberate
choice, just the only option available given the gap. That's since been
corrected, consistent with Bede's classical natural-law formation
(`docs/CONSTITUTION.md`): biological sex, not a separate "gender identity"
concept, is the actual grammatical category these languages need.

`SessionConfig.sex` (`"male"` / `"female"`, `models/schemas.py`) is
collected once at parent setup — surfaced in the UI only when the
deployment's locale needs it (`GET /admin/status`'s `locale` field drives
`ParentSetup.tsx`'s `requireSex`; an English-only deployment never asks).
`POST /pod/configs` (`routers/pod.py`) refuses to save any student config
missing `sex` once `LOCALE` is non-English — fail fast at save time, not a
silent gap discovered mid-conversation. `_locale_directive`
(`services/ai_service.py`) tells Bede the student's sex and instructs
correct grammatical agreement — explicitly *forbidding* falling back to
neutral phrasing when the sex is known, and only degrading to neutral
phrasing for a config saved before this field existed.

This assumes every supported locale is a grammatically gendered language,
which happens to be true for Spanish/Italian/Polish but isn't universal —
Tagalog (from the original locale list this feature grew out of) has no
grammatical gender at all. Adding a non-gendered language later means
revisiting the "always require sex for LOCALE != en" rule in
`routers/pod.py` rather than assuming it still applies.

## Supported locales

Single source of truth: `core/config.py`'s `SUPPORTED_LOCALES` dict. A
`LOCALE` value not in that dict (or a case mismatch, e.g. `ES` instead of
`es`) fails startup with a clear error rather than silently falling back to
English — a family that thinks they configured Spanish should never
discover Bede is still speaking English to their child.

| Code | Language | Status |
|------|----------|--------|
| `es` | Spanish (Español) | Backend directive shipped; `Login.tsx` translated; rest of UI pending |

Italian and Polish (and others) follow the same pattern once their content
is drafted and reviewed: add the code to `SUPPORTED_LOCALES`, add a
`locales/<code>.json` resource file, translate the remaining UI slices.

## Deliberately out of scope (for now)

A few pieces from the broader localization discussion were considered and
explicitly not built here, each for a concrete reason:

- **Peer-to-peer student chat translation (NMT/DeepL).** Bede has no
  student-to-student chat feature at all — a "pod" is one family's own
  children, each in a private 1:1 session with Bede, not a shared room. The
  low-latency NMT case for peer chat doesn't apply to a feature that
  doesn't exist.
- **NMT + MTQE hybrid pipeline for static UI strings.** That pipeline earns
  its complexity at the scale of tens of thousands of strings across many
  markets with ongoing churn. This app has a few hundred UI strings,
  translated once per language and mostly stable — a single AI-drafted pass
  reviewed for naturalness (as done for `Login.tsx`'s `es.json`) covers the
  same quality bar without a new vendor dependency.
- **A parallel safety-classifier model** (e.g. a self-hosted quantized
  Llama, or a third-party moderation API) scanning every localized
  response before it reaches the student. This app's whole deployment
  model is a family's own LAN with minimal ops (`CLAUDE.md`) — self-hosting
  a second inference model, or sending a child's conversation to a
  third-party API, cuts against that directly. `check_safeguarding()`
  (`services/ai_service.py`) already pattern-matches distress signals
  before a message reaches the model; extending its phrase lists per
  locale is a much smaller, LAN-compatible lift than a second model, and is
  the natural next step if this is revisited. Treat a dedicated
  classifier as its own separate infrastructure decision, not a
  localization sub-task.

## Translation quality bar

Translations here are AI-drafted (this app's own model, reviewed for
naturalness and terminology consistency across multiple passes before
shipping) rather than DeepL/NMT output or professionally human-translated.
That's a deliberate, accepted tradeoff for now, not an oversight — treat
each shipped locale as a solid first pass worth a native-speaker review
before it's the primary experience for a real family, particularly for
anything touching Bede's core persona or doctrinal content.
