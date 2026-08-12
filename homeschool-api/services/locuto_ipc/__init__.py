"""
Bede's half of the Locuto local-IPC connector — see
`agnusdei-ai/locuto`'s `docs/bede-ipc-spec.md` (the single canonical copy
of the wire spec; nothing here duplicates it, only implements it) and this
repo's own `docs/LOCUTO_CONNECTOR_DECISIONS.md`.

v1 scope, deliberately: transport, framing, handshake, and Request/Response
dispatch only. The capability registry (capabilities.py) ships EMPTY — no
capability (`PrepareUserReviewableSendDraft` etc.) has an exact CBOR
input/output schema specified anywhere yet, so every `Request` for a real
capability name is refused until that capability gets its own spec. This
proves the boundary (socket permissions, peer-credential auth, framing
discipline, §6's `resolve_local_only()` enforcement point) without shipping
any actual agent behavior.

Linux/macOS (Unix domain socket) only in this pass. Windows (named pipe,
spec §2) is an explicit, separate follow-up — this environment cannot build
or test a Windows named-pipe listener for real, and shipping one unverified
would be exactly the kind of asserted-but-unchecked claim this whole
cross-repo effort has been careful to avoid.

Runs as its own process (`python -m services.locuto_ipc`), not inside the
main FastAPI `api` app — see `bede-connector.md` §2's own recommendation
and `decision-packets.md` packet 11's "process-boundary impact" note. It
imports this codebase's modules directly (same package, same
`resolve_local_only()`) but is a structurally separate listener with a much
smaller attack surface than the tutor-facing API.

`LOCUTO_IPC_ENABLED` (`core/config.py`) defaults True and the
`locuto-ipc` docker-compose service starts alongside the rest of the stack
by default — Bede is meant to interoperate with a paired Locuto
installation out of the box. This is safe precisely because of the empty
registry above: a deployment that never pairs with Locuto has a socket
that completes a handshake and refuses every real capability, nothing
more. A deployer can still set `LOCUTO_IPC_ENABLED=false` to disable the
listener outright (restart required — see `server.py`'s own docstring).
"""
