-- The original trial boundary, recorded once and never changed.
--
-- WHY A TABLE. The retained-access promise ("you can continue using your trial
-- until X") names X as the ORIGINAL trial expiry. Stripe's `trial_end` is a
-- mutable field: an API call or a dashboard edit can move it, so reading it
-- back again is not evidence that it still is what it was. Re-reading is not
-- immutability. This table is the anchor the live value is compared against.
--
-- First sight wins: the row is written by `insert ... on conflict do nothing`
-- from the subscription's creation event (or, once conversion exists, by the
-- conversion code that SETS the trial end), and nothing in src/ updates or
-- deletes it. A later disagreement between this row and Stripe is a finding
-- (`trial_boundary_changed`), not a correction.
--
-- Nothing identifying: ids and an instant.
create table if not exists subscription_boundaries (
  subscription_id text primary key,
  -- Full ISO instant of the original trial end.
  original_trial_end text not null,
  recorded_at text not null,
  -- Which door recorded it (closed vocabulary in src/billing/boundary.ts).
  recorded_by text not null
);
