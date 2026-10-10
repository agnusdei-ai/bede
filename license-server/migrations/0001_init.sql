-- Bede License Server schema — docs/LICENSE_SERVER_DESIGN.md §7, launch-scoped
-- by the Bede ecommerce readiness spec (annual Family membership; trials).
--
-- This database belongs to the LICENSE SERVER, not to any family instance:
-- homeschool-api's database is never touched by this service, and its own
-- "CREATE TABLE IF NOT EXISTS at boot" discipline doesn't apply here. Schema
-- changes ship as additional wrangler d1 migrations (this file is 0001 and is
-- immutable once applied).
--
-- IDs are UUIDs minted by the Worker (crypto.randomUUID()); timestamps are
-- ISO-8601 UTC text — SQLite has no native timestamp column type.

create table if not exists customers (
  id text primary key,
  email text unique not null,
  created_at text not null
);

create table if not exists licenses (
  id text primary key,
  customer_id text not null references customers(id),
  tier text not null,               -- 'core' (annual Family) | 'trial' (later staged task)
  seats integer not null,           -- 6: the ≤6-children household cap, distinct from max_activations
  max_activations integer not null default 2,
  status text not null,             -- 'active' | 'revoked' (trials expire via signed expiry instead)
  valid_until text,                 -- server-authoritative for paid licenses; null for trials
  payment_provider text not null,   -- 'stripe' | 'none' (trials)
  external_customer_id text,
  external_subscription_id text,    -- scoped by provider, never mixed across processors
  license_key text not null,        -- the signed string, stored for re-delivery
  created_at text not null
);

-- Defense in depth beneath the handler's idempotency check: one license per
-- (provider, subscription). Partial (not full) so trial rows — whose
-- external_subscription_id is NULL — are free to coexist.
create unique index if not exists idx_licenses_provider_subscription
  on licenses (payment_provider, external_subscription_id)
  where external_subscription_id is not null;

create table if not exists activations (
  id text primary key,
  license_id text not null references licenses(id),
  install_id text not null,
  first_seen_at text not null,
  last_heartbeat_at text not null,
  unique(license_id, install_id)    -- same install re-activating is idempotent, never a new row
);

create table if not exists webhook_events (
  id text primary key,
  payment_provider text not null,
  external_event_id text not null,
  type text,
  received_at text not null,
  unique(payment_provider, external_event_id)  -- at-least-once delivery must not double-issue
);
