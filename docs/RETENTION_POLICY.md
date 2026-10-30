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
Last reviewed: 2026-08-04.

## Scope

This policy covers only data **Agnus Dei Technologies, LLC** itself
collects as operator of the public demo (`agnusdei.ai/bede/`, also
reachable at `agnusdei.io/bede/` — the same build on the same Worker). A
self-hosted family's own retention of their own data, in their own
database, is that family's decision — see `docs/DATA_RETENTION.md`'s
"Your family's data" section for the technical facts of what's stored
there and how a family deletes it themselves. This company has no access
to that data and sets no retention policy over it.

## Categories, purpose, and deletion timeframe

| Category | Why we collect it | Deletion timeframe | How deletion happens |
|---|---|---|---|
| Session identity (learner's name, grade) — optional | Personalize the tone and content of the one demo session in progress | 6 hours from creation, or immediately on logout | Automatic: filtered out of every read past that age and opportunistically deleted on each new code issued (`demo_code_sessions`, `core/demo_code_session.py`) |
| Current-unit note — optional | Let Bede anchor that one session on what the family is already learning, instead of only its own bundled curriculum | 6 hours from creation, or immediately on logout | Same mechanism as above (`demo_code_unit_notes`, encrypted) |
| Church-tradition note — optional | Frame that one session's Scripture/Saints content consistently with the family's own tradition, instead of assuming one | 6 hours from creation, or immediately on logout | Same mechanism as above (`demo_code_faith_notes`, encrypted) |
| Session setup — optional | Let a visitor configure their own demo session the way a parent configures a real one (subjects, what the family is already reading, what helps this child), instead of showing a fixed demo | 6 hours from creation, or immediately on logout | Same mechanism as above (`demo_code_parent_configs`, encrypted) |
| Work-ledger record (which skill was worked, how much help it took, what Bede noticed about the work) | Show the visitor what their learner actually completed during the session — the demo's own copy of the work ledger a real family gets | 6 hours from creation, or immediately on logout | Same mechanism as above (`demo_code_activity_logs`, encrypted) |
| The conversation itself | Generate that turn's response | **Never stored.** Exists only in transit and in-process memory for the duration of one turn | Nothing to delete — no row is ever created |
| A photo or scan of a graded quiz, if a parent or guardian uses the optional Practice Coach preview (`/practice-demo/*`) | Read into a worksheet of questions, answers and the teacher's marks so Bede can suggest a few minutes of practice. Sent to OpenAI (or, only if OpenAI is briefly unavailable, the configured backup provider) after a per-upload tick that names the provider; nothing is sent without it. Capped at 3 uploads of up to 3 pages per demo session, checked before any model call | **The page is never stored** by us, in a database or a file. What is read from it and the practice set drafted from that are kept **in the server's memory only** (`services/practice/demo_store.py`), never in a table, for at most 6 hours, or until logout | Automatic: dropped on logout (`end_session()`), by the sweep run on each new code (`generate_code()`), and by a 6-hour TTL on every access. No row is ever created, so there is nothing for a table purge to schedule |
| Voice audio, if the microphone is used | Transcribe speech to text for that turn (sent to OpenAI, see below); synthesize Bede's spoken reply | **Never stored**, by us or by OpenAI. Passes through our server for the live turn only | Nothing to delete — no row is ever created |
| Anonymized interaction-pattern signals (which tools fired, turn counts, subjects visited) | Understand, in aggregate, which teaching patterns work well | 30 days from creation | **Automatic background purge**, run every few hours for the life of the backend process (`demo_interaction_signals`, `main.py`'s periodic purge task calling `services/interaction_signals.purge_old_signals()`). This is the one demo category that deliberately outlives the session rather than being deleted at logout — aggregating patterns across many sessions is its whole purpose. It is keyed by an unreversible HMAC of the code rather than the code itself, so it cannot be joined back to a visitor |
| Diagnostic-preview rate-limit record (hashed visitor IP) | Prevent abuse of a public preview feature | Rolling 30-day window | Read-time filtering plus opportunistic cleanup (`diagnostic_preview_uses`, `core/diagnostic_preview_quota.py`) |
| Feedback message + optional reply email | Read and, if requested, reply to the feedback | **Never persisted to any database.** Exists only as one outbound email via Resend to the operator's own inbox | Nothing to delete — no row is ever created |

## What "deletion timeframe" means for a field with no database row

Several categories above are marked "never stored." That is a stronger
commitment than a short retention window, not a weaker one — it means
there is no row for this policy to schedule the deletion of, because
none is ever written. This distinction matters for anyone reviewing this
policy against the code: `core/database.py` defines exactly six demo-
related tables (`DemoCodeSession`, `DemoCodeUnitNote`, `DemoCodeFaithNote`,
`DemoCodeParentConfig`, `DemoCodeActivityLog`, `DemoInteractionSignal`) plus
the rate-limit table
above — nothing else exists to hold a demo visitor's data, and in
particular no table holds conversation transcript text or audio for any
`demo_code` session. The one other place a demo visitor's data can sit is the
Practice Coach's in-memory workspace in the Practice Coach row above. It is
not a table, is never written to disk, and is listed here so this paragraph
is not read as the whole inventory.

**This count was wrong until 2026-08-14, and is recorded rather than
quietly corrected**, for the same reason the vendor correction below is.
The policy said "exactly four" and omitted `DemoCodeActivityLog`, the
demo's work ledger, which has been collected since it shipped. Nothing
was undisclosed to visitors — the public Privacy Notice
(`demo/public/privacy.html`), the demo's own consent screen, and
`docs/DATA_RETENTION.md` all described it, and its retention was always
the same 6-hour window as the rest — but this document is the artifact
that has to enumerate every category, so an omission here is a real
defect in the policy even where the practice was correct.
`homeschool-api/tests/test_coppa_compliance.py` now fails if a demo table
exists in the code without a row in the table above, so the next one
cannot go unnoticed the same way.

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

**2026-08-04 — microphone audio now goes to OpenAI, not only to our own
server.** Until this date the demo transcribed voice input in its own
backend process (faster-whisper), and this policy and the public notice
both said so. That backend now sends the audio to OpenAI's transcription
API instead (`TRANSCRIPTION_PROVIDER=openai` in `render.yaml`), so a new
category of a visitor's data reaches a third party and both documents have
been updated to say so plainly rather than leaving the old wording to go
quietly stale.

The reason is a memory failure rather than a preference: faster-whisper's
`ctranslate2` backend imports torch (~480MB of RSS on import alone)
whenever torch is present, which put `bede-demo-api` at 642MB against the
free plan's 512MB cap and got it OOM-killed repeatedly, taking every
in-flight child's voice turn down with it. This is scoped to the public
demo only. A family's self-hosted instance keeps transcribing locally —
that is the entire point there, and `core/config.py`'s default is
unchanged, so a family has to opt in by name to change it.

Note what this does and does not change about retention: the audio is
still never stored, by us or by OpenAI, which processes it as our service
provider for that one turn and does not use it to train its models. What
changed is **who processes it**, not **how long anyone keeps it**.

## Application logs and the audit log (self-hosted and hosted deployments)

These two stores sit outside the categories table above because they are
written by the operating system and the application's security trail rather
than by a demo visitor's session. Both are operator-configured. The values
below are the code's defaults and the recommendations this repository makes,
not a retention commitment that any particular installation has accepted.

**Application logs (operational output).** The backend writes to standard
output at INFO level, and the container runtime (Docker, or the hosting
platform) keeps that output under its own log driver. Retention is therefore
set by the operator, not by this repository:

- *Docker `json-file` driver, the default:* no rotation and no maximum size
  unless the operator sets `max-size` and `max-file`. Left at default, logs
  persist until the host's disk is cleaned. The operator should set both
  options in the compose deployment.
- *Hosted platforms:* retention is the platform's own, and the operator must
  confirm it in that platform's settings. This repository does not hold that
  value.
- *Recommended default: 30 days* for application logs, with the rotation
  options above. This is a recommendation for the operator to adopt or change,
  recorded as an operator decision and not as a value enforced by the code.

What the logs contain, after the log-redaction change (COPPA readiness C-15
and C-16): a learner is identified only by a keyed reference, `learner:` followed
by 12 hex characters of an HMAC of the name under a key derived from the
deployment's `SECRET_KEY`. The reference is stable within one installation,
so an operator can tell that two lines concern one learner, but it does not
reveal the name, and it cannot be reversed without that key. Exception text
is reduced to its type, with any learner name it carries replaced. On
child-facing paths (the tutoring stream and the lesson-bookmark write) only
the exception's type and the frame where it was raised are logged, never the
message and never a traceback, because the message can contain the child's own
words. The `learner:` reference is still a persistent identifier under COPPA's
definition, so application logs remain in scope of this policy and of the
operator's retention choice. The redaction removes the child's name and words,
not the need to set a retention period.

**Audit log (`audit_log`, encrypted).** Every security-relevant event is
recorded as one encrypted row. Two settings govern it:

| Setting | Default | What it does |
|---|---|---|
| `AUDIT_RETENTION_DAYS` | 365 | Rows older than this are deleted |
| `AUDIT_IP_TRUNCATE_DAYS` | 30 | Rows older than this keep the event, but their stored IP is replaced by a keyed pseudonym (`ip-pseudonym:` plus 16 hex characters) and their user-agent is cleared |

The 365-day value is a **placeholder pending an owner decision**. It is the
default in code so that an installation is never left with an unbounded log,
and it is not a considered retention period for a children's service. The
owner should set it, and record the decision in `docs/DECISIONS.md`, before any
hosted or pilot deployment relies on it.

The 30-day IP window is the minimisation step. It keeps the address for the
period in which a security review is realistic, and afterwards keeps the
event, its outcome, its role and its detail, and still lets an investigator
see that two events came from one device. The pseudonym is keyed on
`SECRET_KEY`, so the mapping cannot be rebuilt from the database alone. A
user-agent string can also identify a device, so it is cleared on the same
schedule rather than kept.

Known limits, stated plainly:

- Student deletion does not remove audit rows. The audit log is kept
  deliberately so that a deletion is itself evidenced. Some audit entries
  record a learner's name in their encrypted payload, and those names remain
  until the audit retention window passes. Whether those names should also be
  pseudonymised is an open owner decision.
- Minimisation runs in the periodic purge task (every six hours, `main.py`).
  A deployment that is shut down for longer than the window applies the
  minimisation on the first periodic pass after it starts again.
- The audit log has no hash chain, so a row that is changed inside the
  database is not detectable from the log itself. The database's own access
  controls and backups are the protection for that.

## Review schedule

Reviewed by the responsible individual (`docs/INFORMATION_SECURITY_POLICY.md`
§2) at least annually, and immediately whenever:
- A new category of data is collected by the demo.
- An existing retention window changes.
- The AI vendor or any other third-party processor changes (§ above).
