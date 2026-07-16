# Localization

Bede supports running a deployment in a language other than English. This
page covers what's implemented, what's deliberately deferred, and why —
see the architecture discussion in this repo's history for the fuller
reasoning behind each call.

## Scope model: one locale offered per deployment, chosen per-login

**This changed from the original design.** The first version of this
feature made `LOCALE` a hard, deployment-wide lock — one self-hosted family
instance ran in exactly one language, period, the same way `PARENT_PASSWORD`
or `CHILD_PIN` are configured once and never switched. That's no longer how
it works.

`LOCALE` (backend env var) now controls something narrower: **which single
non-English locale this deployment *offers* as a choice**, not which
language every session is forced into. The actual language a given session
runs in is picked at **the login screen itself** — Login.tsx's
English/Español toggle, shown only when `GET /auth/locales` reports this
deployment has opted in — and applied instantly to that login (both the UI
chrome and Bede's own conversation), independent of which student is
logging in or what they picked last time. A bilingual household can have
one child log in in English one day and Spanish the next; the choice lives
with the login, not the student's profile. `LOCALE=en` (the default) means
the toggle never renders at all — every session is English, byte-for-byte
identical to a deployment that never heard of this feature.

The public demo (`demo/`) still doesn't have this — it's a different
problem (one deployment serving visitors worldwide at once, no login
credential to attach a choice to) and remains English-only, out of scope
for this pass.

## What's implemented

**Backend — a per-login JWT claim, not a global setting**
(`routers/auth.py`'s `login()` and the new public `GET /auth/locales`):
`POST /auth/login` accepts an optional `locale` field, validates it against
whatever single locale `core/config.py`'s `LOCALE` setting has opted this
deployment into (anything else silently falls back to `"en"` — a stale or
tampered client value should never be able to block someone's login), and
embeds it as a `locale` claim in the issued JWT. The parent-MFA pending →
final token exchange (`routers/mfa.py`) carries the claim through so
completing a security key/TOTP check a moment after the password step
doesn't silently reset it to English. Every downstream request on that
token — `/tutor/chat`, `/tutor/summary`, `/email-summary` — reads
`auth.get("locale", "en")` and threads it through as a plain function
parameter (`services/ai_service.py`'s `_locale_directive`,
`_build_static_prompt`, `_build_subject_prompt`, `stream_tutor_response`,
`generate_session_summary`, and `services/prayer_catalog.py`'s
`prayer_note`) rather than reading a global `settings.locale` the way the
original version did.

**Native generation, not translation** (unchanged principle,
`_locale_directive`): when a session's locale is non-English, Bede's system
prompt gains one instruction telling Claude to converse with the student
directly in that language — deliberately **not** a translation pipeline,
no English draft generated and then translated. Claude is natively
multilingual, so asking it to write in Spanish from the start costs nothing
extra in latency (same single generation pass as English today, still
streamed token-by-token over the existing SSE pipeline) and — unlike a
machine-translation engine — it can simultaneously apply the grade-level
reading-complexity judgment `_STAGE_GUIDANCE` already asks for. An NMT
engine translates exactly what it's given; it can't "simplify this to a
3rd-grade reading level" on its own. Tool names and structured data
(`request_narration`, `celebrate_discovery`, etc.) stay in English
regardless of locale — the frontend matches on the literal tool name
string, so only Bede's own spoken/written words change language.

`routers/pod.py`'s requirement that every student have `SessionConfig.sex`
on file still keys off `LOCALE != "en"` (whether the toggle is *offered* at
all) rather than any per-session state — since any student could land in a
non-English session on any given login once the toggle exists, every
student needs sex on file the moment it's enabled, not just the ones a
parent expects to use it.

**Frontend — `react-i18next`, switched at runtime**
(`homeschool-tutor/src/i18n/`): both resource bundles (`locales/en.json`,
`locales/es.json`) are always loaded together, regardless of build
configuration — `i18n.changeLanguage()` switches between them instantly,
client-side, with no network request. `VITE_LOCALE` still exists but now
only sets the *very first* paint's language, before Login.tsx's own
`GET /auth/locales` call and the persisted session store have had a chance
to run — it's an initial default, not a lock. `Login.tsx` fetches the
available locale(s) on mount, renders the toggle only when the list is
non-empty, and calls `i18n.changeLanguage()` the moment a language is
tapped — so the login screen itself switches live, before the credential
is even submitted, not just once inside the tutoring session. The choice
is sent on the login request itself and persisted in `sessionStore.ts`
(`locale` field) so a page refresh mid-session restores it
(`guards/AppShell.tsx`) instead of silently reverting to English.
`src/i18n/locales.test.ts` guards against a common real failure mode — a
string added to `en.json` and silently forgotten in `es.json`, which
i18next doesn't error on, it just falls back to showing the raw key to the
parent. The test checks key parity, non-empty values, and matching
`{{interpolation}}` variables between locales.

**Currently translated:** `Login.tsx`, `TutorSession.tsx`, `SocraticChat.tsx`,
`ParentSetup.tsx`, `PodDashboard.tsx`, and `Progress.tsx` — every screen a
parent or child actually spends time on. Voice enrollment/verification and a
handful of smaller modal/settings components are **not yet translated**; each
is a follow-up slice using the same `t('namespace.key')` / `Trans` pattern
established here.

**Deliberately still English regardless of locale:** the subject and
core-area taxonomy itself — "Morning Time," "Mathematics," "Science," and
similar labels from `types/index.ts`'s `SUBJECTS`/`CORE_AREAS` arrays, used
across `TutorSession`, `PodDashboard`, `ParentSetup`, `SocraticChat`, and
`Progress` alike. These are shared, single-source-of-truth labels referenced
by (at least) five files; translating the taxonomy itself — likely mirroring
the backend's own `SUBJECT_LABELS` locale-awareness — is a coherent, separate
piece of work, not something to do piecemeal inside one screen's translation
pass without the others drifting out of sync.

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
| `es` | Spanish (Español) | Login-time toggle + backend directive shipped; `Login.tsx` translated; rest of UI pending |

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
