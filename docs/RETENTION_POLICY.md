# Data Retention Policy

**Internal document — not published on any public page**, for the same
reason given in `docs/INFORMATION_SECURITY_POLICY.md`: it is not part of
the built site or demo (`scripts/build_pages_site.sh` never copies
`docs/`), and it exists to satisfy the amended FTC COPPA Rule's
requirement for a written policy stating, for each category of personal
information collected, the purpose of collecting it and a defined
deletion timeframe.

This document is the *policy statement* — what we've committed to and
why. `docs/DATA_RETENTION.md` is the *technical description* — what the
code actually does, with file/function references, kept in sync with
this policy but written for a developer or a self-hosting family rather
than as a compliance artifact. Where the two could drift, this policy is
the commitment and `docs/DATA_RETENTION.md` (plus the code it cites) is
how to verify it's being kept.

Responsible individual: see `docs/INFORMATION_SECURITY_POLICY.md` §2.
Last reviewed: 2026-08-03.

## Scope

This policy covers only data **Agnus Dei Technologies, LLC** itself
collects as operator of the public demo (`agnusdei.io/bede/`). A
self-hosted family's own retention of their own data, in their own
database, is that family's decision — see `docs/DATA_RETENTION.md`'s
"Your family's data" section for the technical facts of what's stored
there and how a family deletes it themselves. This company has no access
to that data and sets no retention policy over it.

## Categories, purpose, and deletion timeframe

| Category | Why we collect it | Deletion timeframe | How deletion happens |
|---|---|---|---|
| Session identity (learner's name, grade) — optional | Personalize the tone and content of the one demo session in progress | 6 hours from creation, or immediately on logout | Automatic: filtered out of every read past that age and opportunistically deleted on each new code issued (`core/demo_code_session.py`) |
| Current-unit note — optional | Let Bede anchor that one session on what the family is already learning, instead of only its own bundled curriculum | 6 hours from creation, or immediately on logout | Same mechanism as above |
| Church-tradition note — optional | Frame that one session's Scripture/Saints content consistently with the family's own tradition, instead of assuming one | 6 hours from creation, or immediately on logout | Same mechanism as above |
| The conversation itself | Generate that turn's response | **Never stored.** Exists only in transit and in-process memory for the duration of one turn | Nothing to delete — no row is ever created |
| Voice audio, if the microphone is used | Transcribe speech to text for that turn; synthesize Bede's spoken reply | **Never stored.** Processed for the live turn only | Nothing to delete — no row is ever created |
| Anonymized interaction-pattern signals (which tools fired, turn counts, subjects visited) | Understand, in aggregate, which teaching patterns work well | 30 days from creation | **Automatic background purge**, run every few hours for the life of the backend process (`main.py`'s periodic purge task calling `services/interaction_signals.purge_old_signals()`) |
| Diagnostic-preview rate-limit record (hashed visitor IP) | Prevent abuse of a public preview feature | Rolling 30-day window | Read-time filtering plus opportunistic cleanup (`core/diagnostic_preview_quota.py`) |
| Feedback message + optional reply email | Read and, if requested, reply to the feedback | **Never persisted to any database.** Exists only as one outbound email via Resend to the operator's own inbox | Nothing to delete — no row is ever created |

## What "deletion timeframe" means for a field with no database row

Several categories above are marked "never stored." That is a stronger
commitment than a short retention window, not a weaker one — it means
there is no row for this policy to schedule the deletion of, because
none is ever written. This distinction matters for anyone reviewing this
policy against the code: `core/database.py` defines exactly four demo-
related tables (`DemoCodeSession`, `DemoCodeUnitNote`, `DemoCodeFaithNote`,
`DemoInteractionSignal`) plus the rate-limit table above — nothing else
exists to hold a demo visitor's data, and in particular no table holds
conversation transcript text or audio for any `demo_code` session.

## A correction this policy documents rather than hides

As of 2026-08-03, this policy (and the demo's public Privacy Notice,
`demo/public/privacy.html`/`privacy.es.html`) previously named Anthropic
as the AI vendor processing the demo's conversation. The deployed demo
actually runs on `BEDE_ADAPTER_ORDER=openai,mistral` (`render.yaml`) —
OpenAI primary, Mistral as automatic failover — and did not depend on
Anthropic at all. Both the public notice and the vendor table in
`docs/INFORMATION_SECURITY_POLICY.md` §5 have been corrected to match.
This is recorded here, rather than silently fixed, because a retention/
disclosure policy that quietly corrects its own past inaccuracy without
a record of having done so is exactly the kind of drift this document
exists to prevent.

**Same day, a second, related change:** the failover vendor was made
genuinely configurable rather than fixed to Mistral. `render.yaml` now
lists `BEDE_ADAPTER_ORDER=openai,mistral,anthropic`, and
`core/provider_state.py`'s new secondary-adapter override
(`POST /admin/ai-provider/secondary`, see `docs/PROVIDER_ADAPTERS.md`)
lets the responsible individual (`docs/INFORMATION_SECURITY_POLICY.md`
§2) pick Claude over Mistral as this deployment's backup, live, without
a redeploy. Mistral remains the default failover unless that override is
set. Both the public notice and this policy's own vendor language were
written to name both possibilities rather than asserting one — see
`docs/INFORMATION_SECURITY_POLICY.md` §5's table.

Any future change to which AI vendor is primary OR secondary must update
this policy, `docs/INFORMATION_SECURITY_POLICY.md` §5, and the public
notice in the same change — that is the actual commitment this section
records, not just the one 2026-08-03 fix.

## Review schedule

Reviewed by the responsible individual (`docs/INFORMATION_SECURITY_POLICY.md`
§2) at least annually, and immediately whenever:
- A new category of data is collected by the demo.
- An existing retention window changes.
- The AI vendor or any other third-party processor changes (§ above).
