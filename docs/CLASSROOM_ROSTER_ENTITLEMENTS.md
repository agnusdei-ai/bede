# Classroom roster capacity and Locuto organizational entitlements

## What is enforceable today

The effective **signed Bede license** is Bede's authoritative current
student-capacity control. `core/license_state.effective_info().seats`
determines how many student configurations may be registered on one
Bede installation; `routers/pod.py::save_pod_configs` already enforces
the union of existing and new students against that cap.

`GET /pod/roster-capacity` makes this real enforcement status visible
to an authenticated **parent only**, returning a count of enrolled
students, the current signed Bede seat limit, remaining seats, and
whether an organizational Locuto entitlement has been verified.

The parent Pod Dashboard displays **X of Y licensed learner seats** only
when a valid signed Bede license is active. No broad classroom/student
data export, Locuto login, messaging-group creation, or extra student
access is introduced.

The installation's current license controls the student count: it can
be greater than ten, and the Locuto messaging group's smaller cap must
never be used as a default school enrollment limit.

## What Locuto actually specifies

The companion product's `docs/deployment.md` §2 describes an
**organization relay** as serving *tens to hundreds*, but does not
establish a universal exact organizational max. Its
`docs/bede-locuto-entitlement-contract.md` defines a negotiated
`limits` object with separate `max_children`, `max_households`,
`max_seats` (ADULT administrative seats), and `max_organizations`.
A `null` value means that field does not constrain the entitlement.

- For an actual jointly authorized organizational entitlement,
  `max_children` maps to Bede's signed `seats` concept, subject to
  explicit validation of both independent signatures and contract
  version. `max_seats` does **not** mean Bede learners.
- Per-message Locuto v1 Pods are separate, with a hard **10-active-human
  member** cap in `docs/groups.md` §9; a school can have more
  students than any one messaging Pod can have members.
- Locuto's current `docs/workflows.md` says its organization Pod
  end-to-end thread and administration flow is not fully enabled.
  Bede does not present a projected Locuto group as usable messaging.

The `/pod/roster-capacity` response currently returns
`locuto_organization_max_children: null` and
`locuto_entitlement_verified: false` deliberately. It would be a
security error to receive unsigned `max_children` values from a
client and accept them as a licensed increase.

## Before institutional instructor access is opened

The current Bede installation remains a **single-family** model.
A classroom roster composed of different households requires separate
educator credentials, true student-to-instructor assignment, parent
authorization, tenant isolation, and end-to-end authorization on every
tutoring and diagnostic operation. Existing parent sessions and the
unenforced organization entitlement draft cannot grant those rights.

Do not put children's names, grades, reports, diagnostics, roster IDs,
or assessment outcomes into Locuto messaging handoffs. When the Locuto
provider offers a tested school-compatible group API, messaging group
membership is separately consented and subject to Locuto's *own*
per-Pod limit and current platform availability.

## Evidence and tests

- `homeschool-api/tests/test_roster_capacity.py`:
  24 synthetic student configs under a 75-student signed-license
  *substitute*; no ten-student truncation; remaining seat counts;
  no invented organizational maximum; parent-only dependency.
  The fake license is a test double, not a forged production
  entitlement. No external services are contacted.
- `homeschool-api/tests/test_app_composition.py` ensures the
  assembled endpoint cannot be downgraded to child-role or demo access.
- Actual enrollment enforcement remains in `save_pod_configs`,
  and all earlier signed license and expiration tests remain required.

This increment is organizational **capacity correctness**, not a
claim that separate educator login, multi-family roster permissions,
or Locuto organizational messaging is released.
