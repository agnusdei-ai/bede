# Written Information Security Policy

**Internal document — not published on any public page.** This is not
served by the marketing site or the demo (neither `scripts/build_pages_site.sh`
nor `wrangler.jsonc` includes `docs/`), and is distinct from the public-facing
[`docs/SECURITY.md`](SECURITY.md) and [`docs/INCIDENT_RESPONSE.md`](INCIDENT_RESPONSE.md),
which describe the product's security architecture and incident process to
developers and self-hosting families. This document exists specifically to
satisfy the amended FTC COPPA Rule's requirement for a written information
security program covering personal information the operator itself collects
and controls, naming who is responsible for it.

Last reviewed: 2026-08-04.

## 1. Scope

This policy covers only the personal information **Agnus Dei Technologies,
LLC** itself collects and controls as the operator of `agnusdei.io` and its
public demo (`agnusdei.io/bede/`, backed by the `bede-demo-api` service).

It does **not** cover a self-hosted family's own deployment of Bede
(`docker-compose.yml`, run on that family's own hardware) — that data is
never transmitted to, held by, or accessible to Agnus Dei Technologies at
all, so there is nothing here for this company to secure. Self-hosting
families should refer to `docs/PRODUCTION_SETUP.md` and `docs/SECURITY.md`
for hardening their own instance; that is their own responsibility as
operator of their own deployment, not covered by this policy.

## 2. Designated responsible individual

Per COPPA's requirement that a covered operator designate an individual
accountable for its information security program:

> **Kristian Gonzalez, Founder, Agnus Dei Technologies, LLC**
> Email: info@agnusdei.ai
> Address: 112 Civita Rd., Liberty Hill, TX 78642

This individual is responsible for: maintaining and enforcing this policy,
reviewing it on the schedule in §7, approving any change to which
third-party vendors process personal information from the demo (see §5),
and leading the response to any security incident per
`docs/INCIDENT_RESPONSE.md`.

## 3. What is collected, and where it actually lives

Everything below is scoped to the public demo, since the marketing site
outside `/bede/` collects nothing (see `site/privacy/index.html`, the
public-facing tracker/data-disclosure inventory this policy's technical
claims are drawn from). `docs/RETENTION_POLICY.md` states purpose and
retention for each category in full; this section covers how it's
protected while it exists.

| Data | Storage | Protected how |
|---|---|---|
| Demo session identity (name, grade) | `demo_code_sessions` table, Postgres (`bede-demo-db` on Render) | **Plaintext, by design** (see `homeschool-api/core/database.py`'s `DemoCodeSession` docstring) — treated as a self-chosen demo alias, not a real identity, and bounded by a 6-hour retention window (§4) rather than encryption. This is a deliberate, documented tradeoff, not an oversight. |
| Current-unit note (optional) | `demo_code_unit_notes` table | Plaintext, same reasoning as above; sanitized against injection at write and render time. |
| Church tradition note (optional) | `demo_code_faith_notes` table | Plaintext, same reasoning as above. This is the one field the demo's own Privacy Notice calls out as a sensitive category needing extra care — the control here is the short, fixed retention window (§4), not encryption. If this policy's risk tolerance changes, encrypting this column is the concrete next step (see §8). |
| The conversation itself, and any voice audio | Never written to any database | Exists only in transit / in-process memory for the duration of one turn, then discarded. There is no row to protect because none is created. Voice audio additionally transits to OpenAI for transcription (§5) and is not stored there either. |
| Anonymized interaction-pattern signals | `demo_interaction_signals` table | Encrypted at rest (`encrypt_json`, AES-256-GCM, same primitive as the main product's `MasteryProfile`), keyed by an HMAC-SHA256 hash of the session code rather than the code itself. |
| Diagnostic-preview rate-limit records | `diagnostic_preview_uses` table | Holds an HMAC-SHA256 hash of the visitor's IP, not the IP itself — chosen specifically because this table moved a value that used to live only in an ephemeral in-memory dict onto durable storage (see that table's own docstring in `core/database.py`). |
| Feedback message + optional reply email | Not persisted to any database | Exists only as one outbound email via Resend, then is gone from anything this company operates. |

## 4. Transport security

- The static marketing site and demo frontend are served over HTTPS via
  Cloudflare's edge (Cloudflare Workers Static Assets, `wrangler.jsonc`).
- The demo's backend (`bede-demo-api`) is a Render web service; Render
  terminates TLS for all traffic to it.
- The self-hosted product's own reverse proxy (`Caddyfile`) handles TLS
  for a family's own deployment — outside this policy's scope (§1), noted
  here only for completeness.

This policy does not claim to have independently audited Cloudflare's or
Render's own infrastructure security — both are established providers
whose own security posture is documented on their respective trust/
compliance pages. Agnus Dei Technologies configures and uses these
platforms; it does not operate the physical or network infrastructure
beneath them.

## 5. Third-party vendors with access to personal information

Only vendors actually reachable by live code, per `render.yaml` and
`services/adapters/router.py`, are listed — not every adapter that
exists in the codebase but isn't configured for this deployment.

| Vendor | What it receives | Purpose |
|---|---|---|
| OpenAI | Conversation text (primary AI provider); Bede's reply text (text-to-speech); **microphone audio, when a visitor uses voice input** (speech-to-text) | Generate and voice Bede's tutoring responses, and turn a visitor's speech into text |
| Mistral | Conversation text, only on automatic failover if OpenAI errors — **default backup** | Backup AI provider, live circuit-breaker failover |
| Anthropic (Claude) | Conversation text, only on automatic failover if OpenAI errors — **only if configured as the backup instead of Mistral** (`ANTHROPIC_API_KEY` set AND selected via `core/provider_state.py`'s secondary override) | Alternate backup AI provider, same mechanism as Mistral |
| Resend | Feedback message + optional reply email | Deliver the feedback form to the operator's own inbox |
| Render | All of the above, as the host running `bede-demo-api` and its Postgres database | Infrastructure hosting |
| Cloudflare | Static site/demo asset delivery | Infrastructure hosting (no personal information reaches this layer — it serves static files only) |

Microphone audio was added to OpenAI's row on 2026-08-04. Before that date
this deployment transcribed voice input in its own backend process
(faster-whisper) and no audio left our infrastructure. It now goes to
OpenAI's transcription API (`TRANSCRIPTION_PROVIDER=openai` in
`render.yaml`) because the local model could not fit the host's memory
limit — `ctranslate2` imports torch at ~480MB of RSS, which OOM-killed
`bede-demo-api` repeatedly. Scoped to this public demo only: a family's
self-hosted instance still transcribes locally, and `core/config.py`'s
default is unchanged. See `docs/RETENTION_POLICY.md`'s changelog.

The backup slot is genuinely configurable, not a hardcoded claim: `render.yaml`'s
`BEDE_ADAPTER_ORDER=openai,mistral,anthropic` lists all three as candidates,
and `POST /admin/ai-provider/secondary` (`routers/admin.py`) is how the
responsible individual (§2) would actually switch the backup from Mistral
to Claude on this deployment — live, no redeploy — if that vendor
relationship changes (see `docs/PROVIDER_ADAPTERS.md`'s "Choosing the
failover itself" section). Changing which vendor is primary OR secondary
is a change this policy requires the designated individual (§2) to review,
since it changes the answer to "who processes a child's conversation" —
the exact drift this policy exists to catch (see the 2026-08-03 correction
described in `docs/RETENTION_POLICY.md`'s changelog and
`demo/public/privacy.html`, where the notice previously named the wrong
vendor entirely).

## 6. Operational access control

This is currently a small operation with a single individual (§2) holding
production access (Render dashboard, Cloudflare dashboard, and any
database credentials). There is no role-based access system to describe
yet because there is currently no second person to scope access for. If
that changes, this section must be updated before a second person is
granted any production credential, to state: who has access, to what,
and why.

## 7. Review schedule

This policy is reviewed by the designated individual (§2) at least
annually, and immediately after any of the following:
- A change to which third-party AI or infrastructure vendor processes
  personal information (§5).
- A change to what the demo collects, or how long it retains it
  (`docs/RETENTION_POLICY.md`).
- A confirmed security incident (`docs/INCIDENT_RESPONSE.md`).
- The addition of a second person with production access (§6).

## 8. Known gaps and planned improvements

Documented honestly rather than omitted, per this company's own standard
that an overstated disclosure is worse than an admitted gap:

- **Demo session fields are plaintext, not encrypted at rest** (§3). The
  current control is a short, enforced retention window rather than
  encryption. Encrypting these columns (matching `MasteryProfile`'s
  pattern) would close this gap and is the most concrete open item this
  policy identifies.
- **No formal access log review process** exists yet beyond the audit log
  the self-hosted product itself has (`core/audit.py`) — the demo backend
  does not currently maintain an equivalent operator-side access log for
  who queried `bede-demo-db` and when, since access is currently limited
  to the single individual named in §2.
