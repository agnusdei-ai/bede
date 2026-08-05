"""Bede's MCP server — stdio transport.

Run this on the PARENT's own machine (not in the Bede container) and point an
MCP host at it — Claude Desktop, Claude Code, or anything else speaking MCP.
It gives that assistant read-only access to your own family's progress data,
so you can ask "how is Ada doing in math" wherever you already work instead of
opening the Bede parent UI.

    BEDE_API_URL=http://localhost:8000 \
    BEDE_PARENT_PASSWORD=... \
    python scripts/mcp_server/server.py

See docs/MCP.md for host configuration and the security rationale.

## Why stdio, and why this process is not part of the API

Bede is a self-hosted, LAN-deployed app whose whole security posture is that
it exposes as little as possible. Mounting an MCP endpoint inside the FastAPI
app would have added a new authenticated network surface to the same process
that serves children. This adds none: it is a subprocess on the parent's own
machine, spoken to over stdin/stdout by the MCP host that launched it, and it
reaches Bede through exactly the same authenticated REST endpoints the parent
UI already uses. There is no new endpoint, no new auth path, and nothing new
listening anywhere.

Everything that decides what may be asked for lives in bede_tools.py, which
has no MCP dependency and is unit-tested. This file is transport only, and is
kept small enough to review at a glance for exactly that reason.

## Every tool is annotated read-only, in the protocol itself

`ToolAnnotations(read_only_hint=True)` is not decoration. An MCP host can use
it to decide what may run without asking the user first, and a host that
prompts before mutating tools should never prompt for these — because none of
them can mutate anything (bede_tools.py issues GET requests exclusively, and
its test suite asserts that against real traffic rather than against the
source). Declaring it here makes that property visible to the host instead of
leaving it as something only this repository knows.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Literal

try:
    from mcp.server import MCPServer
    from mcp.types import ToolAnnotations
except ImportError:  # pragma: no cover - a setup error, not a runtime path
    sys.stderr.write(
        "The MCP SDK is not installed. Run:\n"
        "    pip install -r scripts/mcp_server/requirements.txt\n"
    )
    raise SystemExit(1)

from bede_tools import TOOL_SCHEMAS, BedeAuthError, BedeClient, dispatch

# stderr, never stdout — stdout IS the MCP transport, and a stray log line
# written there corrupts the protocol stream.
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("bede-mcp")

# Mirrors bede_tools.SUBJECT_AREAS. Spelled out rather than computed because
# typing.Literal needs literal members at definition time — the SDK derives
# each tool's input schema from these annotations, so this is what gives the
# model the actual enum instead of a bare string. test_server.py asserts the
# two stay in step.
SubjectArea = Literal[
    "mathematics", "composition", "phonics", "literacy", "language_exposure"
]

server: MCPServer = MCPServer("bede", version="1.0.0")
_client: BedeClient | None = None

_DESCRIPTIONS = {schema["name"]: schema["description"] for schema in TOOL_SCHEMAS}

# Read-only, and non-destructive. open_world_hint is False: these tools reach
# exactly one known deployment — the family's own Bede — not the open internet.
_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, open_world_hint=False
)


async def _call(name: str, **arguments) -> str:
    """Shared body for every tool below: dispatch, then serialize.

    Errors come back as tool CONTENT rather than raised exceptions so the
    assistant can relay the actual remedy ("your Bede has MFA enrolled, so
    this cannot log in") instead of reporting an opaque tool failure.
    """
    assert _client is not None  # set in main() before the server ever runs
    try:
        result = await dispatch(_client, name, arguments)
    except BedeAuthError as exc:
        return f"Bede login problem: {exc}"
    except ValueError as exc:
        return f"Bad request: {exc}"
    except Exception as exc:
        log.warning("Tool %s failed", name, exc_info=True)
        return f"Bede request failed: {exc}"
    return json.dumps(result, indent=2, default=str)


async def list_students() -> str:
    return await _call("list_students")


async def get_mastery_summary(
    student_name: str, subject_area: SubjectArea = "mathematics"
) -> str:
    return await _call(
        "get_mastery_summary", student_name=student_name, subject_area=subject_area
    )


async def get_work_ledger(student_name: str) -> str:
    return await _call("get_work_ledger", student_name=student_name)


async def get_pod_work_roster() -> str:
    return await _call("get_pod_work_roster")


async def get_narration_assessments(student_name: str) -> str:
    return await _call("get_narration_assessments", student_name=student_name)


async def get_learner_profile(student_name: str) -> str:
    return await _call("get_learner_profile", student_name=student_name)


_TOOL_FUNCTIONS = (
    list_students,
    get_mastery_summary,
    get_work_ledger,
    get_pod_work_roster,
    get_narration_assessments,
    get_learner_profile,
)


def register_tools(target: MCPServer) -> None:
    """Register every tool, taking each description from bede_tools.TOOL_SCHEMAS.

    Registered from a list rather than with inline decorators so that a
    function added here without a matching entry in TOOL_SCHEMAS raises at
    import time instead of shipping with an empty description — the model
    reads that description, so a blank one is a silent capability loss.
    """
    for fn in _TOOL_FUNCTIONS:
        target.add_tool(
            fn,
            name=fn.__name__,
            description=_DESCRIPTIONS[fn.__name__],
            annotations=_READ_ONLY,
        )


register_tools(server)


async def main() -> None:
    global _client
    try:
        _client = BedeClient.from_env()
    except BedeAuthError as exc:
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(1)

    try:
        await server.run_stdio_async()
    finally:
        await _client.aclose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
