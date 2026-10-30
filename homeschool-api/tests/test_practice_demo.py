"""The public demo's Practice Coach (routers/practice_demo.py,
services/practice/demo_store.py, docs/PRACTICE_COACH.md "On the public demo").

What these pin, each verified by breaking the thing it guards:

* demo-code auth only, in BOTH directions, and the routes cannot shadow a
  real family's /practice/{student}/... routes;
* the upload quota is spent BEFORE any model call, and a refusal never
  reaches one;
* consent is refused before a single byte is decoded, without spending a slot;
* reading is always cloud (a configured local model is never used);
* nothing is written to any table, and the workspace is gone on logout, on
  the code-expiry sweep and on TTL.
"""
import ast
import base64
import copy
import io
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.params import Depends as DependsType
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from starlette.requests import Request

import core.demo_code_session as demo_code_session
from core.audit import AuditEvent
from core.deps import require_demo_practice, require_parent
from core.middleware import compute_fingerprint
from core.security import create_access_token
from models.practice import (
    ApproveSetRequest,
    ConfirmAssessmentRequest,
    DemoReadPhotosRequest,
    GradedAssessment,
    PhotoPage,
)
from routers import practice as real_practice_router
from routers import practice_demo as demo_router
from services.practice import demo_store, extract, upload_safety

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]

_GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "services/practice/packs/latin/golden/latin_quiz_1.expected.json")
    .read_text(encoding="utf-8")
)["assessment"]


def _png(color) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(out, format="PNG")
    return out.getvalue()


PHOTO = _png((200, 30, 30))


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", b"pytest")]})


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _token(role: str, **extra) -> str:
    payload = {"sub": role, "role": role}
    if role == "parent":
        payload["cv"] = 0
    payload.update(extra)
    return create_access_token(payload, fingerprint=compute_fingerprint("127.0.0.1", "pytest"))


@pytest.fixture(autouse=True)
def _clean_store():
    demo_store.clear_all()
    yield
    demo_store.clear_all()


class StubClient:
    def __init__(self, text_):
        self.text, self.calls = text_, []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"content": [type("B", (), {"text": self.text})()]})()


def _routing(monkeypatch, *, local=None, cloud="openai", cloud_client=None):
    from services.adapters import router
    import services.ai_service as ai_service

    configured = (["local"] if local is not None else []) + ([cloud] if cloud else [])
    monkeypatch.setattr(router, "configured_adapters", lambda *a, **k: configured)
    monkeypatch.setattr(router, "preference_order", lambda *a, **k: ["local", "openai", "mistral", "anthropic"])
    monkeypatch.setattr(router, "resolve_local_only", lambda *a, **k: local)
    if cloud_client is not None:
        monkeypatch.setattr(ai_service, "_client", cloud_client)


@pytest.fixture
def audit(monkeypatch):
    calls = []

    async def fake(event, **kw):
        calls.append((event, kw))

    monkeypatch.setattr(demo_router, "log_event", fake)
    return calls


def _req(consent=True, pages=1, subject="latin"):
    return DemoReadPhotosRequest(
        subject=subject, pages=[PhotoPage(data=b64(PHOTO)) for _ in range(pages)], cloud_consent=consent,
    )


async def _code():
    return await demo_code_session.generate_code("Guest", "4")


async def _read(code, req=None):
    return await demo_router.read_assessment(req or _req(), _request(), auth={"role": "demo_code", "code": code})


def _settled() -> GradedAssessment:
    data = copy.deepcopy(_GOLDEN)
    for section in data["sections"]:
        for item in section["items"]:
            if item.get("ask_parent"):
                item["ask_parent"], item["confidence"] = None, 0.95
    return GradedAssessment.model_validate(data)


# ── Route auth separation, both directions ───────────────────────────────────

async def test_a_demo_code_reaches_the_demo_routes_and_not_the_real_ones():
    code = await _code()
    payload = await require_demo_practice(_request(), _bearer(_token("demo_code", code=code)))
    assert payload["code"] == code
    with pytest.raises(HTTPException) as exc:
        await require_parent(_request(), _bearer(_token("demo_code", code=code)))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["parent", "child", "educator", "parent_pending", "parent_recovery"])
async def test_no_family_or_transient_session_reaches_the_demo_routes(role):
    with pytest.raises(HTTPException) as exc:
        await require_demo_practice(_request(), _bearer(_token(role)))
    assert exc.value.status_code in (401, 403)


async def test_a_logged_out_demo_code_is_refused():
    code = await _code()
    await demo_code_session.end_session(code)
    with pytest.raises(HTTPException) as exc:
        await require_demo_practice(_request(), _bearer(_token("demo_code", code=code)))
    assert exc.value.status_code == 401


def _guards(route):
    import inspect
    return [p.default.dependency for p in inspect.signature(route.endpoint).parameters.values()
            if isinstance(p.default, DependsType)]


def test_every_demo_route_is_guarded_by_the_demo_dependency_alone():
    assert demo_router.router.routes
    for route in demo_router.router.routes:
        assert require_demo_practice in _guards(route), route.path
        assert require_parent not in _guards(route), route.path


def test_every_real_practice_route_still_requires_a_parent_and_not_the_demo_dependency():
    for route in real_practice_router.router.routes:
        assert require_parent in _guards(route), route.path
        assert require_demo_practice not in _guards(route), route.path


def test_the_demo_prefix_cannot_shadow_a_real_students_routes():
    """A child named "Demo" must still reach /practice/Demo/..., so no demo
    route may live under /practice/."""
    assert demo_router.router.prefix == "/practice-demo"
    for route in demo_router.router.routes:
        assert not route.path.startswith("/practice/"), route.path


# ── Consent: refused before anything is parsed, never spends a slot ──────────

async def test_missing_consent_is_refused_before_any_parse_or_model_call_and_costs_nothing(monkeypatch, audit):
    cloud = StubClient(json.dumps(_GOLDEN))
    _routing(monkeypatch, cloud="openai", cloud_client=cloud)

    async def must_not_parse(*a, **k):
        raise AssertionError("a file was decoded without consent")

    monkeypatch.setattr(extract, "prepare_pages", must_not_parse)
    monkeypatch.setattr(upload_safety, "prepare_pages", must_not_parse)
    code = await _code()
    with pytest.raises(HTTPException) as exc:
        await _read(code, _req(consent=False))
    assert exc.value.status_code == 409
    assert exc.value.detail["consent_required"] is True
    assert exc.value.detail["provider"] == "openai"
    assert cloud.calls == []
    assert demo_store.uploads_remaining(code) == demo_store.MAX_UPLOADS_PER_CODE


async def test_the_demo_never_reads_on_a_local_model_even_when_one_is_configured(monkeypatch, audit):
    local, cloud = StubClient("{}"), StubClient(json.dumps(_GOLDEN))
    _routing(monkeypatch, local=local, cloud="openai", cloud_client=cloud)
    code = await _code()
    await _read(code)
    assert len(cloud.calls) == 1 and local.calls == []

    # And with ONLY a local model there is no demo reading at all, never a local one.
    _routing(monkeypatch, local=local, cloud=None)
    with pytest.raises(HTTPException) as exc:
        await _read(code)
    assert exc.value.status_code == 409
    assert local.calls == []
    assert (await demo_router.get_reading_route(auth={"role": "demo_code", "code": code}))["cloud_provider"] is None


# ── Quota: spent before the model, enforced before the model ─────────────────

async def test_an_over_quota_upload_never_calls_the_model_and_is_audited(monkeypatch, audit):
    cloud = StubClient(json.dumps(_GOLDEN))
    _routing(monkeypatch, cloud="openai", cloud_client=cloud)
    code = await _code()
    for _ in range(demo_store.MAX_UPLOADS_PER_CODE):
        await _read(code)
    assert len(cloud.calls) == demo_store.MAX_UPLOADS_PER_CODE

    with pytest.raises(HTTPException) as exc:
        await _read(code)
    assert exc.value.status_code == 429 and exc.value.detail["demo_practice_quota"] is True
    assert len(cloud.calls) == demo_store.MAX_UPLOADS_PER_CODE  # the sentinel: no further model call
    assert audit[-1][0] == AuditEvent.RATE_LIMITED and audit[-1][1]["detail"] == "demo_practice_quota"


async def test_the_quota_is_per_code_and_a_second_code_has_its_own(monkeypatch, audit):
    _routing(monkeypatch, cloud="openai", cloud_client=StubClient(json.dumps(_GOLDEN)))
    first, second = await _code(), await _code()
    for _ in range(demo_store.MAX_UPLOADS_PER_CODE):
        await _read(first)
    await _read(second)
    assert demo_store.uploads_remaining(second) == demo_store.MAX_UPLOADS_PER_CODE - 1


async def test_the_process_wide_hourly_ceiling_stops_a_visitor_minting_many_codes(monkeypatch, audit):
    cloud = StubClient(json.dumps(_GOLDEN))
    _routing(monkeypatch, cloud="openai", cloud_client=cloud)
    monkeypatch.setattr(demo_store, "MAX_UPLOADS_PER_HOUR_GLOBAL", 2)
    a, b, c = await _code(), await _code(), await _code()
    await _read(a)
    await _read(b)
    with pytest.raises(HTTPException) as exc:
        await _read(c)
    assert exc.value.status_code == 429
    assert len(cloud.calls) == 2
    assert audit[-1][1]["detail"] == "demo_practice_quota_global"


async def test_a_refused_file_gives_the_slot_back_but_a_failed_reading_does_not(monkeypatch, audit):
    cloud = StubClient("not json at all")
    _routing(monkeypatch, cloud="openai", cloud_client=cloud)
    code = await _code()

    bad = DemoReadPhotosRequest(subject="latin", pages=[PhotoPage(data=b64(b"not an image at all"))], cloud_consent=True)
    with pytest.raises(HTTPException) as exc:
        await _read(code, bad)
    assert exc.value.status_code == 422
    assert cloud.calls == []
    assert demo_store.uploads_remaining(code) == demo_store.MAX_UPLOADS_PER_CODE  # we refused it, they did not pay

    with pytest.raises(HTTPException) as exc:
        await _read(code)  # a model WAS called and answered garbage
    assert exc.value.status_code == 502 and len(cloud.calls) == 1
    assert demo_store.uploads_remaining(code) == demo_store.MAX_UPLOADS_PER_CODE - 1


async def test_the_page_cap_holds_for_a_pdf_that_expands_past_it_before_any_model_call(monkeypatch, audit):
    cloud = StubClient(json.dumps(_GOLDEN))
    _routing(monkeypatch, cloud="openai", cloud_client=cloud)

    async def four_pages(_data):
        return [("image/png", b64(PHOTO))] * (demo_store.MAX_PAGES_PER_UPLOAD + 1)

    monkeypatch.setattr(extract, "prepare_pages", four_pages)
    code = await _code()
    with pytest.raises(HTTPException) as exc:
        await _read(code)
    assert exc.value.status_code == 422
    assert cloud.calls == []
    assert demo_store.uploads_remaining(code) == demo_store.MAX_UPLOADS_PER_CODE


def test_the_request_itself_caps_pages_at_the_demo_limit():
    with pytest.raises(Exception):
        _req(pages=demo_store.MAX_PAGES_PER_UPLOAD + 1)


# ── The whole flow, and nothing is stored anywhere ───────────────────────────

async def _all_rows(demo_db):
    from core.database import Base
    out = {}
    async with demo_db() as db:
        for table in Base.metadata.sorted_tables:
            rows = (await db.execute(select(table))).all()
            out[table.name] = [json.dumps([repr(c) for c in r]) for r in rows]
    return out


async def test_the_whole_flow_works_and_leaves_no_trace_in_any_table(monkeypatch, audit, demo_db):
    cloud = StubClient(json.dumps(_GOLDEN))
    _routing(monkeypatch, cloud="openai", cloud_client=cloud)
    code = await _code()
    auth = {"role": "demo_code", "code": code}

    read = await _read(code)
    assert read["status"] == "needs_review" and len(read["ask_parent"]) == 2
    with pytest.raises(HTTPException) as exc:  # a flagged reading cannot be planned
        await demo_router.plan_practice(read["id"], auth=auth)
    assert exc.value.status_code == 409

    confirmed = await demo_router.confirm_assessment(read["id"], ConfirmAssessmentRequest(assessment=_settled()), auth=auth)
    assert confirmed["status"] == "confirmed"
    planned = await demo_router.plan_practice(read["id"], auth=auth)
    assert planned["status"] == "draft" and planned["practice_set"]["items"]

    marker = _GOLDEN["sections"][0]["items"][0]["prompt"]
    held = demo_store.load_reading(code, read["id"])
    assert held is not None and marker in held.assessment.model_dump_json()  # it IS held, in memory

    approved = await demo_router.approve_set(planned["set_id"], ApproveSetRequest(), auth=auth)
    assert approved["status"] == "approved"
    with pytest.raises(HTTPException) as exc:
        await demo_router.discard_set(planned["set_id"], auth=auth)
    assert exc.value.status_code == 409

    rows = await _all_rows(demo_db)
    assert rows["practice_assessments"] == [] and rows["practice_sets"] == []
    dump = json.dumps(rows)
    assert b64(PHOTO)[:24] not in dump
    assert marker not in dump
    assert planned["summary"][:40] not in dump


async def test_other_codes_records_answer_exactly_like_missing_ones(monkeypatch, audit):
    _routing(monkeypatch, cloud="openai", cloud_client=StubClient(json.dumps(_GOLDEN)))
    mine, theirs = await _code(), await _code()
    read = await _read(mine)
    await demo_router.confirm_assessment(read["id"], ConfirmAssessmentRequest(assessment=_settled()),
                                         auth={"role": "demo_code", "code": mine})
    planned = await demo_router.plan_practice(read["id"], auth={"role": "demo_code", "code": mine})
    other = {"role": "demo_code", "code": theirs}
    for call in (
        lambda: demo_router.plan_practice(read["id"], auth=other),
        lambda: demo_router.plan_practice(99999, auth={"role": "demo_code", "code": mine}),
        lambda: demo_router.approve_set(planned["set_id"], ApproveSetRequest(), auth=other),
        lambda: demo_router.discard_set(planned["set_id"], auth=other),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert (exc.value.status_code, exc.value.detail) == (404, "Record not found")


async def test_a_visitor_keeps_only_a_few_draft_sets(monkeypatch, audit):
    _routing(monkeypatch, cloud="openai", cloud_client=StubClient(json.dumps(_GOLDEN)))
    code = await _code()
    auth = {"role": "demo_code", "code": code}
    read = await _read(code)
    await demo_router.confirm_assessment(read["id"], ConfirmAssessmentRequest(assessment=_settled()), auth=auth)
    for _ in range(demo_store.MAX_SETS_PER_CODE):
        await demo_router.plan_practice(read["id"], auth=auth)
    with pytest.raises(HTTPException) as exc:
        await demo_router.plan_practice(read["id"], auth=auth)
    assert exc.value.status_code == 409


# ── Eviction ─────────────────────────────────────────────────────────────────

async def test_logout_deletes_the_workspace(monkeypatch, audit):
    _routing(monkeypatch, cloud="openai", cloud_client=StubClient(json.dumps(_GOLDEN)))
    code = await _code()
    await _read(code)
    assert demo_store.has_workspace(code)
    await demo_code_session.end_session(code)
    assert not demo_store.has_workspace(code)
    assert demo_store.uploads_remaining(code) == demo_store.MAX_UPLOADS_PER_CODE


async def test_minting_a_code_sweeps_expired_workspaces(monkeypatch, audit):
    _routing(monkeypatch, cloud="openai", cloud_client=StubClient(json.dumps(_GOLDEN)))
    code = await _code()
    await _read(code)
    demo_store._workspaces[code].created_at -= demo_store.TTL_SECONDS + 1
    await _code()  # generate_code() runs the same sweep as its SQL deletes
    assert code not in demo_store._workspaces


async def test_a_workspace_past_its_ttl_is_absent_to_every_read(monkeypatch, audit):
    _routing(monkeypatch, cloud="openai", cloud_client=StubClient(json.dumps(_GOLDEN)))
    code = await _code()
    read = await _read(code)
    demo_store._workspaces[code].created_at -= demo_store.TTL_SECONDS + 1
    assert demo_store.load_reading(code, read["id"]) is None
    with pytest.raises(HTTPException) as exc:
        await demo_router.plan_practice(read["id"], auth={"role": "demo_code", "code": code})
    assert exc.value.status_code == 404


def test_the_store_ttl_is_the_demo_codes_own():
    assert demo_store.TTL_SECONDS == demo_code_session._CODE_TTL_SECONDS


def test_the_store_is_bounded():
    for i in range(demo_store._MAX_WORKSPACES + 25):
        demo_store.reserve_upload(f"code-{i}")
    assert len(demo_store._workspaces) <= demo_store._MAX_WORKSPACES


# ── Structure: no database in the demo path ──────────────────────────────────

_API = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


@pytest.mark.parametrize("rel", ["routers/practice_demo.py", "services/practice/demo_store.py"])
def test_the_demo_path_imports_no_database_and_not_the_encrypted_store(rel):
    imported = _imports(_API / rel)
    forbidden = {n for n in imported if n in {
        "core.database", "core.database.get_db", "core.database.AsyncSessionLocal",
        "services.practice.store", "services.practice.store.save_assessment",
        "sqlalchemy.ext.asyncio.AsyncSession", "core.encryption", "core.student_keys",
    } or n.startswith("core.database.") or n.startswith("services.practice.store")}
    assert not forbidden, f"{rel} reaches storage: {sorted(forbidden)}"


def test_logout_and_the_expiry_sweep_both_reach_the_store():
    import re
    src = (_API / "core" / "demo_code_session.py").read_text()
    end = re.search(r"async def end_session\(.*?(?=\nasync def |\ndef )", src, re.S).group(0)
    gen = re.search(r"async def generate_code\(.*?(?=\nasync def |\ndef )", src, re.S).group(0)
    assert re.search(r"demo_store\.discard\(code\)", end)
    assert re.search(r"demo_store\.sweep\(\)", gen)


# ── The demo's TypeScript and this backend are one contract ──────────────────

_DEMO_SRC = Path(__file__).resolve().parents[2] / "demo" / "src"


def test_the_demo_page_cap_is_the_backends():
    import re
    src = (_DEMO_SRC / "practiceCoachLogic.ts").read_text()
    assert int(re.search(r"export const MAX_PAGES = (\d+)", src).group(1)) == demo_store.MAX_PAGES_PER_UPLOAD
    longest = [m.max_length for m in DemoReadPhotosRequest.model_fields["pages"].metadata if hasattr(m, "max_length")]
    assert longest == [demo_store.MAX_PAGES_PER_UPLOAD]


def test_every_path_the_demo_client_calls_is_a_route_with_that_method():
    import re
    src = (_DEMO_SRC / "api.ts").read_text()
    section = src[src.index("// ── Practice Coach"):]
    calls = re.findall(r"practiceFetch<.*?>\(\s*token,\s*[`']([^`']+)[`'](?:,\s*\{[^}]*?method:\s*'(\w+)')?", section, re.S)
    assert len(calls) == 7, calls
    served = {(m, r.path.removeprefix("/practice-demo")) for r in demo_router.router.routes for m in r.methods}
    rename = {"id": "reading_id", "setId": "set_id"}
    for path, method in calls:
        path = re.sub(r"\$\{(\w+)\}", lambda m: "{" + rename[m.group(1)] + "}", path)
        assert (method or "GET", path) in served, (method, path)
