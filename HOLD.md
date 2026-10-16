# Hold-Branch Addendum

This branch preserves unreviewed owner-flow work only.

It is not a release candidate and is not authorized for merge, deployment,
teacher testing, production use, or use as a base for G1/G2/G3 work.

Known incompatibility:
The preserved work may cause an approved instructional plan to be delivered
directly into a learner session. That behavior conflicts with the current
teacher-controlled decision-support boundary.

Required before any future reuse:
- Default `delivery_state = NOT_REQUESTED`
- Explicit teacher delivery request and confirmation
- Reauthorization of teacher, campus, learner, grant, and session
- Delivery-specific audit record
- Cancellation/revocation behavior
- Synthetic qualification
- Separate human product review
