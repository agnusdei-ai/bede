# SUPERSEDED_BY_PILOT_SCOPE_FREEZE

The R1 supervised learner-session delivery proposal is **deferred**, not part of the current Valor pilot. The experimental schema committed to this branch was removed; do not merge or use this branch for implementation. Merged PR #633 is a dormant future contract.

## Authorization discovery
The existing institutional tutoring and instruction routes require educator authorization. Reusing them for learner access would violate role separation. Resolving that safely would require a separate learner identity, assignment/approval, launch authorization, session, streaming/revocation, privacy and retention design. None of those capabilities is authorized for this pilot.

## Current pilot promise
Synthetic assessment → Data Day evidence → Bede recommendation → teacher approve/edit/reject → recorded instructional plan → teacher personally teaches → teacher observation → later progress review. **No learner-session delivery.** Retain the database invariant `delivery_state = NOT_REQUESTED` and verify that teacher approval cannot launch instruction.

## Deferred post-pilot item
Supervised learner-session delivery requires a separate product decision, learner identity and assignment/approval model, authorization threat model, age-appropriate Socratic policy, privacy/retention review, implementation cycle and qualification gates. Do not elaborate or implement during pilot qualification.

## Pilot release critical path
G1 isolation/revocation; canonical assessment and Data Day; deletion lifecycle; #596 integration/qualification; #591 rebuild; #604 teacher journey; delivery-disabled owner flows; synthetic qualification; immutable package; physical Mac check; separate pilot decision.

No merge, deployment, live learner use or Pilot GO is authorized by this note.
