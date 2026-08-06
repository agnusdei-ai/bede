-- Bede license ledger — every license this Worker has ever issued, paid or
-- trial. This is the operator's own record (not a copy of anything
-- Helcim/Anthropic hold) — see docs/CHECKOUT_SETUP.md.
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
  source TEXT NOT NULL,                   -- 'helcim' | 'trial'
  helcim_invoice_number TEXT,             -- NULL for a trial
  helcim_transaction_id TEXT,
  created_at TEXT NOT NULL                -- ISO timestamp this row was written
);

CREATE INDEX IF NOT EXISTS idx_licenses_email ON licenses(licensee_email);

-- Enforces webhook idempotency — a retried/duplicate webhook delivery for
-- the same invoice becomes a safe no-op instead of a duplicate license.
CREATE UNIQUE INDEX IF NOT EXISTS idx_licenses_helcim_invoice
  ON licenses(helcim_invoice_number)
  WHERE helcim_invoice_number IS NOT NULL;

-- One row per POST /checkout/session call — created before payment, so the
-- webhook (which only carries a transaction id) can look up which
-- tier/seats/email/licensee_name the buyer actually intended, via the
-- invoiceNumber we generate ourselves at initialize time. Never deleted —
-- also doubles as the checkout_token -> invoice_number map that
-- GET /license/by-checkout uses to find the resulting license afterward.
CREATE TABLE IF NOT EXISTS pending_checkouts (
  checkout_token TEXT PRIMARY KEY,
  invoice_number TEXT UNIQUE NOT NULL,
  licensee_email TEXT NOT NULL,
  licensee_name TEXT NOT NULL,
  tier TEXT NOT NULL,
  seats INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
