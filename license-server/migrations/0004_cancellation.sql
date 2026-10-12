-- The three cancellation routes' own storage. docs/LICENSE_SERVER_SETUP.md §3:
-- a schema change is a NEW numbered migration; 0001-0003 are immutable once
-- applied.
--
-- Neither table is a column on `licenses`. That table's rows are the
-- entitlement; a one-time link we emailed, and a request we have not yet been
-- able to process, are neither part of what a customer bought nor facts about
-- it.

-- Tier 1, the account route. The license server has no passwords and must not
-- grow one, so "signing in" is a one-time link sent to the address of record.
-- Only the HASH is stored: a leaked database row must not be a working
-- cancellation link, and the server never needs the token back in plaintext —
-- the same verify-only reasoning as core/credential_hash.py.
create table if not exists cancel_tokens (
  token_hash text primary key,
  license_id text not null references licenses(id),
  created_at text not null,
  expires_at text not null,
  -- Set on first use. A link that cancels twice is a link that could cancel
  -- something the customer re-subscribed to in between.
  used_at text
);

create index if not exists cancel_tokens_license on cancel_tokens(license_id);

-- Tier 3, the route for a customer who cannot get in at all, and the durable
-- record behind "your request was received on <timestamp>". That sentence may
-- only be shown when a row here exists, which is why this is a table and not
-- a log line.
--
-- `license_id` is nullable ON PURPOSE: the whole point of this tier is that
-- the customer could not identify their subscription, so a request that
-- matches nothing is still a request we received and owe an answer to.
create table if not exists cancellation_requests (
  id text primary key,
  received_at text not null,
  account_email text not null,
  name text,
  subscription_reference text,
  license_id text references licenses(id),
  -- 'received'  — recorded, not yet acted on
  -- 'confirmed' — the provider accepted the change
  -- 'closed'    — resolved without a provider change (no subscription found)
  status text not null default 'received',
  -- The provider's own answer, verbatim, for the operator reading this later.
  provider_detail text,
  confirmed_at text
);

create index if not exists cancellation_requests_email on cancellation_requests(account_email);
create index if not exists cancellation_requests_status on cancellation_requests(status);
