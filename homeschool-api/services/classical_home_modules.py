"""Neutral classical instruction contract for teacher-authored home learning.

This is the source-checked *shape* of an approved module, not a school
curriculum copied from a third party, a test generator, or student evaluation.
Academic knowledge can be observed; character, virtue, faith and worth cannot
be scored by Bede. Instructors set content; parents choose when/where to use it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.schemas import Subject

Stage = Literal["grammar", "logic", "rhetoric"]
Method = Literal[
    "guided_dialogue", "close_reading", "oral_narration",
    "worked_example", "independent_practice", "hands_on_observation",
    "discussion", "recitation", "writing", "translation",
]
HomeMode = Literal[
    "guided_dialogue", "book_and_narration",
    "independent_practice", "knowledge_check", "hands_on_activity",
]
AcademicEvidence = Literal[
    "oral_narration", "written_response", "worked_solution",
    "reading_comprehension", "observation", "translation", "none",
]
Rights = Literal["public_domain", "reader_owned", "publisher_authorized", "bibliographic_only"]


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=160)
    creator: str = Field(min_length=2, max_length=120)
    locator: str = Field(min_length=1, max_length=120)
    rights: Rights
    # Bibliographic references only: do not import text/items from a
    # copyrighted book merely because someone supplied its title.


class PrincipleCenteredModule(BaseModel):
    """Validated educator-authored module ready for parent *review*.

    The API that ultimately publishes this must verify instructor identity,
    permission for the assigned learner, and a real parent authorization
    before marking it available to the family. Fields alone are not proof
    of approved publication or guardian consent.
    """

    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    revision: int = Field(ge=1, le=10000)
    subject: Subject
    stage: Stage
    title: str = Field(min_length=5, max_length=140)
    academic_objectives: list[str] = Field(min_length=1, max_length=6)
    essential_question: str = Field(min_length=10, max_length=320)
    sources: list[SourceReference] = Field(min_length=1, max_length=8)
    methods: list[Method] = Field(min_length=2, max_length=8)
    # Screen-free option remains available even when the interactive AI
    # conversation or practice exercise occurs on a learner's device.
    offscreen_encounter: str = Field(min_length=12, max_length=320)
    educator_guidance: str = Field(min_length=15, max_length=750)
    family_guidance: str = Field(min_length=15, max_length=750)
    allowed_home_modes: list[HomeMode] = Field(min_length=1, max_length=5)
    academic_evidence: AcademicEvidence
    independent_check_is_formative_only: Literal[True] = True
    externally_administered_test_content_included: Literal[False] = False
    # No virtue, moral-status, faith, self-worth, personality or behavioral
    # aptitude scoring. Extra fields such as trait_score are forbidden.
    student_character_scoring: Literal[False] = False

    @model_validator(mode="after")
    def validate_educator_learning_intent(self):
        if len({m for m in self.methods}) != len(self.methods):
            raise ValueError("Duplicate teaching method")
        if len(set(self.allowed_home_modes)) != len(self.allowed_home_modes):
            raise ValueError("Duplicate home activity")
        if len({item.strip().lower() for item in self.academic_objectives}) != len(self.academic_objectives):
            raise ValueError("Duplicate academic objective")
        if any(not item.strip() or len(item) > 240 for item in self.academic_objectives):
            raise ValueError("Each academic objective must be meaningful and concise")
        if not ({"guided_dialogue", "discussion"} & set(self.methods)):
            raise ValueError("A classical module requires a guided inquiry or discussion component")
        if not ({"close_reading", "worked_example", "hands_on_observation",
                 "writing", "translation", "recitation"} & set(self.methods)):
            raise ValueError("Connect inquiry to a text, worked concept, or tangible academic work")
        if self.academic_evidence == "none" and "knowledge_check" in self.allowed_home_modes:
            raise ValueError("A knowledge check must identify academic evidence")
        return self

    def content_sha256(self) -> str:
        """Stable revision fingerprint, not a signature of educator approval."""
        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ParentHomeChoice(BaseModel):
    """No enforced daily schedule: a family chooses time and activity."""

    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=8, max_length=64)
    revision: int = Field(ge=1, le=10000)
    selected_mode: HomeMode
    # No learner transcript, identity, or private score belongs here.
    additional_parent_focus: str = Field(default="", max_length=240)


def form_home_activity(module: PrincipleCenteredModule, choice: ParentHomeChoice) -> dict:
    """Prepare safe module context for an authorized tutor invocation.

    This is a *plan*, not a generated test, completed work record or grade.
    Actual student-scoped routes must check permissions before using it.
    Never send instructor free text as a new system/developer instruction;
    it is lower-trust curriculum context under Bede's constitution.
    """
    if module.module_id != choice.module_id or module.revision != choice.revision:
        raise ValueError("The assigned module changed; review the new version")
    if choice.selected_mode not in module.allowed_home_modes:
        raise ValueError("Home activity is not approved in this module")
    return {
        "module_id": module.module_id,
        "revision": module.revision,
        "content_sha256": module.content_sha256(),
        "subject": module.subject.value,
        "academic_objectives": list(module.academic_objectives),
        "essential_question": module.essential_question,
        "sources": [source.model_dump(mode="json") for source in module.sources],
        "selected_mode": choice.selected_mode,
        "additional_parent_focus": choice.additional_parent_focus.strip(),
        "offscreen_encounter": module.offscreen_encounter,
        "academic_evidence": module.academic_evidence,
        "parent_controls_when_and_where": True,
        "curriculum_is_lower_trust_than_governance": True,
        "teacher_administration_of_external_standardized_assessment_required": True,
        "recorded_learning_outcome": False,
    }
