# Parent Setup: Connections and readiness (design, not built)

**Status: proposal for owner review. Nothing here is implemented.** The aim is
that after installation a parent can see and manage Bede's outside connections
(tutoring service, voice) from Parent Setup instead of editing `.env`. The
hard part is not the screen, it is letting a browser cause a secret to be
stored. That needs agreement first.

## What exists today

`GET /admin/ai-provider` (+ `POST`) switches among already-credentialed
adapters and stores only a name, never a credential
(`core/provider_state.py`). `GET /tutor/voice` reports whether speech is
configured. Credentials live only in `.env`, read at start. There is no write
path for a key, deliberately.

## Proposed states, per connection

`missing` (no key), `configured_not_verified` (key present, never tested),
`verified` (one low-cost test succeeded, with a time), `rejected` (the service
refused the key), `unavailable` (could not reach it), `off` (deliberately
disabled). The UI never says a connection works unless it is `verified`, and a
verification is a user-pressed action, never automatic.

## Decisions needed before any code

1. **Where a key is stored.** Options: (a) keep `.env` only and have the app
   show state plus exact instructions (no write capability, simplest, no new
   attack surface); (b) an encrypted database row under the existing
   `DATA_KEY` hierarchy, with `.env` as fallback. Recommendation: (a) first,
   (b) only if (a) proves too hard for families, because (b) makes the API a
   place secrets are written.
2. **Who may write.** Server-enforced elevated parent only
   (`require_elevated_parent`, the same gate as the AI-provider switch), never
   a child, educator or demo role; school/COPPA enforcement and the offline
   boundary still apply and can refuse.
3. **What never leaves the server.** No secret in any response (replace and
   remove, never display or echo), none in browser storage, logs, audit detail
   or error text; the audit row records "voice key replaced", not the value.
4. **Recovery.** A failed or rejected replacement must keep the previous
   working key until the new one verifies; "remove" returns to `missing`
   without breaking text-only lessons. A lost-password parent recovers through
   the existing 2-of-3 recovery flow, which this does not change.
5. **What it must not change.** Tutoring provider and adapter order stay a
   separate, existing choice; adding voice never reorders them. The demo, the
   reference voice and the text-first fallback are untouched. No new
   activation gate.

## Out of scope

Hosted accounts, key sharing, key rotation schedules, and any provider not
already supported.
