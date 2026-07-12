"""
Real check for Diagnostic build-loop unit 1.1 (skill_map.py) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md. Asserts the K-8 math skill
map is a valid DAG with no dangling prerequisite references, every skill
banded and domained, and the accessor functions behave correctly.
"""

from services.diagnostic.skill_map import (
    GradeBand,
    SKILL_MAP,
    all_skill_ids,
    get_skill,
    prerequisites_of,
    skills_in_band,
    skills_in_domain,
)


def test_prerequisite_graph_is_acyclic():
    """DFS cycle check over the prerequisite DAG (skill -> its prereqs)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {skill_id: WHITE for skill_id in SKILL_MAP}

    def visit(skill_id: str, stack: list[str]) -> None:
        color[skill_id] = GRAY
        for prereq_id in prerequisites_of(skill_id):
            if color[prereq_id] == GRAY:
                cycle = " -> ".join(stack + [prereq_id])
                raise AssertionError(f"Cycle detected in prerequisite graph: {cycle}")
            if color[prereq_id] == WHITE:
                visit(prereq_id, stack + [prereq_id])
        color[skill_id] = BLACK

    for skill_id in SKILL_MAP:
        if color[skill_id] == WHITE:
            visit(skill_id, [skill_id])

    assert all(c == BLACK for c in color.values())


def test_no_dangling_prerequisites():
    """Every prerequisite id must resolve to a real skill in SKILL_MAP."""
    dangling = [
        (skill.id, prereq_id)
        for skill in SKILL_MAP.values()
        for prereq_id in skill.prerequisites
        if prereq_id not in SKILL_MAP
    ]
    assert dangling == [], f"Dangling prerequisite references: {dangling}"


def test_every_skill_has_a_band_and_domain():
    for skill in SKILL_MAP.values():
        assert isinstance(skill.band, GradeBand), f"{skill.id} has no valid band"
        assert skill.domain, f"{skill.id} has no domain"
        assert skill.label, f"{skill.id} has no label"


def test_get_skill_returns_none_for_unknown_id():
    assert get_skill("not.a.real.skill") is None
    assert get_skill("") is None


def test_get_skill_returns_the_skill_for_known_id():
    skill = get_skill("cc.rote_count_20")
    assert skill is not None
    assert skill.id == "cc.rote_count_20"
    assert skill.domain == "Counting & Cardinality"


def test_skills_in_band_partitions_all_skills_and_is_non_empty_per_band():
    all_ids = set(all_skill_ids())
    partitioned: set[str] = set()

    for band in GradeBand:
        band_skills = skills_in_band(band)
        assert band_skills, f"Band {band} has no skills"
        assert not (set(band_skills) & partitioned), f"Band {band} overlaps a prior band"
        partitioned |= set(band_skills)

    assert partitioned == all_ids, "skills_in_band does not partition all_skill_ids()"


def test_skills_in_domain_covers_every_declared_domain():
    domains = {skill.domain for skill in SKILL_MAP.values()}
    for domain in domains:
        domain_skills = skills_in_domain(domain)
        assert domain_skills, f"Domain {domain!r} has no skills"
        for skill_id in domain_skills:
            assert SKILL_MAP[skill_id].domain == domain


def test_all_skill_ids_matches_skill_map_keys():
    assert set(all_skill_ids()) == set(SKILL_MAP.keys())
    assert len(all_skill_ids()) == len(set(all_skill_ids())), "duplicate skill ids"
