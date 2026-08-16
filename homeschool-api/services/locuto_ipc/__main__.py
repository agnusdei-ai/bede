"""
Entrypoint: `python -m services.locuto_ipc`. Deliberately minimal —
this process does NOT run main.py's full lifespan (constitution
verification, license gating, voice-model warm-up, data-retention purge,
etc.), because none of that is this listener's concern. It needs only
core.config.settings and services.adapters.router — both dependency-free
of the database.

Audit logging (core/audit.py's log_event) is used from within a capability
handler if a future one chooses to call it, and log_event already fails
open on its own (catches and logs locally rather than raising) if the
database/encryption haven't been initialized — this entrypoint does not
force that initialization just to make an optional audit write possible,
matching this module's own "small, separately-scoped" design goal.
"""
from __future__ import annotations

import asyncio
import logging

from .server import serve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
