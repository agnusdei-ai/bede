"""Tests for the MCP server's tool layer (bede_tools.py).

No MCP dependency here by design — see that module's docstring. These run
against a stubbed httpx transport, so they exercise the real request-building,
auth, and refusal logic without a live Bede.

The assertions worth reading first are the ones about what this server
REFUSES: read-only-ness as a property of the code, and the fact that the
instructions restraining a consuming model live in the tool descriptions the
model actually reads rather than in a doc it does not.
"""

import json

import httpx
import pytest

from bede_tools import (
    SUBJECT_AREAS,
    TOOL_SCHEMAS,
    USER_AGENT,
    BedeAuthError,
    BedeClient,
    device_id,
    dispatch,
)

LOGIN_OK = {"access_token": "test-token", "role": "parent"}


def make_client(handler, password="pw"):
    """A BedeClient wired to an in-memory transport."""
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        transport=transport, headers={"User-Agent": USER_AGENT}
    )
    return BedeClient("http://bede.test", password, client=http)


def json_response(payload, status=200):
    return httpx.Response(status, json=payload)


# ── Read-only-ness ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_tool_issues_only_get_requests():
    """The central safety property: a parent asking their assistant about a
    child's progress must never be one hallucinated tool call away from
    mutating that child's record.

    This is asserted by observing real traffic rather than by reading the
    source, so it stays true if someone later adds a helper that posts.
    """
    seen = []

    def handler(request):
        seen.append(request.method)
        if request.url.path == "/auth/login":
            return json_response(LOGIN_OK)
        if request.url.path == "/pod/configs":
            return json_response([])
        return json_response({})

    client = make_client(handler)
    for schema in TOOL_SCHEMAS:
        args = {}
        if "student_name" in schema["inputSchema"]["properties"]:
            args["student_name"] = "Ada"
        await dispatch(client, schema["name"], args)

    assert seen, "no requests were made"
    # POST /auth/login is the one non-GET, and it is authentication rather
    # than a tool reaching a family's data.
    assert set(seen) == {"GET", "POST"}
    assert seen.count("POST") == 1


@pytest.mark.asyncio
async def test_no_tool_reaches_a_mutating_endpoint():
    """Belt and braces: nothing here touches a path the API mutates through."""
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/auth/login":
            return json_response(LOGIN_OK)
        return json_response([])

    client = make_client(handler)
    for schema in TOOL_SCHEMAS:
        args = {}
        if "student_name" in schema["inputSchema"]["properties"]:
            args["student_name"] = "Ada"
        await dispatch(client, schema["name"], args)

    for path in paths:
        assert "/delete" not in path
        assert not path.startswith("/tutor")
        assert not path.startswith("/admin")


# ── Auth ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mfa_enrolled_reports_an_actionable_error():
    """A deployment with parent MFA cannot be logged into without a browser.
    The parent needs to be told that specifically — not handed a 401."""

    def handler(request):
        return json_response(
            {"access_token": "pending", "role": "parent_pending", "mfa_required": True}
        )

    client = make_client(handler)
    with pytest.raises(BedeAuthError, match="MFA"):
        await client.list_students()


@pytest.mark.asyncio
async def test_rate_limited_login_is_distinguished_from_a_wrong_password():
    """429 means "wait", not "your password is wrong" — telling a parent to
    re-check a correct password sends them to change credentials they did not
    need to touch."""

    def handler(request):
        return httpx.Response(429)

    client = make_client(handler)
    with pytest.raises(BedeAuthError, match="rate-limit"):
        await client.list_students()


@pytest.mark.asyncio
async def test_a_401_triggers_exactly_one_re_login_then_gives_up():
    """A parent changing their password invalidates every live token
    immediately (by design — core/parent_credential.py). One retry recovers
    from that; looping on a genuinely rejected token would hammer the lockout
    counter the API keeps for the parent role."""
    logins = []
    calls = []

    def handler(request):
        if request.url.path == "/auth/login":
            logins.append(1)
            return json_response(LOGIN_OK)
        calls.append(1)
        return httpx.Response(401)

    client = make_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await client.list_students()

    assert len(logins) == 2  # initial + one retry
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_login_sends_the_field_names_the_api_requires():
    """models.schemas.LoginRequest names ONE field for all three roles —
    `credential` (password for parent, PIN for child, code for demo) — not
    `password`.

    The first cut of this module sent `password`, which the real API would
    have rejected as a 422 on the very first call. Nothing caught it: the
    unit tests stubbed the transport, and the end-to-end stub accepted any
    JSON body. This asserts the wire contract explicitly, since a permissive
    fake is exactly what let a wrong field name pass twice.
    """
    bodies = []

    def handler(request):
        if request.url.path == "/auth/login":
            bodies.append(json.loads(request.content))
            return json_response(LOGIN_OK)
        return json_response([])

    client = make_client(handler, password="hunter2")
    await client.list_students()

    assert len(bodies) == 1
    body = bodies[0]
    assert body["role"] == "parent"
    assert body["credential"] == "hunter2"
    assert "password" not in body


@pytest.mark.asyncio
async def test_login_registers_a_device_so_it_can_be_revoked():
    """This process holds a parent password and can read every child's
    progress. Sending a device_id is optional at the API — and omitting it
    means a token that can never be revoked, because core/deps.py treats a
    missing device_id claim as nothing-to-revoke.

    So it must be sent: a parent has to be able to cut this off from Bede's
    device settings like any other device.
    """
    bodies = []

    def handler(request):
        if request.url.path == "/auth/login":
            bodies.append(json.loads(request.content))
            return json_response(LOGIN_OK)
        return json_response([])

    client = make_client(handler)
    await client.list_students()
    assert bodies[0].get("device_id")


def test_device_id_is_stable_across_instances():
    """Stable, or every restart registers a new device and the parent's
    device list fills with entries they cannot tell apart."""
    assert device_id() == device_id()


def test_device_id_respects_an_override_and_fits_the_column():
    """DeviceRecord.device_id is String(64); LoginRequest enforces that with
    max_length, so an oversized override would be a 422 rather than silent
    truncation server-side."""
    assert device_id({"BEDE_MCP_DEVICE_ID": "my-laptop"}) == "my-laptop"
    assert len(device_id({"BEDE_MCP_DEVICE_ID": "x" * 200})) == 64
    assert len(device_id({})) <= 64


@pytest.mark.asyncio
async def test_a_422_is_reported_as_a_version_mismatch_not_a_bad_password():
    """A schema disagreement and a wrong secret need different remedies."""

    def handler(request):
        return httpx.Response(422, json={"detail": "field required"})

    client = make_client(handler)
    with pytest.raises(BedeAuthError, match="malformed"):
        await client.list_students()


@pytest.mark.asyncio
async def test_login_sends_the_pinned_user_agent():
    """Bede binds a JWT to the User-Agent it was issued to, so the login and
    every later call have to agree on one."""
    agents = []

    def handler(request):
        agents.append(request.headers.get("user-agent"))
        if request.url.path == "/auth/login":
            return json_response(LOGIN_OK)
        return json_response([])

    client = make_client(handler)
    await client.list_students()
    assert set(agents) == {USER_AGENT}


def test_from_env_names_the_missing_variable():
    with pytest.raises(BedeAuthError, match="BEDE_API_URL"):
        BedeClient.from_env({})
    with pytest.raises(BedeAuthError, match="BEDE_PARENT_PASSWORD"):
        BedeClient.from_env({"BEDE_API_URL": "http://bede.test"})


# ── Tool behavior ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_students_returns_only_roster_fields():
    """A student config carries far more than a roster needs (lesson resume
    notes, faith tradition, curriculum resources). Only the fields an
    assistant needs to name a student and know what they study are passed
    on."""

    def handler(request):
        if request.url.path == "/auth/login":
            return json_response(LOGIN_OK)
        return json_response(
            [
                {
                    "student_name": "Ada",
                    "grade": "4",
                    "subjects": ["mathematics"],
                    "companion_mode": "full_plan",
                    "faith_tradition": "Baptist",
                    "lesson_resume": [{"subject": "mathematics", "stopped_at": "x"}],
                }
            ]
        )

    client = make_client(handler)
    students = await client.list_students()
    assert students == [
        {
            "student_name": "Ada",
            "grade": "4",
            "subjects": ["mathematics"],
            "companion_mode": "full_plan",
        }
    ]
    assert "faith_tradition" not in students[0]
    assert "lesson_resume" not in students[0]


@pytest.mark.asyncio
async def test_mastery_summary_rejects_an_unknown_subject_area():
    """Rejected before it becomes a request, so a typo is a clear error
    rather than a 404 or an empty summary that reads as 'no progress'."""

    def handler(request):
        return json_response(LOGIN_OK)

    client = make_client(handler)
    with pytest.raises(ValueError, match="Unknown subject_area"):
        await client.get_mastery_summary("Ada", "astrology")


@pytest.mark.asyncio
async def test_mastery_summary_passes_the_subject_area_through():
    seen = {}

    def handler(request):
        if request.url.path == "/auth/login":
            return json_response(LOGIN_OK)
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return json_response({"student_name": "Ada"})

    client = make_client(handler)
    await client.get_mastery_summary("Ada", "phonics")
    assert seen["path"] == "/diagnostic/Ada/summary"
    assert seen["params"] == {"subject_area": "phonics"}


@pytest.mark.asyncio
async def test_dispatch_rejects_an_unknown_tool_name():
    """A hallucinated name must never fall through to some other tool's
    data."""

    def handler(request):
        return json_response(LOGIN_OK)

    client = make_client(handler)
    with pytest.raises(ValueError, match="Unknown tool"):
        await dispatch(client, "get_everything", {})


# ── The refusals, in the text the model actually reads ──────────────────


def test_pod_roster_description_forbids_ranking():
    """The API refuses to emit a ranking and PodWorkRoster.tsx refuses to
    render one, but a consuming model can reintroduce one the data does not
    contain just by summing. The refusal therefore has to appear in the tool
    description itself — this is the only instruction that model gets."""
    description = next(
        s["description"] for s in TOOL_SCHEMAS if s["name"] == "get_pod_work_roster"
    )
    lowered = description.lower()
    assert "not a ranking" in lowered
    assert "do not total" in lowered
    assert "ahead of" in lowered
    assert "absent" in lowered


def test_work_ledger_description_forbids_averaging_and_protects_blanks():
    """summarize() emits distributions and never an average, because a mean
    over an ordinal scale invents precision and reads as a grade. And a blank
    must stay distinguishable from a low mark — WorkLedger.tsx's own hardest
    rule."""
    description = next(
        s["description"] for s in TOOL_SCHEMAS if s["name"] == "get_work_ledger"
    )
    lowered = description.lower()
    assert "average" in lowered
    assert "not a low mark" in lowered


def test_mastery_description_surfaces_the_calibration_caveat():
    """Reporting a provisional cold-start estimate as a finding is the most
    likely way this data gets misused."""
    description = next(
        s["description"] for s in TOOL_SCHEMAS if s["name"] == "get_mastery_summary"
    )
    assert "calibration" in description.lower()
    assert "not test scores" in description.lower().replace("’", "'")


def test_learner_profile_description_disclaims_the_style_label():
    """processing_style is a nudge to Bede's tool choice, explicitly not a
    psychometric claim — CLAUDE.md says so, and so must this."""
    description = next(
        s["description"] for s in TOOL_SCHEMAS if s["name"] == "get_learner_profile"
    )
    assert "psychometric" in description.lower()


def test_no_tool_exposes_anything_about_faith_engagement():
    """The constitution governs the faith dimension qualitatively, by rule,
    and never as a metric. No such signal exists to expose; this test is here
    so that adding one has to fail a test rather than pass a review."""
    blob = json.dumps(TOOL_SCHEMAS).lower()
    for forbidden in ("faith_score", "faith_engagement", "spiritual_growth", "piety_score"):
        assert forbidden not in blob


def test_every_schema_is_well_formed():
    names = set()
    for schema in TOOL_SCHEMAS:
        assert schema["name"] not in names, "duplicate tool name"
        names.add(schema["name"])
        assert schema["description"].strip()
        assert schema["inputSchema"]["type"] == "object"
        for required in schema["inputSchema"]["required"]:
            assert required in schema["inputSchema"]["properties"]


def test_subject_areas_are_the_ones_the_diagnostic_engine_rolls_up():
    assert set(SUBJECT_AREAS) == {
        "mathematics",
        "composition",
        "phonics",
        "literacy",
        "language_exposure",
    }
