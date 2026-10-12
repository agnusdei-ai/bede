-- The append-only billing audit ledger.
--
-- docs/LICENSE_SERVER_SETUP.md §3: a schema change is a NEW numbered
-- migration; 0001-0004 are immutable once applied.
--
-- WHY A FIFTH TABLE, when four already record billing things. Each of those
-- answers an OPERATIONAL question and none answers the audit one:
--
--   licenses              what a customer is entitled to NOW
--   webhook_events        which provider deliveries we have already handled
--   cancellation_requests which cancellations still need an operator
--   trial_reminders       which families we have already written to
--
-- All four are current-state or work-queue tables: rows get updated, and
-- "what is true now" is exactly what they are for. A SOC 2 Type 2 engagement
-- asks a different question — show every billing state change across the
-- period, who caused it, and on what authority — and a current-state table
-- structurally cannot answer it, because the evidence is the history and the
-- history is what gets overwritten.
--
-- So this table is APPEND-ONLY by design and by convention: nothing in the
-- codebase updates or deletes a row, and `tests/soc2_evidence.test.ts` fails
-- if an `update billing_events` or `delete from billing_events` appears
-- anywhere in src/. A ledger an application can edit is not evidence.
--
-- It is deliberately NOT a replacement for any of the four. Duplication of a
-- fact between a work queue and a ledger is correct here: one is for doing
-- the work, the other is for proving what was done.
create table if not exists billing_events (
  id text primary key,
  -- When the action happened, as a full instant. Date granularity cannot
  -- support "show me the sequence of changes on 12 October".
  occurred_at text not null,
  -- What happened. A closed vocabulary (src/audit/billing_events.ts) so a
  -- period's events can be counted by type without a human classifying them.
  action text not null,
  -- WHO caused it, from a closed vocabulary. This is the column the audit
  -- turns on: a cancellation by the customer over an emailed link and one
  -- performed by an operator are the same change on different authority, and
  -- a ledger that cannot tell them apart proves nothing about authorisation.
  actor_kind text not null,
  -- Non-identifying detail about the actor (a masked email, an operator
  -- label). Never a credential, never a token, never a licence key.
  actor_detail text,
  license_id text,
  subscription_id text,
  -- 'confirmed' | 'pending' | 'refused' | 'failed' — whether the intended
  -- change actually took effect, which is the other half of the evidence:
  -- an attempted change that failed is as much a fact as one that succeeded.
  outcome text not null,
  -- The provider's own answer, verbatim, for whoever reads this later.
  provider_detail text,
  -- Ties a ledger row to the reference the customer was shown, so a support
  -- enquiry and the audit trail meet.
  request_id text
);

create index if not exists billing_events_occurred on billing_events(occurred_at);
create index if not exists billing_events_license on billing_events(license_id);
create index if not exists billing_events_action on billing_events(action);
