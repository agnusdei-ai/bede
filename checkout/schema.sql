-- Bede license ledger — every license this Worker has ever issued, paid or
-- trial. This is the operator's own record (not a copy of anything
-- Stripe/Anthropic hold) — see docs/CHECKOUT_SETUP.md.
--
-- Apply with:
--   wrangler d1 execute bede-licenses --remote --file=schema.sql

CREATE TABLE IF NOT EXISTS licenses (
  id TEXT PRIMARY KEY,                    -- uuid, matches the license payload's own "id"
  license_key TEXT NOT NULL,              -- the full signed LICENSE_KEY string
  licensee_email TEXT NOT NULL,
  licensee_name TEXT NOT NULL,
  tier TEXT NOT NULL,                     -- 'trial' | 'core' | 'coop'
  seats INTEGER NOT NULL,
  issued TEXT NOT NULL,                   -- ISO date, e.g. 2026-07-14
  expires TEXT,                           -- ISO date, or NULL for perpetual
  source TEXT NOT NULL,                   -- 'stripe' | 'trial'
  stripe_checkout_session_id TEXT,        -- NULL for a trial
  stripe_customer_id TEXT,
  created_at TEXT NOT NULL                -- ISO timestamp this row was written
);

CREATE INDEX IF NOT EXISTS idx_licenses_email ON licenses(licensee_email);

-- Enforces webhook idempotency — Stripe retries checkout.session.completed
-- on any non-2xx response, and this makes a second delivery of the same
-- session a safe no-op instead of a duplicate license.
CREATE UNIQUE INDEX IF NOT EXISTS idx_licenses_stripe_session
  ON licenses(stripe_checkout_session_id)
  WHERE stripe_checkout_session_id IS NOT NULL;
