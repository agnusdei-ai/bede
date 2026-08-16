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
       GradeBand.THREE_5, ("cc.compare_quantities", "nbt.place_value_tens")),
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
       GradeBand.SIX_8, ("nbt.subtract_within_100", "nbt.long_division")),
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
       GradeBand.SIX_8, ("nbt.standard_multiplication", "oa.division_facts")),
    _s("sp.data_distribution", "Describes the distribution of a data set",
       "Statistics & Probability", GradeBand.SIX_8, ("sp.mean_median_mode",)),
    _s("sp.basic_probability", "Computes basic probabilities", "Statistics & Probability",
       GradeBand.SIX_8, ("fr.equivalent_fractions",)),

    # ── Functions ──────────────────────────────────────────────────────────
    _s("fn.function_concept", "Understands a function as a rule", "Functions",
       GradeBand.SIX_8, ("ee.two_step_equations", "rp.unit_rate")),
    _s("fn.linear_functions", "Works with linear functions", "Functions",
       GradeBand.SIX_8, ("fn.function_concept",)),

    # ══════════════════════════════════════════════════════════════════════
    # PREPARATORY-SCHOOL EXTENSION
    #
    # The original 42 skills tracked a conventional public-school K-8 scope.
    # Held against what an independent/classical preparatory school actually
    # expects, the top of the map stopped roughly at two-step equations and
    # a first look at linear functions — while a prep-school 8th grader is
    # normally FINISHING ALGEBRA I. (Singapore's Dimensions Math 7-8, which
    # classical and prep schools commonly use, covers pre-algebra plus
    # Algebra I with an introduction to geometry across those two years.)
    #
    # Everything below is ADDITIVE. Not one existing skill id, label, band,
    # or prerequisite tuple changed — stored MasteryProfile vectors
    # reference these ids by name, so renaming or removing one would orphan
    # a real family's history. New skills are backfilled into an existing
    # vector at their cold-start prior by mastery.ensure_complete().
    #
    # The three bands now target:
    #   K-2  — number sense deep enough to carry multiplication later
    #          (number bonds, skip counting, equal groups), not just
    #          counting and adding.
    #   3-5  — the arithmetic a prep school assumes is finished before
    #          pre-algebra: order of operations, factors and primes,
    #          all four decimal operations, division of fractions.
    #   6-8  — genuine Algebra I: multi-step and literal equations,
    #          inequalities, systems, exponent laws, radicals, polynomial
    #          arithmetic, factoring, quadratics by factoring, slope and
    #          slope-intercept form, plus the Pythagorean theorem and
    #          transformational geometry.
    # ══════════════════════════════════════════════════════════════════════

    # ── K-2: number sense that multiplication will later stand on ─────────
    _s("cc.skip_count_2_5_10", "Skip counts by 2s, 5s, and 10s", "Counting & Cardinality",
       GradeBand.K_2, ("cc.rote_count_20",)),
    _s("cc.number_bonds", "Decomposes a number into parts (number bonds)",
       "Counting & Cardinality", GradeBand.K_2, ("cc.count_objects_20",)),
    _s("oa.fact_fluency_20", "Recalls addition and subtraction facts within 20 fluently",
       "Operations & Algebraic Thinking", GradeBand.K_2, ("oa.subtract_within_20",)),
    _s("oa.even_odd", "Distinguishes even and odd numbers", "Operations & Algebraic Thinking",
       GradeBand.K_2, ("cc.skip_count_2_5_10",)),
    _s("oa.arrays_equal_groups", "Sees equal groups and arrays as repeated addition",
       "Operations & Algebraic Thinking", GradeBand.K_2,
       ("oa.add_within_20", "cc.skip_count_2_5_10")),
    _s("oa.one_step_word_problems", "Solves one-step word problems",
       "Operations & Algebraic Thinking", GradeBand.K_2,
       ("oa.subtract_within_20", "cc.number_bonds")),
    _s("nbt.compare_three_digit", "Compares three-digit numbers",
       "Number & Operations in Base Ten", GradeBand.K_2,
       ("nbt.place_value_tens", "cc.compare_quantities")),
    _s("md.money", "Counts and makes amounts of money", "Measurement & Data",
       GradeBand.K_2, ("nbt.add_within_100", "cc.skip_count_2_5_10")),
    _s("md.measure_mass_capacity", "Measures mass and capacity", "Measurement & Data",
       GradeBand.K_2, ("md.measure_length",)),
    _s("fr.halves_fourths", "Partitions shapes into halves and fourths",
       "Number & Operations — Fractions", GradeBand.K_2,
       ("geo.classify_shapes_by_attributes",)),
    _s("geo.compose_shapes", "Composes and decomposes shapes", "Geometry",
       GradeBand.K_2, ("geo.identify_shapes",)),

    # ── 3-5: the arithmetic pre-algebra assumes is already finished ───────
    _s("oa.order_of_operations", "Applies the order of operations",
       "Operations & Algebraic Thinking", GradeBand.THREE_5,
       ("oa.multiplication_facts", "oa.division_facts")),
    _s("oa.factors_multiples", "Finds factors and multiples",
       "Operations & Algebraic Thinking", GradeBand.THREE_5, ("oa.division_facts",)),
    _s("oa.primes_composites", "Identifies primes and composites, and factors fully",
       "Operations & Algebraic Thinking", GradeBand.THREE_5, ("oa.factors_multiples",)),
    _s("oa.multi_step_word_problems", "Solves multi-step word problems",
       "Operations & Algebraic Thinking", GradeBand.THREE_5,
       ("oa.one_step_word_problems", "nbt.standard_multiplication")),
    _s("nbt.rounding_estimation", "Rounds and estimates to check reasonableness",
       "Number & Operations in Base Ten", GradeBand.THREE_5, ("nbt.place_value_hundreds",)),
    _s("nbt.decimal_operations", "Adds, subtracts, multiplies, and divides decimals",
       "Number & Operations in Base Ten", GradeBand.THREE_5,
       ("nbt.place_value_decimals", "nbt.long_division")),
    _s("fr.compare_fractions", "Compares and orders fractions",
       "Number & Operations — Fractions", GradeBand.THREE_5, ("fr.equivalent_fractions",)),
    _s("fr.mixed_numbers", "Converts between mixed numbers and improper fractions",
       "Number & Operations — Fractions", GradeBand.THREE_5, ("fr.add_subtract_fractions",)),
    _s("fr.divide_fractions", "Divides fractions", "Number & Operations — Fractions",
       GradeBand.THREE_5, ("fr.multiply_fractions",)),
    _s("md.angle_measure", "Measures and draws angles", "Measurement & Data",
       GradeBand.THREE_5, ("geo.classify_shapes_by_attributes",)),
    _s("md.volume_rectangular", "Finds the volume of a rectangular prism",
       "Measurement & Data", GradeBand.THREE_5, ("md.area_perimeter",)),
    _s("md.line_plots", "Represents data on a line plot", "Measurement & Data",
       GradeBand.THREE_5, ("md.read_bar_graphs", "fr.unit_fractions")),
    _s("geo.classify_2d_hierarchy", "Classifies two-dimensional figures in a hierarchy",
       "Geometry", GradeBand.THREE_5, ("geo.classify_shapes_by_attributes", "md.angle_measure")),

    # ── 6-8: genuine Algebra I ────────────────────────────────────────────
    _s("ns.absolute_value", "Understands absolute value", "The Number System",
       GradeBand.SIX_8, ("ns.integers",)),
    _s("ns.exponent_laws", "Applies the laws of integer exponents", "The Number System",
       GradeBand.SIX_8, ("ns.rational_operations", "oa.order_of_operations")),
    _s("ns.square_cube_roots", "Evaluates square and cube roots", "The Number System",
       GradeBand.SIX_8, ("ns.exponent_laws",)),
    _s("ns.scientific_notation", "Works in scientific notation", "The Number System",
       GradeBand.SIX_8, ("ns.exponent_laws", "nbt.decimal_operations")),
    _s("ns.irrational_numbers", "Distinguishes rational from irrational numbers",
       "The Number System", GradeBand.SIX_8, ("ns.square_cube_roots",)),

    _s("rp.proportional_relationships", "Recognizes and uses proportional relationships",
       "Ratios & Proportional Relationships", GradeBand.SIX_8, ("rp.unit_rate",)),
    _s("rp.scale_similar_figures", "Uses scale drawings and similar figures",
       "Ratios & Proportional Relationships", GradeBand.SIX_8,
       ("rp.proportional_relationships",)),

    _s("ee.distributive_expand", "Expands expressions using the distributive property",
       "Expressions & Equations", GradeBand.SIX_8, ("ee.evaluate_expressions",)),
    _s("ee.multi_step_equations", "Solves multi-step equations", "Expressions & Equations",
       GradeBand.SIX_8, ("ee.two_step_equations", "ee.distributive_expand")),
    _s("ee.variables_both_sides", "Solves equations with variables on both sides",
       "Expressions & Equations", GradeBand.SIX_8, ("ee.multi_step_equations",)),
    _s("ee.literal_equations", "Rearranges a formula to solve for a chosen variable",
       "Expressions & Equations", GradeBand.SIX_8, ("ee.multi_step_equations",)),
    _s("ee.inequalities", "Solves and graphs linear inequalities", "Expressions & Equations",
       GradeBand.SIX_8, ("ee.multi_step_equations",)),
    _s("ee.factor_expressions", "Factors linear and simple quadratic expressions",
       "Expressions & Equations", GradeBand.SIX_8,
       ("ee.distributive_expand", "oa.primes_composites")),
    _s("ee.polynomial_arithmetic", "Adds, subtracts, and multiplies polynomials",
       "Expressions & Equations", GradeBand.SIX_8,
       ("ee.factor_expressions", "ns.exponent_laws")),
    _s("ee.quadratic_by_factoring", "Solves quadratic equations by factoring",
       "Expressions & Equations", GradeBand.SIX_8,
       ("ee.polynomial_arithmetic", "ns.square_cube_roots")),
    _s("ee.systems_of_equations", "Solves systems of linear equations",
       "Expressions & Equations", GradeBand.SIX_8,
       ("ee.variables_both_sides", "fn.linear_functions")),

    _s("fn.slope", "Finds and interprets slope as a rate of change", "Functions",
       GradeBand.SIX_8, ("fn.linear_functions", "rp.proportional_relationships")),
    _s("fn.slope_intercept_form", "Writes and graphs a line in slope-intercept form",
       "Functions", GradeBand.SIX_8, ("fn.slope", "geo.coordinate_plane")),
    _s("fn.compare_functions", "Compares functions given in different representations",
       "Functions", GradeBand.SIX_8, ("fn.slope_intercept_form",)),
    _s("fn.linear_modeling", "Models a real situation with a linear function",
       "Functions", GradeBand.SIX_8, ("fn.slope_intercept_form",)),

    _s("geo.angle_relationships", "Uses angle relationships to find unknown angles",
       "Geometry", GradeBand.SIX_8, ("md.angle_measure",)),
    _s("geo.pythagorean", "Applies the Pythagorean theorem", "Geometry",
       GradeBand.SIX_8, ("ns.square_cube_roots", "geo.area_of_polygons")),
    _s("geo.transformations", "Performs and describes transformations", "Geometry",
       GradeBand.SIX_8, ("geo.coordinate_plane",)),
    _s("geo.congruence_similarity", "Reasons about congruence and similarity", "Geometry",
       GradeBand.SIX_8, ("geo.transformations", "rp.scale_similar_figures")),
    _s("geo.surface_area", "Finds the surface area of solids", "Geometry",
       GradeBand.SIX_8, ("geo.area_of_polygons", "md.volume_rectangular")),

    _s("sp.scatter_plots", "Reads and constructs scatter plots", "Statistics & Probability",
       GradeBand.SIX_8, ("geo.coordinate_plane", "sp.data_distribution")),
    _s("sp.line_of_best_fit", "Fits and interprets a line of best fit",
       "Statistics & Probability", GradeBand.SIX_8,
       ("sp.scatter_plots", "fn.slope_intercept_form")),
    _s("sp.two_way_tables", "Interprets two-way tables", "Statistics & Probability",
       GradeBand.SIX_8, ("sp.data_distribution",)),
    _s("sp.compound_probability", "Computes probabilities of compound events",
       "Statistics & Probability", GradeBand.SIX_8,
       ("sp.basic_probability", "fr.multiply_fractions")),
)

SKILL_MAP: dict[str, Skill] = {s.id: s for s in _SKILLS}

# Directed edges: skill -> its direct prerequisites. Suitable for KST
# surmise-closure computation (services/diagnostic/kst.py, unit 1.5).
PREREQUISITES: dict[str, tuple[str, ...]] = {s.id: s.prerequisites for s in _SKILLS}


def _build_dependents_index() -> dict[str, tuple[str, ...]]:
    """Inverse of PREREQUISITES: skill -> the skills that list it as a direct
    prerequisite. Precomputed once at module load (per design doc §4.1) so
    kst.py (unit 1.5) doesn't need to rebuild a reverse-adjacency map itself
    to walk 'up' the DAG."""
    index: dict[str, list[str]] = {skill_id: [] for skill_id in SKILL_MAP}
    for skill in _SKILLS:
        for prereq_id in skill.prerequisites:
            index.setdefault(prereq_id, []).append(skill.id)
    return {skill_id: tuple(dependents) for skill_id, dependents in index.items()}


DEPENDENTS: dict[str, tuple[str, ...]] = _build_dependents_index()


def get_skill(skill_id: str) -> Skill | None:
    return SKILL_MAP.get(skill_id)


def prerequisites_of(skill_id: str) -> list[str]:
    """Direct prerequisites only — not the transitive surmise closure
    (that's kst.surmise_closure, unit 1.5)."""
    return list(PREREQUISITES.get(skill_id, ()))


def dependents_of(skill_id: str) -> list[str]:
    """Direct dependents only — the skills that list skill_id as one of
    their own direct prerequisites. Inverse of prerequisites_of."""
    return list(DEPENDENTS.get(skill_id, ()))


def skills_in_band(band: GradeBand) -> list[str]:
    return [s.id for s in _SKILLS if s.band == band]


def skills_in_domain(domain: str) -> list[str]:
    return [s.id for s in _SKILLS if s.domain == domain]


def all_skill_ids() -> list[str]:
    return [s.id for s in _SKILLS]
