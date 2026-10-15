# Bede — organizational location subscriptions

> **Valor founding-school promotion (Fall 2026–Spring 2027):** Eligible founding-school campus memberships are offered at **$2,600 USD per physical campus per month, billed monthly on a 12-month contract**, with unlimited enrolled learner seats at that campus. This is **over 25% off** the separate standard **$3,500/month** campus price: save **$900 per month** or **$10,800 across 12 months**. Founding-campus software fees total **$31,200 across 12 months** rather than **$42,000** at the standard rate. This promotional rate is binding for the signed subscription term, including months after Spring 2027. See [VALOR_PRICING.md](VALOR_PRICING.md). The $3,500/location figure below refers to the separate general campus-location offer and does **not** supersede the approved Valor founding promotion. The $950 fixed **paid evaluation** and $25/learner/month options remain separate; the current free invite-only Valor pilot uses only manually approved synthetic-data access and has no purchasing or conversion. 

**Commercial offer decision (October 2026): $3,500 USD per month per
physical school location, unlimited enrolled learner seats at that
location.** This supersedes earlier wording of "$3,500 per organization"
that could incorrectly license multiple locations on one subscription.

The complementary per-learner offer is **$25 USD per learner per month**.
At 140 enrolled learners, the **standard $3,500** monthly campus subscription and $25 per-learner subscription are equal in price; the founding-campus **$2,600** price equals $25 per learner at **104** learners,
before hardware and optional services. Annualized location software fees
are $42,000 with twelve paid months. Each additional physical branch or
campus requires another location subscription and independently signed
license. There is no all-branches unlimited package in this offer.

**Mac mini hardware is a separate bundle and separately invoiced.**
The intended classroom package (32 GB unified memory / 1 TB storage) and
campus package (64 GB / 4 TB) are specified in
[MAC_MINI_BUNDLES.md](MAC_MINI_BUNDLES.md). Procurement, warranty, spare
units, installation, repairs and support terms must be quoted separately.

## Flexible 12-month model changes

The school may move between the campus and per-learner models through a **mutually agreed written amendment** identifying its effective date and revised billing. The 12-month contractual commitment remains unless expressly amended; avoid charging both software models for the same campus period. No automatic credits, prorations, or return to promotional pricing are promised. Paid subscriptions are separate from the free, manually approved, synthetic-data-only Valor pilot.

## What "unlimited learner seats" actually promises

- Unlimited *enrolled learner accounts* under a **single named physical
  location**; no additional per-learner software licensing fee at that site.
- Distinct, verified educator accounts, roster scopes and diagnostic
  permissions remain mandatory. An unlimited license NEVER widens an
  educator's ability to view another child's data.
- This is **not** unlimited simultaneous local model inference, unlimited
  concurrent tutoring sessions, unlimited compute tokens, a schoolwide
  throughput guarantee, an always-on cloud SLA or multiple sites.
- Local inference admission capacity must be measured on the actual
  sellable Apple Silicon runtime + model + quantization, including voice,
  DIBELS records, backup and simultaneous session testing. Do not claim
  a 64 GB / 4 TB Mac mini supports a whole school's active sessions
  without results from `core.mac_bundle_qualification`.
- Families or schools may use external AI providers only under separately
  disclosed data/usage terms and qualified safety governance. No model
  provider credential is included in a campus software license.

## Code: signed, site-bound entitlement, not fake giant seat number

There are two independent trust decisions:

1. **Commercial pricing** lives in
   `homeschool-api/core/campus_pricing.py`. It quotes $25/learner/month
   and $3,500/month per physical site with explicit hardware exclusion.
   It grants NO access, accepts NO payments and cannot override licensing.
2. **Signed software entitlement** lives in
   `homeschool-api/core/licensing.py`: a new **signed license tier
   `campus_location`** contains
   `"learner_scope":"unlimited_at_location"`, a signed
   `"location_id"`, and an expiring paid term. It MUST NOT include the
   numeric `seats` field used by legacy `trial`, `core` and `coop`
   licenses. No other tier may contain the campus entitlement.
   Bede checks the Ed25519 signature and ensures the signed location
   exactly matches the host's configured `BEDE_LOCATION_ID`. In
   production, a mismatch gates the instance instead of guessing a
   different license, and a parent trying to apply a mismatch gets 422.

The signed `campus_location` tier is **not** a fourth member of the
commercial `CommercialTier` enum. That enum remains Family, Co-op,
Network per the separate existing entitlement contract. The operator
issues this approved location-specific offer explicitly; no implicit
legacy-tier mapping was introduced. The Ed25519 private key never
enters the repository, web browser or device configuration.

## Operator fulfillment — controlled manual pilot

Assign a random, non-identifying **location identifier** to the actual
physical site (e.g. `site-2026-01`). Configure that exact ID on the
pilot deployment's private API environment:

    BEDE_LOCATION_ID=site-2026-01

After payment/invoicing and appropriate operator/guardian permissions,
issue a 31-day signed key with the OFFLINE private key:

    cd homeschool-api
    python scripts/issue_license.py \
      --tier campus_location \
      --licensee "School Location 01" \
      --location-id site-2026-01 \
      --days 31 \
      --private-key /private/operator-signing.pem

Provision that key in the existing elevated parent License panel or
server environment. It becomes active only if the site identifier
matches. Renew by issuing/applying a newly signed key reflecting the
paid-through term. Do not keep charging a customer without a renewal
fulfillment workflow.

**Commercial billing is not yet automated for this location product.**
The current Stripe license-server mappings issue only the existing
Family membership; the location SKU has NO configured Stripe price
ID, checkout, invoice collection, renewal webhook or automated license
issuance. This document is a manual B2B fulfillment contract, not
evidence of an online checkout. Obtain explicit approval and regression
tests before modifying live pricing pages (`site/` or `demo/`).

Offline signatures prevent forging or modifying a location ID. They
cannot prevent a recipient from copying an entire signed key and
configuration to another device. Legal single-location terms and the
optional activation/license server govern duplication; **site-bound
signature alone is not hardware attestation or clone prevention**.

## Preflight for a paying production pilot

- Complete clinician/educator-style diagnostic validation with
  **independently administered** DIBELS reports and source corrections.
  DIBELS scores are never silently AI-administered or rescaled.
- Verify instructor MFA, per-child roster authorization, guardian
  permissions and safe supervised learner-device use.
- Run at least one full two-day teaching cycle, data recovery and
  real-device performance/stress tests on the sold Mac configuration.
- Run the license test matrix: legacy license cap, unlimited site
  entitlement, wrong location, expiry, revocation and switching licenses.
- Establish a stated support/response contract, renewal invoicing
  owner, hardware procurement/warranty responsibility and operational
  limits for local model concurrency.

A green unit test proves software contract behavior, not that the
site can handle all simultaneous learners or that payment systems are
in production.
