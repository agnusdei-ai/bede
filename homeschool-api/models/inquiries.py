"""Bounded business inquiry fields; never student records or arbitrary recipients."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

Audience = Literal["homeschool", "coop", "charter_school"]
GradeBand = Literal["K–2", "3–5", "6–8"]
Interest = Literal["Demo", "Plan and pricing", "Implementation", "Training and onboarding"]


class InquiryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    audience: Audience
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=254)
    organization: str = Field(default="", max_length=150)
    role: str = Field(min_length=1, max_length=80)
    location: str = Field(default="", max_length=120)
    learners: int = Field(ge=1, le=100000, strict=True)
    families: int | None = Field(default=None, ge=1, le=100000, strict=True)
    educators: int | None = Field(default=None, ge=1, le=10000, strict=True)
    sites: int | None = Field(default=None, ge=1, le=1000, strict=True)
    grades: list[GradeBand] = Field(min_length=1, max_length=3)
    interests: list[Interest] = Field(min_length=1, max_length=4)
    timing: Literal["Within 30 days", "Within 90 days", "Next school term", "Exploring"]
    deployment: Literal["Hosted", "On-site / private", "Need guidance"]
    notes: str = Field(default="", max_length=1200)
    consent: Literal[True]
    website: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def scope_matches_audience(self):
        if self.audience != "homeschool":
            if not self.organization or self.educators is None or self.sites is None:
                raise ValueError("Organization, educator count, and location count are required.")
        if self.audience == "coop" and self.families is None:
            raise ValueError("An estimated family count is required for a co-op.")
        if len(set(self.grades)) != len(self.grades) or len(set(self.interests)) != len(self.interests):
            raise ValueError("Selections must not be repeated.")
        return self
