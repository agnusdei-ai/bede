"""
K-8 mathematics skill map — the DAG (domain -> skill -> sub-skill) that
grounds the Diagnostic Engine's KST fringe computation (runtime-loop step
S1, see docs/diagnostic/DIAGNOSTIC_LOOP.md). Pure data + accessors: no DB,
no LLM, no third-party dependency (stdlib dataclasses/enum only), per
docs/diagnostic/DIAGNOSTIC_BUILD_LOOP.md's hard rules for Phase 1.

Band values mirror models.schemas.GradeStage exactly (foundations="K-2",
core_mastery="3-5", independent="6-8") rather than the frontend timer's
K-3 split (homeschool-tutor/src/utils/gradeTimer.ts) — per the design
doc's §2.1 decision to stay consistent with grade_to_stage().

The prerequisite edges are the KST surmise relation: a skill's
`prerequisites` are presumed mastered before the skill itself. This is a
representative, extensible skeleton (~40 skills across all 11 CCSS-aligned
domains from the design doc's §2.2) — structural correctness matters more
than exhaustive coverage; a parent/operator can extend SKILL_MAP without
touching engine logic elsewhere in this package.
"""

from dataclasses import dataclass, field
from enum import Enum


class GradeBand(str, Enum):
    """Mirrors models.schemas.GradeStage's values exactly."""
    K_2 = "K-2"
    THREE_5 = "3-5"
    SIX_8 = "6-8"


@dataclass(frozen=True)
class Skill:
    id: str
    label: str
    domain: str
    band: GradeBand
    prerequisites: tuple[str, ...] = field(default_factory=tuple)


def _s(
    id_: str,
    label: str,
    domain: str,
    band: GradeBand,
    prerequisites: tuple[str, ...] = (),
) -> Skill:
    return Skill(id=id_, label=label, domain=domain, band=band, prerequisites=prerequisites)


_SKILLS: tuple[Skill, ...] = (
    # ── Counting & Cardinality ────────────────────────────────────────────
    _s("cc.rote_count_20", "Rote counts to 20", "Counting & Cardinality", GradeBand.K_2),
    _s("cc.count_objects_20", "Counts a set of up to 20 objects", "Counting & Cardinality",
       GradeBand.K_2, ("cc.rote_count_20",)),
    _s("cc.compare_quantities", "Compares two quantities", "Counting & Cardinality",
       GradeBand.K_2, ("cc.count_objects_20",)),

    # ── Operations & Algebraic Thinking ───────────────────────────────────
    _s("oa.add_within_20", "Adds within 20", "Operations & Algebraic Thinking",
       GradeBand.K_2, ("cc.count_objects_20",)),
    _s("oa.subtract_within_20", "Subtracts within 20", "Operations & Algebraic Thinking",
       GradeBand.K_2, ("oa.add_within_20",)),
    _s("oa.multiplication_facts", "Knows multiplication facts", "Operations & Algebraic Thinking",
       GradeBand.THREE_5, ("oa.add_within_20",)),
    _s("oa.division_facts", "Knows division facts", "Operations & Algebraic Thinking",
       GradeBand.THREE_5, ("oa.multiplication_facts",)),
    _s("oa.numeric_patterns", "Extends and explains numeric patterns",
       "Operations & Algebraic Thinking", GradeBand.THREE_5, ("oa.multiplication_facts",)),

    # ── Number & Operations in Base Ten ───────────────────────────────────
    _s("nbt.place_value_tens", "Understands place value to tens",
       "Number & Operations in Base Ten", GradeBand.K_2, ("cc.count_objects_20",)),
    _s("nbt.place_value_hundreds", "Understands place value to hundreds",
       "Number & Operations in Base Ten", GradeBand.THREE_5, ("nbt.place_value_tens",)),
    _s("nbt.add_within_100", "Adds within 100", "Number & Operations in Base Ten",
       GradeBand.K_2, ("oa.add_within_20", "nbt.place_value_tens")),
    _s("nbt.subtract_within_100", "Subtracts within 100", "Number & Operations in Base Ten",
       GradeBand.K_2, ("oa.subtract_within_20", "nbt.place_value_tens")),
    _s("nbt.standard_multiplication", "Multi-digit multiplication (standard algorithm)",
       "Number & Operations in Base Ten", GradeBand.THREE_5,
       ("oa.multiplication_facts", "nbt.place_value_hundreds")),
    _s("nbt.long_division", "Long division", "Number & Operations in Base Ten",
       GradeBand.THREE_5, ("nbt.standard_multiplication",)),

    # ── Number & Operations — Fractions ───────────────────────────────────
    _s("fr.unit_fractions", "Understands unit fractions", "Number & Operations — Fractions",
       GradeBand.THREE_5, ("oa.division_facts",)),
    _s("fr.equivalent_fractions", "Finds equivalent fractions", "Number & Operations — Fractions",
       GradeBand.THREE_5, ("fr.unit_fractions",)),
    _s("fr.add_subtract_fractions", "Adds and subtracts fractions",
       "Number & Operations — Fractions", GradeBand.THREE_5, ("fr.equivalent_fractions",)),
    _s("fr.multiply_fractions", "Multiplies fractions", "Number & Operations — Fractions",
       GradeBand.THREE_5, ("fr.add_subtract_fractions",)),

    # Decimals depend on both base-ten place value and fraction equivalence.
    _s("nbt.place_value_decimals", "Understands decimal place value",
       "Number & Operations in Base Ten", GradeBand.THREE_5,
       ("nbt.place_value_hundreds", "fr.equivalent_fractions")),

    # ── Measurement & Data ─────────────────────────────────────────────────
    _s("md.measure_length", "Measures length with standard units", "Measurement & Data",
       GradeBand.K_2, ("cc.count_objects_20",)),
    _s("md.tell_time", "Tells time to the hour/minute", "Measurement & Data",
       GradeBand.K_2, ("cc.count_objects_20",)),
    _s("md.read_bar_graphs", "Reads and interprets bar graphs", "Measurement & Data",
       GradeBand.K_2, ("cc.compare_quantities",)),
    _s("md.area_perimeter", "Computes area and perimeter", "Measurement & Data",
       GradeBand.THREE_5, ("nbt.standard_multiplication",)),
    _s("md.convert_units", "Converts between measurement units", "Measurement & Data",
       GradeBand.THREE_5, ("nbt.place_value_decimals",)),

    # ── Geometry ───────────────────────────────────────────────────────────
    _s("geo.identify_shapes", "Identifies basic 2D/3D shapes", "Geometry", GradeBand.K_2),
    _s("geo.classify_shapes_by_attributes", "Classifies shapes by attributes", "Geometry",
       GradeBand.K_2, ("geo.identify_shapes",)),
    _s("geo.coordinate_plane", "Plots points on the coordinate plane", "Geometry",
       GradeBand.THREE_5, ("cc.compare_quantities",)),
    _s("geo.area_of_polygons", "Finds the area of polygons", "Geometry",
       GradeBand.THREE_5, ("md.area_perimeter",)),
    _s("geo.volume", "Finds the volume of solids", "Geometry",
       GradeBand.SIX_8, ("geo.area_of_polygons",)),

    # ── Ratios & Proportional Relationships ───────────────────────────────
    _s("rp.ratio_concept", "Understands the concept of a ratio",
       "Ratios & Proportional Relationships", GradeBand.SIX_8, ("fr.equivalent_fractions",)),
    _s("rp.unit_rate", "Computes unit rates", "Ratios & Proportional Relationships",
       GradeBand.SIX_8, ("rp.ratio_concept",)),
    _s("rp.percent", "Solves percent problems", "Ratios & Proportional Relationships",
       GradeBand.SIX_8, ("rp.unit_rate", "fr.multiply_fractions")),

    # ── The Number System ─────────────────────────────────────────────────
    _s("ns.integers", "Operates with positive and negative integers", "The Number System",
       GradeBand.SIX_8, ("nbt.subtract_within_100",)),
    _s("ns.rational_operations", "Operates with rational numbers", "The Number System",
       GradeBand.SIX_8, ("ns.integers", "fr.multiply_fractions")),

    # ── Expressions & Equations ───────────────────────────────────────────
    _s("ee.evaluate_expressions", "Evaluates algebraic expressions", "Expressions & Equations",
       GradeBand.SIX_8, ("oa.numeric_patterns", "ns.rational_operations")),
    _s("ee.one_step_equations", "Solves one-step equations", "Expressions & Equations",
       GradeBand.SIX_8, ("ee.evaluate_expressions",)),
    _s("ee.two_step_equations", "Solves two-step equations", "Expressions & Equations",
       GradeBand.SIX_8, ("ee.one_step_equations",)),

    # ── Statistics & Probability ──────────────────────────────────────────
    _s("sp.mean_median_mode", "Computes mean, median, and mode", "Statistics & Probability",
       GradeBand.SIX_8, ("nbt.standard_multiplication",)),
    _s("sp.data_distribution", "Describes the distribution of a data set",
       "Statistics & Probability", GradeBand.SIX_8, ("sp.mean_median_mode",)),
    _s("sp.basic_probability", "Computes basic probabilities", "Statistics & Probability",
       GradeBand.SIX_8, ("fr.equivalent_fractions",)),

    # ── Functions ──────────────────────────────────────────────────────────
    _s("fn.function_concept", "Understands a function as a rule", "Functions",
       GradeBand.SIX_8, ("ee.two_step_equations", "rp.unit_rate")),
    _s("fn.linear_functions", "Works with linear functions", "Functions",
       GradeBand.SIX_8, ("fn.function_concept",)),
)

SKILL_MAP: dict[str, Skill] = {s.id: s for s in _SKILLS}

# Directed edges: skill -> its direct prerequisites. Suitable for KST
# surmise-closure computation (services/diagnostic/kst.py, unit 1.5).
PREREQUISITES: dict[str, tuple[str, ...]] = {s.id: s.prerequisites for s in _SKILLS}


def get_skill(skill_id: str) -> Skill | None:
    return SKILL_MAP.get(skill_id)


def prerequisites_of(skill_id: str) -> list[str]:
    """Direct prerequisites only — not the transitive surmise closure
    (that's kst.surmise_closure, unit 1.5)."""
    return list(PREREQUISITES.get(skill_id, ()))


def skills_in_band(band: GradeBand) -> list[str]:
    return [s.id for s in _SKILLS if s.band == band]


def skills_in_domain(domain: str) -> list[str]:
    return [s.id for s in _SKILLS if s.domain == domain]


def all_skill_ids() -> list[str]:
    return [s.id for s in _SKILLS]
