"""Feature flag for the curriculum engine. Default: disabled."""

from __future__ import annotations

import os

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def curriculum_engine_enabled() -> bool:
    """True only when CURRICULUM_ENGINE_ENABLED is explicitly set to a true value."""
    return os.environ.get("CURRICULUM_ENGINE_ENABLED", "").strip().lower() in _TRUE_VALUES
