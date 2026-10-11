-- One row per trial we have told the family is ending, so we never tell them
-- twice. docs/LICENSE_SERVER_SETUP.md §3: a schema change is a NEW numbered
-- migration; 0001 and 0002 are immutable once applied.
--
-- The primary key IS the licence id, which is what makes a double-send
-- impossible rather than unlikely: the sender claims the right to send with
-- `on conflict do nothing` and reads `changes`, exactly as
-- src/routes/trial.ts claims the one-active-trial slot. Two overlapping cron
-- invocations cannot both win.
--
-- Deliberately NOT a column on `licenses`: that table's rows are the
-- entitlement, and whether we happened to send an email is not part of what a
-- customer bought.

create table if not exists trial_reminders (
  license_id text primary key references licenses(id),
  sent_at text not null
);
