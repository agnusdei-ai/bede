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

**The public demo (`demo/`) now has its own equivalent toggle**, on
`CodeScreen` (its self-service "generate my code" entry screen — the closest
analog to `Login.tsx`, since the demo has no parent/child role choice).
It's a genuinely separate implementation, not a shared one: the demo is its
own Vite app with no dependency on `homeschool-tutor`'s code, so it got its
own `react-i18next` setup (`demo/src/i18n/`), its own resource bundles
(currently `codeScreen`/`common` namespaces only — the chat experience past
login isn't translated yet), and its own persistence (`sessionStorage`,
since the demo has no login-backed store the way `homeschool-tutor` does).
The one thing it *didn't* need was any backend change — `POST /auth/login`
already embedded a `locale` claim unconditionally for every role, `demo_code`
included, from the very first version of this feature; the demo frontend
just needed to start sending one.

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

**A real lapse this caught in production**: `<language>`'s own dedicated
block sits at the very end of the static prompt, and for most of a reply
that's enough — but real Spanish sessions showed Bede's response to
`sacred_rules` 9 (the `[START]` greeting) and 10 (the opening/closing
prayer) mixing languages mid-turn, composing the free-form greeting or
prayer in English before switching to Spanish for the actual Socratic
question. Both rules ask for spontaneous composition (a greeting, a
prayer) rather than answering something the child said — exactly the kind
of generation most likely to fall back on trained English devotional
patterns despite the instruction present elsewhere in the same prompt.
Fixed by adding a short, localized reminder directly at each of those two
rules (` — in Spanish (Español), not English`, computed once as
`_rule_lang_note` in `_build_static_prompt`, empty string for English so
that prompt stays byte-for-byte unchanged) — redundant reinforcement right
at the point of failure, not a replacement for `_locale_directive`'s own
full block. Covered by `tests/test_locale_directive.py`'s
"redundant reminder" tests, verified with the standard break-then-restore
discipline (temporarily removed the reminder, confirmed the new tests
actually fail, restored it).

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

**Speech recognition follows the session's own locale, not a hardcoded
default** (`SocraticChat.tsx` and the demo's `ChatScreen`, both via
`useHybridVoiceInput`'s `language` option): a real bug report showed voice
dictation ("listening") still recognizing speech as English inside a
Spanish session — the mic button worked and transcribed *something*, but
against the wrong language model, so a Spanish-speaking child's actual
words came back garbled. `useHybridVoiceInput` always supported a
`language` parameter (default `'en-US'`) and propagated it correctly to
the server Whisper transcription's language hint — the bug was purely that
neither call site ever passed anything but the default. Both now pass
`i18n.language === 'es' ? 'es-MX' : 'en-US'`. (At the time this was fixed,
that language hint reached both the native Web Speech API's `lang` and the
server Whisper fallback; browser-native SpeechRecognition was later
removed entirely in favor of server-side streaming transcription as the
sole path — see `docs/VOICE_SETUP.md` — but the locale-propagation fix
described here still applies unchanged to that single remaining path.)
Voice *biometric* verification (`VoiceVerification.tsx`, login-time
passphrase check) was never affected — it's acoustic speaker-embedding
comparison (`services/voice_auth.py`), not language-dependent
transcription.

**Currently translated:** `Login.tsx`, `TutorSession.tsx`, `SocraticChat.tsx`,
`ParentSetup.tsx`, `PodDashboard.tsx`, and `Progress.tsx` — every screen a
parent or child actually spends time on. Voice enrollment/verification and a
handful of smaller modal/settings components are **not yet translated**; each
is a follow-up slice using the same `t('namespace.key')` / `Trans` pattern
established here.

**The safeguarding crisis check is Spanish-aware too, not just Bede's own
replies** (`services/ai_service.py`'s `_SAFEGUARDING_PATTERNS`/
`safeguarding_response`, found during a pre-deployment adversarial-testing
pass — see `docs/SECURITY.md`): this one deliberately isn't gated behind the
session's locale the way everything else above is. It's checked
unconditionally on every message regardless of `LOCALE`, since a family can
be multilingual even in an English deployment and a missed crisis signal is
a far worse failure mode than an occasional false positive. The response
text *is* locale-aware (`routers/tutor.py` passes `auth.get("locale", "en")`
through), so a Spanish-speaking child gets the safety message in Spanish,
not just detected correctly.

**Deliberately still English regardless of locale:** the subject and
core-area taxonomy itself — "Morning Time," "Mathematics," "Science," and
similar labels from `types/index.ts`'s `SUBJECTS`/`CORE_AREAS` arrays, used
across `TutorSession`, `PodDashboard`, `ParentSetup`, `SocraticChat`, and
`Progress` alike. These are shared, single-source-of-truth labels referenced
by (at least) five files; translating the taxonomy itself — likely mirroring
the backend's own `SUBJECT_LABELS` locale-awareness — is a coherent, separate
piece of work, not something to do piecemeal inside one screen's translation
pass without the others drifting out of sync.

**The demo (`demo/src/i18n/`)** — its own, separate `react-i18next` install:
`CodeScreen` (title, name/grade fields, the privacy-notice paragraph via
`Trans`, the "Generate my code" button, and the toggle itself), `ChatScreen`
(header, "Learning Subject" label and the subject dropdown itself, the
break/session-concluded overlay, streaming/transcribing indicators, input
placeholders, mic tooltips), the header links (Ask Bede, Mastery preview,
Feedback, Finish demo), `ParentControlsMenu`, `ThemePicker`'s static labels,
`SessionEndedScreen`, and `DemoSummaryScreen` (including its end-of-demo
feedback survey — ratings, the feature dropdown, the improvement textarea,
the parent/guardian email opt-in) are all translated — this closes the gap
that originally let a visitor pick Español at the code screen and then land
in an English chat with only Bede's own replies actually in Spanish, since
fixed after real user reports of exactly that "Spanglish" experience.

**Still not yet translated, a disclosed boundary**: `DemoSandboxScreen`
(the "Ask Bede" direct-answer preview) and `DiagnosticViewScreen` (the
"Mastery preview" link) — both are optional, opt-in preview surfaces reached
via an extra click from the header, not the core chat flow every visitor
goes through — plus the separate small `FeedbackModal` reachable from the
header's "Feedback" link (distinct from `DemoSummaryScreen`'s own built-in
feedback survey, which *is* translated). `demo/src/api.ts`'s
`friendlyErrorMessage()` now also translates the network-error fallback at
every call site that passes it a `t` function (`CodeScreen` and
`DemoSummaryScreen`'s email-send handler); the remaining call sites across
`App.tsx` — mostly inside the still-untranslated sandbox/diagnostic screens
— keep their existing English fallback text, same disclosed boundary.

**`ConsentModal` and the static Privacy Notice page**: `ConsentModal.tsx` (the
"Before you begin" dialog gating entry to the demo — every visitor sees this,
not an optional preview surface) is now translated via the `consent.*` i18next
namespace, closing a gap that previously left this dialog, including its
COPPA parental-notice link text, in English even when Español was selected.
Its linked Privacy Notice — `demo/public/privacy.html`, a static page
deliberately outside the SPA/React-Router tree so it works standalone and
survives a JS failure (see `ConsentModal.tsx`'s own comment) — cannot be
translated at runtime the way a React component can; it now has a sibling
static file, `demo/public/privacy.es.html`, and `ConsentModal` links to
whichever one matches `i18n.language`. The Spanish privacy page is an
AI-drafted translation of the English page's content, not independently
drafted legal text, and is disclosed as such in a footnote on the page itself
pending native-speaker/legal review — same disclosure pattern as the
"Spanish beta testing" section in `docs/DEMO_HOSTING.md`. It is scoped to
this demo's existing English content only; it does not attempt to address
jurisdiction-specific children's-privacy regimes beyond COPPA (e.g. Mexico's
LFPDPPP, Spain's LOPDGDD) — see the "`es` is Mexican Spanish, not
pan-Hispanic-neutral" section below for why the demo's `es` locale is scoped
to Mexico specifically, which is the most directly relevant regime if that
work is taken on.

Subject labels specifically (`demo/src/api.ts`'s `SUBJECT_LABELS`) are
locale-aware via a `subjects.*` i18next namespace at the one place they're
rendered (`ChatScreen`'s subject `<select>`) — this is narrower than fully
solving the "subject/core-area taxonomy stays English regardless of locale"
gap described above for `homeschool-tutor` (which has five call sites to
keep in sync, not one), but establishes the same key-naming convention
(`subjects.<Subject enum value>`) that a future pass there could reuse.

## `es` is Mexican Spanish, not pan-Hispanic-neutral

**This is a deliberate scope choice, not a default.** The app has exactly
one Spanish locale — there's no `es-MX` vs. `es-ES` split — and that single
locale is intentionally calibrated for a Mexican Catholic family
specifically, not a generic "any Spanish-speaking country" experience. A
Spain, Argentine, or other Spanish-speaking family using the same toggle
gets the same Mexico-framed content. This mirrors how the English-locale
experience was never neutral either — it already reflects one particular
tradition (Mater Amabilis, an American Catholic homeschool curriculum) — but
it's called out explicitly here since it wasn't originally an intentional
design decision the way it is now.

`services/ai_service.py`'s `_guadalupe_note` (wired into
`_build_subject_prompt`, `Subject.saints` and `Subject.morning_time` only)
is the concrete expression of this: when `locale == "es"`, Bede is told Our
Lady of Guadalupe and St. Juan Diego are *this family's own* patroness and
saint, not one devotion among many, and given verified facts (the December
9, 1531 first apparition at Tepeyac hill outside Mexico City, the December
12, 1531 tilma image, St. Juan Diego's July 31, 2002 canonization by Pope
St. John Paul II as the first Indigenous saint of the Americas) to draw on
naturally rather than from unverified model memory — consistent with
`docs/CONTENT_CONTRIBUTING.md`'s sourcing standard, cross-checked across
multiple independent sources. This doesn't replace or crowd out the
liturgical calendar or the Faith and Life catechism scope
(`services/catalog_service.py`) — Bede still ranges across the Church's full
calendar of saints; it's context to reach for when it's the natural fit,
the same way an English-locale session already draws on whichever
saint/feast fits the day.

**Poetry co-study resolved a different way — no Spanish-language catalog
entry at all, on purpose.** The two best-known Guadalupan hymns — "La
Guadalupana" ("Desde el cielo...") and "Las Mañanitas a la Virgen de
Guadalupe" — are both mid-20th-century compositions (1940s and 1950s
respectively) still under copyright, not the pre-1929 public-domain
material `services/poetry_catalog.py` requires (see
`docs/CONTENT_CONTRIBUTING.md`'s "one hard rule"). Older material exists —
Sor Juana Inés de la Cruz's 17th-century villancicos touch on Guadalupe,
safely public domain by any measure — but a clean, exact, cross-verifiable
primary-source text wasn't found in the research pass that first raised
this. Rather than keep chasing sourcing for Spanish (and needing to repeat
that chase for every future locale — Tagalog, Italian, Polish), a live
Spanish session surfaced a cleaner fix: `poetry_catalog.py`'s English poem
was firing regardless of locale, so a Spanish reply would quote a real
English poem verbatim mid-sentence — a "Spanglish" kink a parent reported
directly.

`_native_poetry_note` (`services/ai_service.py`, wired into
`_build_subject_prompt` in place of `poetry_catalog.py`'s quotation
whenever `locale != "en"`) is the fix: Bede composes a short original
devotional reflection or a few original lines of verse, natively in the
session's language, never attributed to a real poet or presented as an
existing published work — the same native-generation principle
`_locale_directive` already applies everywhere else Bede speaks. This needs
no stored or sourced content and scales to any future locale with zero
content-curation work, at the cost of a real feature difference stated
plainly: only English sessions get Bede quoting a real, historically
attributed poem verbatim; every other locale gets Bede's own composition
instead. `prayer_catalog.py`'s prayer recitation is unaffected by any of
this — it already carries verified Spanish text for the Church's own
traditional prayers (Our Father, etc.), a different case from quoting an
individually-authored poem.

## Troubleshooting: Bede reverts to English (or mixes languages mid-sentence) partway through a Spanish session

Reported directly, with a live trace: a parent noticed Bede in `es` mode
"reverting to bilingual / English modality" — one whole turn in plain
English (`"What was the first clue that helped you notice that?"`), and a
separate turn mixing English into the middle of an otherwise-Spanish
sentence (`"...Eso es un gran regalo. I noticed you saw that reconocer que
es un hijo único de Dios que ama su fe."`). Two distinct, real causes, not
one:

1. **A 100%-reproducible server-side bug, not a model lapse.** The exact
   English sentence from the first example is one of
   `_CELEBRATION_FALLBACK_QUESTIONS`' four hardcoded strings
   (`services/ai_service.py`) — `stream_tutor_response`'s own code appends
   one of these, with no model involved at all, whenever a turn ends on a
   questionless tool (`celebrate_discovery`/`connect_to_faith`) without the
   model supplying its own follow-up question (see the `test_ai_service_streaming.py`
   tests for why that fallback exists in the first place: a guarantee, not a
   request, against the turn just stopping with nothing for the child to
   respond to). Both fallback lists were hardcoded English-only with no
   locale awareness whatsoever — unlike everywhere else in this file, which
   threads `locale` through explicitly, this one code path broke a Spanish
   session's immersion unconditionally on whichever turn happened to trigger
   it. **Fixed** by keying both lists by locale (`{"en": [...], "es": [...]}`,
   falling back to `"en"` for any locale without its own translation yet)
   and threading `locale` into which list `random.choice` draws from.
2. **A likely model-generation contributor**, matching the "Spanglish kink"
   pattern from the poetry catalog section above: `celebrate_discovery`'s
   own tool `description` used to contain a literal, quotable English
   example sentence — `'I noticed you connected X to Y'` — as guidance for
   what "specific praise" looks like. The reported mixed-language text
   (`"I noticed you saw that..."`) echoes that exact phrasing closely enough
   that the tool description itself is the likely source the model drew on
   while composing its Spanish `specific_insight`/`encouragement` fields.
   **Fixed** by rephrasing the description to state the underlying principle
   (specific beats generic) without a literal English sentence to
   pattern-match against — no change to the guidance's substance, so English
   sessions are unaffected.

Both fixes are localized to `services/ai_service.py`; no frontend change was
needed. `_locale_directive`'s own carve-out ("Tool names and any structured
data you produce stay exactly as documented below, in English") was never
meant to cover prose field VALUES like `specific_insight`/`encouragement` —
only the tool's name and genuinely structural data (e.g. `elements` lists,
enum values) — but the ambiguity was real enough that it's worth stating
explicitly here for the next person debugging a similar report: any tool
whose field values render as user-facing text (`celebrate_discovery`,
`connect_to_faith`, `offer_socratic_hint`, `show_visual_aid`,
`invite_handwriting`'s `prompt`) must have those values written in the
session's own language like everything else Bede says — only the tool
*name* itself and non-prose structured values are the English exception.
Other tool descriptions (`request_narration`, `invite_handwriting`) still
carry their own literal English example phrases and weren't touched here —
no evidence tied them to this specific report, and `invite_handwriting`'s
description in particular is large and carefully iterated on; a future
mixed-language report tied to one of those tools would be the trigger to
revisit them the same way.

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
  locale (now done for Spanish — see `docs/SECURITY.md`) is a much
  smaller, LAN-compatible lift than a second model.

  **The dedicated-classifier decision this deferred has since been
  made** (`services/moderation.py`, AIUC-1 B005 — see `docs/SECURITY.md`),
  and it sidesteps both objections above by construction: it classifies
  through the same adapter-resolved client every tutoring turn already
  uses (Anthropic, OpenAI, Mistral, or a local self-hosted model, whichever
  this deployment has configured — see `docs/PROVIDER_ADAPTERS.md`) — no
  second model to host, no new vendor receiving a child's conversation.
  Locale isn't threaded through it at all; it classifies content categories (self-harm,
  violence, sexual content, hate speech, prompt injection), not language,
  so it works identically regardless of which locale a session runs in.

## Translation quality bar

Translations here are AI-drafted (this app's own model, reviewed for
naturalness and terminology consistency across multiple passes before
shipping) rather than DeepL/NMT output or professionally human-translated.
That's a deliberate, accepted tradeoff for now, not an oversight — treat
each shipped locale as a solid first pass worth a native-speaker review
before it's the primary experience for a real family, particularly for
anything touching Bede's core persona or doctrinal content.
