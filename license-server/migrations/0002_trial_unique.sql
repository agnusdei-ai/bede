-- One ACTIVE trial per customer, enforced by the database. The trial route
-- checks "one active trial per email" with a SELECT before INSERT, but a
-- concurrent request for the same email can pass that check before the
-- first insert lands. This partial index (SQLite — and therefore D1 —
-- supports partial unique indexes) makes the second concurrent insert fail
-- instead of double-issuing; the route reads the outcome from `changes`.
--
-- Keyed on customer_id (email is already unique on customers). Expired
-- trials are exempt: status flips, or a fresh trial for the same customer
-- is a NEW row after the old one expired — the index only constrains
-- rows that are active RIGHT NOW, so "come back next year and trial
-- again" keeps working.
create unique index if not exists idx_licenses_one_active_trial
  on licenses (customer_id) where tier = 'trial' and status = 'active';
