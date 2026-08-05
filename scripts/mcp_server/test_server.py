"""Tests for the MCP transport shim (server.py).

Separate from test_bede_tools.py because these DO import the `mcp` SDK.
bede_tools.py is deliberately SDK-free so its logic can be tested without one
(see its docstring); this file covers the seam between that logic and the
protocol, which is exactly where the first cut of this server broke — it was
written against the SDK's 1.x decorator API, passed every bede_tools test,
and could not start at all.

That failure is why `test_every_declared_tool_is_registered` exists. A unit
test of the logic cannot see a transport that never comes up.
"""

import pytest

import bede_tools
import server


@pytest.mark.asyncio
async def test_every_declared_tool_is_registered():
    """The registered set and the declared set are one fact in two places."""
    registered = {tool.name for tool in await server.server.list_tools()}
    declared = {schema["name"] for schema in bede_tools.TOOL_SCHEMAS}
    assert registered == declared


@pytest.mark.asyncio
async def test_every_tool_is_annotated_read_only():
    """The protocol-level counterpart to bede_tools' GET-only guarantee.

    An MCP host uses these annotations to decide what may run without asking
    the user first. Since nothing here can mutate a family's data, saying so
    in the protocol is both true and useful — and a tool added later without
    that guarantee should fail this rather than quietly inherit the claim.
    """
    for tool in await server.server.list_tools():
        assert tool.annotations is not None, f"{tool.name} has no annotations"
        assert tool.annotations.read_only_hint is True, f"{tool.name} is not read-only"
        assert tool.annotations.destructive_hint is False


@pytest.mark.asyncio
async def test_every_tool_carries_its_declared_description():
    """The description is the only instruction the consuming model gets, and
    the refusals this codebase cares about (the pod roster is not a ranking,
    a blank is not a low mark) live in it. A tool registered with a blank or
    default description is a silent loss of all of that."""
    declared = {s["name"]: s["description"] for s in bede_tools.TOOL_SCHEMAS}
    for tool in await server.server.list_tools():
        assert tool.description == declared[tool.name]
        assert tool.description.strip()


@pytest.mark.asyncio
async def test_subject_area_enum_matches_bede_tools():
    """server.py spells the subject areas out in a typing.Literal (the SDK
    derives each tool's input schema from the annotation, so this is what
    gives the model a real enum). Two copies of one list — checked here
    rather than trusted."""
    schema = next(
        t.input_schema
        for t in await server.server.list_tools()
        if t.name == "get_mastery_summary"
    )
    subject_area = schema["properties"]["subject_area"]
    assert set(subject_area["enum"]) == set(bede_tools.SUBJECT_AREAS)
    assert subject_area["default"] == "mathematics"


@pytest.mark.asyncio
async def test_student_name_is_required_where_it_applies():
    """A tool that made student_name optional would silently operate on
    whatever the server felt like — there is no sensible default child."""
    per_student = {
        "get_mastery_summary",
        "get_work_ledger",
        "get_narration_assessments",
        "get_learner_profile",
    }
    for tool in await server.server.list_tools():
        if tool.name in per_student:
            assert "student_name" in tool.input_schema.get("required", []), tool.name
