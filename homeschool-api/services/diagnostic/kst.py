"""
Knowledge Space Theory — surmise relations, knowledge-state validity, the
outer fringe, and prerequisite-floor propagation — realizes runtime-loop
steps S1/S7 (see docs/diagnostic/DIAGNOSTIC_LOOP.md). Pure stdlib, no
numpy, per docs/diagnostic/DIAGNOSTIC_BUILD_LOOP.md's Phase 1 hard rules.

Implements the published surmise-relation model from scratch (design doc
§14 — Doignon & Falmagne 1985, Falmagne & Doignon 2011): skill_map.py's
prerequisite edges *are* the surmise relation `≺` (a ≺ b means "a child
who has mastered b is presumed to have mastered a"). Every function here
operates against that real K-8 skill map (services.diagnostic.skill_map),
not a generic injected graph — this module is specifically the K-8 math
DAG's KST logic, matching the design doc's own signatures (no
prerequisite-lookup parameter is threaded through them).
"""

from services.diagnostic.skill_map import prerequisites_of


def _transitive_prerequisites(skill_id: str) -> set[str]:
    """Every prerequisite of skill_id, direct and indirect — the surmise
    closure of a single skill, minus the skill itself."""
    return surmise_closure({skill_id}) - {skill_id}


def surmise_closure(mastered: set[str]) -> set[str]:
    """Downward closure under the surmise relation: mastered, plus every
    prerequisite (transitively) of every skill in mastered. A child who
    has genuinely mastered a skill is presumed to have its prerequisites
    too, even if those were never directly probed."""
    closure = set(mastered)
    stack = list(mastered)
    while stack:
        for prereq_id in prerequisites_of(stack.pop()):
            if prereq_id not in closure:
                closure.add(prereq_id)
                stack.append(prereq_id)
    return closure


def is_valid_knowledge_state(state: set[str]) -> bool:
    """A state is a valid knowledge state iff it is already closed under
    the surmise relation — every skill in it has all its prerequisites
    also in it. An "invalid" state (e.g. {oa.subtract_within_20} without
    its prerequisite oa.add_within_20) can't correspond to a real child's
    knowledge under this model."""
    return surmise_closure(state) == set(state)


def propagate_prerequisites(vector: dict[str, float], threshold: float = 0.8) -> dict[str, float]:
    """For every skill whose probability has reached threshold, raise the
    floor on all of its prerequisites (transitively) to at least that same
    threshold — a child demonstrably doing multi-digit multiplication
    almost certainly also has their multiplication facts, even if that
    specific skill hasn't been directly probed in a while. Only touches
    skill ids already present in vector; never adds new keys. Returns a
    new dict — the input is not mutated."""
    updated = dict(vector)
    for skill_id, probability in vector.items():
        if probability < threshold:
            continue
        for prereq_id in _transitive_prerequisites(skill_id):
            if prereq_id in updated:
                updated[prereq_id] = max(updated[prereq_id], threshold)
    return updated


def fringe(vector: dict[str, float], lo: float = 0.2, hi: float = 0.8) -> list[str]:
    """The outer fringe: skills whose full prerequisite closure is already
    mastered (every prerequisite's probability >= hi — vacuously true for
    a skill with no prerequisites at all, e.g. cc.rote_count_20) but which
    are not themselves mastered yet (probability < hi) and are not a
    confirmed gap either (probability >= lo) — these are the ideal next
    things to probe. A skill scored below lo has already been probed and
    firmly missed; propagate_prerequisites/kst.surmise_closure handle
    reconciling that separately rather than re-offering it as "next up."
    """
    result = []
    for skill_id, probability in vector.items():
        if not (lo <= probability < hi):
            continue
        prereqs = _transitive_prerequisites(skill_id)
        if all(vector.get(prereq_id, 0.0) >= hi for prereq_id in prereqs):
            result.append(skill_id)
    return sorted(result)
