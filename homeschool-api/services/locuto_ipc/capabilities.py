"""
The capability registry — bede-connector.md §4's closed vocabulary,
enforced here as an actual closed dict rather than a comment promising one.

EMPTY in this version, deliberately. `bede-connector.md`'s
`DraftReplyFromUserSelectedText`, `SummarizeUserSelectedMessages`, etc. are
illustrative capability NAMES — none of them has an exact CBOR input/output
schema specified anywhere yet. bede-ipc-spec.md §4 is explicit that "a new
capability is a new named message body, declared per §5, never a widening
of an existing one." Registering a capability here without that
declaration existing first would mean this module inventing the schema
unilaterally, which is exactly the "widening" the spec forbids.

A Request naming anything not in CAPABILITIES is refused
(protocol.refused()) — server.py's dispatch never falls through to a
default handler or a generic invocation path. See
bede-connector.md §4's own "not capabilities" list, in particular
`InvokeArbitraryLocutoMethod` and `CallTutorTools` — this registry's shape
is what makes both of those structurally absent rather than merely
undocumented.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

# A capability handler receives the Request's already-validated `input`
# dict and returns the `output` dict for a Succeeded Response, or raises
# services.adapters.router.LocalAdapterUnavailableError to signal
# Outcome.Unavailable (server.py's dispatch translates that exception into
# the correct Response — see its docstring for why the translation lives
# there and not here). A handler must resolve any model client it needs
# via services.adapters.router.resolve_local_only() — bede-ipc-spec.md §6 —
# and never any other resolver in services/adapters/.
CapabilityHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

CAPABILITIES: dict[str, CapabilityHandler] = {}


def is_registered(name: str) -> bool:
    return name in CAPABILITIES


def get_handler(name: str) -> CapabilityHandler | None:
    return CAPABILITIES.get(name)
