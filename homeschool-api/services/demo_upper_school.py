"""Shared upper-school guidance for demo and enrolled sessions.

The module name is retained for compatibility. Availability and routing are
defined by curriculum_delivery, independently of account or delivery type.
"""

from models.schemas import DEMO_UPPER_GRADES, SessionConfig


GRADE_FOCI = {
    "9": (
        "Mathematics: algebraic structure, linear and quadratic relationships, and explaining equivalent steps. "
        "Reading and writing: close reading, textual evidence, paragraph arguments, and revision. "
        "Science: variables, measurement, energy and matter, and claims supported by data. "
        "History: ancient civilizations and evaluating a primary source in context."
    ),
    "10": (
        "Mathematics: geometric reasoning, similarity, proof, and connecting diagrams with algebra. "
        "Reading and writing: compare interpretations, analyze rhetoric, and develop a supported essay. "
        "Science: biological systems, experimental controls, and distinguishing correlation from causation. "
        "History: medieval and early modern societies, comparing sources and competing explanations."
    ),
    "11": (
        "Mathematics: polynomial, rational, exponential, and logarithmic relationships and checking domains. "
        "Reading and writing: sustained arguments, source synthesis, counterarguments, and citation practice. "
        "Science: chemical models, proportional reasoning, and evaluating uncertainty in supplied data. "
        "History: American history and civic arguments, using primary-source evidence and context."
    ),
    "12": (
        "Mathematics: functions, trigonometric and introductory rate-of-change reasoning, and modeling assumptions. "
        "Reading and writing: independent synthesis, research questions, argument revision, and oral defense. "
        "Science: physical models, quantitative reasoning, uncertainty, and limitations of an explanation. "
        "History: modern history, government, and economics, weighing evidence and tradeoffs across perspectives."
    ),
}


def upper_school_guidance(config: SessionConfig) -> str:
    grade = config.grade.strip()
    if grade not in DEMO_UPPER_GRADES:
        return ""
    scope = (
        "When an adult-selected, reviewed Bede full-year lesson is supplied below, teach from it; it is not accredited, "
        "credit-bearing, human-accepted or evidence of mastery. "
        if getattr(config, "upper_curriculum", None) else
        "These are sample practice directions, not a complete, accredited, or approved full-year curriculum. "
    )
    return (
        f"INTERACTIVE GRADE {grade} — upper-school Socratic practice.\n"
        "The 6-8 transport band is only a compatibility envelope for existing session tools; "
        "teach at the exact upper-school grade stated here, not at a middle-school level. "
        f"{scope}"
        "Do not report K-8 diagnostic or skill-registry results as high-school mastery or readiness.\n"
        f"{GRADE_FOCI[grade]}\n"
        "Start with one short readiness question tied to the chosen subject and the learner's own unit, "
        "if supplied. Use the response to adjust prerequisites and challenge without changing the selected grade. "
        "In languages, build from the learner's demonstrated reading and translation experience; in logic, "
        "test premises and validity; in art and music, ask for evidence-based comparison. "
        "Use age-respectful language, one purposeful question at a time, and progressive hints. "
        "Never complete active assignments, solve an assigned equation, or supply a finished thesis. "
        "Ask the learner to explain, apply the idea to a new case, and reflect on the result. "
        "Offer spoken, typed, or supported written responses without lowering the reasoning goal. "
        "For unseen books or sources, request an excerpt rather than inventing quotations. "
        "Science practice uses supplied or clearly hypothetical data; never prescribe unsupervised experiments. "
        "Adults retain educational and safety decisions. Preserve the selected session language."
    )
