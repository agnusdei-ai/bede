"""Operator-facing Bede offer catalog; pricing is not an access decision.

Separates COMMERCIAL consideration from the Ed25519-verified license:
a quoted dollar figure must never grant access or erase a signed seat cap.

The campus location offer grants unlimited enrolled learner SEATS within
one location. AI inference throughput, simultaneous user capacity, uptime,
hardware suitability and cross-location deployment are not unlimited.
Mac mini hardware is sold separately, never silently included.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

INDIVIDUAL_LEARNER_MONTH_USD = Decimal("25.00")
CAMPUS_LOCATION_MONTH_USD = Decimal("3500.00")
CAMPUS_LOCATION_ANNUAL_USD = CAMPUS_LOCATION_MONTH_USD * 12
BREAKEVEN_LEARNERS = 140


@dataclass(frozen=True)
class BedeOffer:
    code: str
    monthly_price_usd: Decimal
    billing_unit: str
    unlimited_enrolled_learners: bool
    hardware_included: bool
    ai_capacity_unlimited: bool
    location_license_scope: str


PER_LEARNER = BedeOffer(
    code="per_learner_monthly",
    monthly_price_usd=INDIVIDUAL_LEARNER_MONTH_USD,
    billing_unit="learner",
    unlimited_enrolled_learners=False,
    hardware_included=False,
    ai_capacity_unlimited=False,
    location_license_scope="sold_as_licensed",
)
CAMPUS_LOCATION = BedeOffer(
    code="campus_location_monthly",
    monthly_price_usd=CAMPUS_LOCATION_MONTH_USD,
    billing_unit="one_physical_school_location",
    unlimited_enrolled_learners=True,
    hardware_included=False,
    ai_capacity_unlimited=False,
    location_license_scope="one_signed_location_per_deployment",
)


def quote_monthly(*, offer: BedeOffer, learners: int = 1, locations: int = 1) -> Decimal:
    """Pure quote function, not a checkout, billing integration or entitlement.

    In campus pricing, learner count is informative and never changes
    subscription price. Each additional campus/location requires its own
    subscription and independently signed site license.
    """
    if not isinstance(learners, int) or isinstance(learners, bool) or learners < 1:
        raise ValueError("learners must be a positive integer")
    if not isinstance(locations, int) or isinstance(locations, bool) or locations < 1:
        raise ValueError("locations must be a positive integer")
    if offer == CAMPUS_LOCATION:
        return CAMPUS_LOCATION_MONTH_USD * locations
    if offer == PER_LEARNER:
        return INDIVIDUAL_LEARNER_MONTH_USD * learners
    raise ValueError("unrecognized offer requires an explicit operator review")
