"""Owner-approved public beta endpoint, independent of paid license terms."""

from datetime import datetime, timezone

# Midnight after December 31, 2026 in America/Chicago (CST).
# Extending this requires an explicit reviewed code change, not a client clock.
PUBLIC_DEMO_CLOSES_AT = datetime(2027, 1, 1, 6, tzinfo=timezone.utc)
PUBLIC_DEMO_CLOSED_MESSAGE = (
    "The public demo beta ended December 31, 2026. "
    "Request onboarding at https://agnusdei.ai/inquire/ or email info@agnusdei.ai."
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def public_demo_closed() -> bool:
    return utc_now() >= PUBLIC_DEMO_CLOSES_AT
