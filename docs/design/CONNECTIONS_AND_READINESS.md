# Parent Setup: Connections and readiness (design, not built)

**Status: proposal for owner review. Nothing here is implemented.** The aim is
that after installation a parent can see and manage Bede's outside connections
(tutoring service, voice) from Parent Setup instead of editing `.env`. The
hard part is not the screen, it is letting a browser cause a secret to be
stored. That needs agreement first.

## Intended destination

Guided, in-app management is where this is heading: a parent connects, replaces
or turns off Bede's voice and tutoring service from Parent Setup, with the same
plain wording the installer uses ("Bede's voice is connected", "Continue with
text", "Speaking is off") and, when something fails, the actual problem and the
next useful action. Customer-facing labels stay confident and outcome-focused;
engineering verification detail belongs in tests and the acceptance record. The
installer's `.env` path stays as the fallback until this exists.

## What exists today

`GET /admin/ai-provider` (+ `POST`) switches among already-credentialed
adapters and stores only a name, never a credential
(`core/provider_state.py`). `GET /tutor/voice` reports whether speech is
configured. Credentials live only in `.env`, read at start. There is no write
path for a key, deliberately.

## Proposed states, per connection

Internal states: `missing`, `connected`, `rejected` (the service refused the
key), `unavailable` (could not reach it), `blocked` (policy forbids it), `off`
(deliberately disabled). The customer sees plain labels for each ("Bede's voice
is connected", "Continue with text", "Speaking is off") and, for `rejected`,
`unavailable` and `blocked`, the actual problem and the next step. A failure
state comes from a real failed speech attempt, so the label is never a guess.
Any proactive check of a key is a paid or external call and needs the owner's
approval first.

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
