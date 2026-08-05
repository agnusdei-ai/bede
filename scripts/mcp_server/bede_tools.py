"""The tool layer of Bede's MCP server — what the tools ARE, with no MCP
dependency of its own.

Split from server.py deliberately. Everything that decides what a parent can
ask for, what gets sent, and what is refused lives here and is unit-tested
with nothing but httpx; server.py is a thin transport shim over it that
imports the `mcp` SDK. That keeps `mcp` out of homeschool-api's own
requirements (and so out of its pip-audit gate), and it means the part worth
reviewing is the part that is actually covered by tests.

## What this exposes, and what it refuses to

Every tool here is READ-ONLY, and that is a structural property rather than a
convention: `_get()` is the only request helper in this module and it issues
GET requests exclusively. `test_bede_tools.py` asserts that no tool can reach
a mutating verb. A parent asking their own assistant "how is Ada doing in
math" should never be one hallucinated tool call away from deleting Ada's
record.

Three things are deliberately NOT exposed, each for a reason already settled
elsewhere in this codebase:

* **Nothing child-facing.** These are the `require_parent` endpoints only. A
  child who can see they are behind a sibling has been ranked whatever the UI
  calls it (see services/diagnostic/activity.py), and that reasoning does not
  stop being true because the reader is an LLM.
* **No per-student totals, and no ranking, from the pod roster.** The API
  already refuses to emit one — `pod_activity()` sorts students by NAME so the
  order cannot shift when the amounts do, and omits a student from a skill
  they have not worked rather than listing them at zero. A consuming model
  can reintroduce a ranking the data does not contain just by summing, so
  `get_pod_work_roster`'s description says so in the words the model reads.
* **Nothing about a child's spiritual life.** There is no such metric to
  expose, by constitutional design (CLAUDE.md: "Never measure, score, or
  quantify a child's spiritual engagement or growth"). This note is here so
  that a future contributor adding tools finds the rule at the point of
  temptation rather than in a document they were not reading.

## Authentication

A parent password from the environment, exchanged for a JWT at
`POST /auth/login`. Bede fingerprints every JWT against the issuing IP and
User-Agent (core/security.py), so this module pins a fixed User-Agent and
relies on the server process staying at one address — which it does, because
it runs on the parent's own machine.

If the deployment has parent MFA enrolled, login returns `mfa_required` and
there is no non-interactive way to finish the ceremony. That is reported as a
clear, actionable error rather than a hang or a confusing 401 — see
`BedeAuthError`.
"""

from __future__ import annotations

import os
import socket
import uuid
from typing import Any, Dict, List, Optional

import httpx

# Bede binds every JWT to the User-Agent it was issued to, so this has to be
# both fixed and sent on the login request as well as on every call after it.
USER_AGENT = "bede-mcp-server/1.0"

# Namespace for deriving this install's device_id. Any fixed UUID works; this
# one is arbitrary and never changes.
_DEVICE_NAMESPACE = uuid.UUID("6f9b1f1e-1f9a-4f1e-9c3a-1b0d5a7c2e41")


def device_id(env: Optional[Dict[str, str]] = None) -> str:
    """A stable device_id for this MCP install, so a parent can SEE and
    REVOKE it from Bede's device settings.

    Sending one is optional at the API (`LoginRequest.device_id`), and
    omitting it works — a token with no device_id claim is simply never
    treated as revoked. That is exactly why it must not be omitted here.
    This process holds a parent password and reads every child's progress;
    it is precisely the kind of access a parent should be able to cut off
    from the UI, and a component that silently sits outside the revocation
    mechanism is worse than one that never had access.

    Derived from the hostname rather than generated and persisted to a file:
    stable across restarts with nothing to write, and stable is the only
    property that matters here. `device_id` is client-asserted rather than
    cryptographically proven in Option C anyway (see core/device_registry.py),
    so unguessability buys nothing. BEDE_MCP_DEVICE_ID overrides it for a
    parent running this on two machines that report the same hostname.
    """
    env = env if env is not None else dict(os.environ)
    override = env.get("BEDE_MCP_DEVICE_ID", "").strip()
    if override:
        return override[:64]
    try:
        host = socket.gethostname() or "unknown-host"
    except Exception:  # pragma: no cover - gethostname failing is exotic
        host = "unknown-host"
    return str(uuid.uuid5(_DEVICE_NAMESPACE, f"bede-mcp:{host}"))

DEFAULT_TIMEOUT_SECONDS = 30.0

# Mirrors the subject areas services/diagnostic/ actually rolls up. Kept as a
# tuple here (rather than fetched) so a bad value is rejected before it
# becomes a request, and so the tool schema can enumerate them for the model.
SUBJECT_AREAS = (
    "mathematics",
    "composition",
    "phonics",
    "literacy",
    "language_exposure",
)


class BedeAuthError(RuntimeError):
    """Login failed in a way the parent needs to act on — wrong password, MFA
    enrolled (which cannot be completed non-interactively), or the API being
    unreachable. Separate from a per-call error so the message can say which
    of those it was."""


class BedeClient:
    """A thin, read-only, authenticated client for one Bede deployment."""

    def __init__(
        self,
        base_url: str,
        password: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._password = password
        self._device_id = device_id()
        self._token: Optional[str] = None
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT}
        )

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "BedeClient":
        """Build from BEDE_API_URL + BEDE_PARENT_PASSWORD.

        Raises BedeAuthError (not KeyError) for a missing value, because this
        is reached from the MCP host's own startup, where a stack trace about
        a dict lookup tells the parent nothing about what to fix.
        """
        env = env if env is not None else dict(os.environ)
        base_url = env.get("BEDE_API_URL", "").strip()
        password = env.get("BEDE_PARENT_PASSWORD", "").strip()
        if not base_url:
            raise BedeAuthError(
                "BEDE_API_URL is not set. Point it at your Bede API, "
                "e.g. https://bede.local/api or http://localhost:8000"
            )
        if not password:
            raise BedeAuthError(
                "BEDE_PARENT_PASSWORD is not set. Use the same parent password "
                "you use to log into Bede."
            )
        return cls(base_url=base_url, password=password)

    async def login(self) -> None:
        """Exchange the parent password for a JWT.

        Called lazily by `_get` on the first request, and again if a call ever
        comes back 401 — which happens legitimately when the parent changes
        their password (core/parent_credential.py bumps a credentials_version
        that invalidates every existing token immediately, by design).
        """
        try:
            response = await self._client.post(
                f"{self.base_url}/auth/login",
                # `credential`, not `password` — LoginRequest names one field
                # for all three roles (password for parent, PIN for child,
                # code for demo). Sending the wrong key is a 422, not a 401,
                # so it reads as a malformed request rather than a bad
                # secret; test_login_sends_the_field_names_the_api_requires
                # pins the real name.
                json={
                    "role": "parent",
                    "credential": self._password,
                    "device_id": self._device_id,
                },
            )
        except httpx.HTTPError as exc:
            raise BedeAuthError(f"Could not reach Bede at {self.base_url}: {exc}") from exc

        if response.status_code == 429:
            raise BedeAuthError(
                "Bede is rate-limiting login attempts. Wait about a minute and try again."
            )
        if response.status_code == 403:
            raise BedeAuthError(
                "Bede refused the login. If the parent account is locked out after "
                "repeated failures, wait for the lockout to expire (15 minutes) "
                "before retrying."
            )
        if response.status_code == 422:
            # A schema mismatch between this client and the deployment's API,
            # not a credential problem. Telling a parent to check a password
            # that is already correct sends them to change something they did
            # not need to touch.
            raise BedeAuthError(
                "Bede rejected the login request as malformed (422). This MCP "
                "server and your Bede version disagree about the login format — "
                f"check for an update. Details: {response.text[:200]}"
            )
        if response.status_code != 200:
            raise BedeAuthError(
                f"Login failed ({response.status_code}). Check BEDE_PARENT_PASSWORD."
            )

        payload = response.json()
        if payload.get("mfa_required"):
            raise BedeAuthError(
                "This Bede deployment has parent MFA enrolled (security key or "
                "authenticator app). MFA cannot be completed without a browser, so "
                "the MCP server cannot log in. Bede's progress data stays available "
                "in the parent web UI."
            )
        token = payload.get("access_token")
        if not token:
            raise BedeAuthError("Login succeeded but returned no token.")
        self._token = token

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """The ONLY request helper in this module, and it is GET-only.

        That is what makes "this server is read-only" a property of the code
        rather than a promise in a docstring — there is no code path here that
        can issue a POST, PATCH, or DELETE against a family's data.
        """
        if self._token is None:
            await self.login()

        response = await self._client.get(
            f"{self.base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        if response.status_code == 401:
            # Most likely the parent changed their password (which invalidates
            # every live token immediately) — re-login once, then give up
            # rather than looping.
            await self.login()
            response = await self._client.get(
                f"{self.base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── Tools ───────────────────────────────────────────────────────────
    #
    # Each returns already-shaped JSON from Bede's own parent endpoints. None
    # of them reshapes, ranks, aggregates across students, or derives a score
    # the API did not already emit.

    async def list_students(self) -> List[Dict[str, Any]]:
        """Who is in this pod, and what each is set up to study."""
        configs = await self._get("/pod/configs")
        return [
            {
                "student_name": c.get("student_name"),
                "grade": c.get("grade"),
                "subjects": c.get("subjects", []),
                "companion_mode": c.get("companion_mode"),
            }
            for c in configs
        ]

    async def get_mastery_summary(
        self, student_name: str, subject_area: str = "mathematics"
    ) -> Dict[str, Any]:
        if subject_area not in SUBJECT_AREAS:
            raise ValueError(
                f"Unknown subject_area {subject_area!r}. "
                f"Expected one of: {', '.join(SUBJECT_AREAS)}"
            )
        return await self._get(
            f"/diagnostic/{student_name}/summary",
            params={"subject_area": subject_area},
        )

    async def get_work_ledger(self, student_name: str) -> Dict[str, Any]:
        """What this student has actually DONE — completed activities and how
        much help each took. Distinct from mastery, which is a claim about the
        child; this is a record of events."""
        return await self._get(f"/diagnostic/{student_name}/activity")

    async def get_pod_work_roster(self) -> Dict[str, Any]:
        """Which students have worked which skills, grouped BY SKILL."""
        return await self._get("/diagnostic/pod/activity")

    async def get_narration_assessments(self, student_name: str) -> Any:
        return await self._get(f"/narration/{student_name}/assessments")

    async def get_learner_profile(self, student_name: str) -> Any:
        return await self._get(f"/narration/{student_name}/profile")


# ── Tool schemas ────────────────────────────────────────────────────────
#
# The `description` strings are not documentation for humans — they are the
# only instruction the consuming model gets. Where this codebase makes a
# refusal (the pod roster is not a ranking; a blank is not a low score), the
# refusal has to be stated HERE, in the text the model reads, or it holds only
# on Bede's own screens and evaporates the moment the data is read by
# something else.

_STUDENT_ARG = {
    "student_name": {
        "type": "string",
        "description": "Exactly as it appears in list_students.",
    }
}

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "list_students",
        "description": (
            "List the students in this Bede pod, with each one's grade, the subjects "
            "they are set up to study, and their companion mode. Start here — every "
            "other tool needs a student name from this list."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_mastery_summary",
        "description": (
            "Bede's current estimate of what one student has mastered in one subject "
            "area, with the skills that look like gaps and the ones that are learnable "
            "next.\n\n"
            "Read `calibration` first. When it is true, Bede is still getting to know "
            "this child and the numbers are provisional — say so rather than reporting "
            "them as findings. These are probability estimates from opportunistic "
            "evidence during tutoring, not test scores, and they are never a judgment "
            "of the child."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_STUDENT_ARG,
                "subject_area": {
                    "type": "string",
                    "enum": list(SUBJECT_AREAS),
                    "description": "Defaults to mathematics.",
                },
            },
            "required": ["student_name"],
        },
    },
    {
        "name": "get_work_ledger",
        "description": (
            "What this student has actually completed — activities done, how much help "
            "each took, and what Bede noticed about the work.\n\n"
            "This is a record of events, not a claim about the child, and it is "
            "deliberately reported as counts and dates with no average, level, or "
            "percentage. Do not compute one: a mean over these ordinal scales would "
            "invent precision the scales do not carry and read as a grade.\n\n"
            "Work Bede did not score is reported as not-scored. That is a blank, not a "
            "low mark, and the two must stay distinguishable in anything you write."
        ),
        "inputSchema": {
            "type": "object",
            "properties": dict(_STUDENT_ARG),
            "required": ["student_name"],
        },
    },
    {
        "name": "get_pod_work_roster",
        "description": (
            "Which students have worked which skills, grouped BY SKILL, with students "
            "listed alphabetically inside each one.\n\n"
            "This is deliberately not a ranking and must not be turned into one. Do not "
            "total a student's work across skills, do not order students by how much "
            "they have done, and do not describe any child as ahead of or behind "
            "another. A student who has not worked a skill is simply absent from it — "
            "that is not a zero. The question this answers is 'who has done this work', "
            "which is how one member of a pod comes to help another; 'who is better at "
            "this' is not built and should not be inferred."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_narration_assessments",
        "description": (
            "This student's narration assessment history — Bede's rubric scores for "
            "the times they told back what they had learned in their own words. "
            "Charlotte Mason narration, so the thing being assessed is the telling, "
            "not the child."
        ),
        "inputSchema": {
            "type": "object",
            "properties": dict(_STUDENT_ARG),
            "required": ["student_name"],
        },
    },
    {
        "name": "get_learner_profile",
        "description": (
            "The synthesized learner profile Bede uses to adapt its own tutoring — "
            "including a processing_style label.\n\n"
            "That label is a nudge to Bede's tool choice, not a psychometric claim "
            "that any learning style improves learning. Report it as what Bede is "
            "doing differently, never as a fact about how this child learns."
        ),
        "inputSchema": {
            "type": "object",
            "properties": dict(_STUDENT_ARG),
            "required": ["student_name"],
        },
    },
]


async def dispatch(client: BedeClient, name: str, arguments: Dict[str, Any]) -> Any:
    """Route one MCP tool call to its BedeClient method.

    An unknown name raises ValueError rather than falling through to a
    default, so a hallucinated tool name can never silently resolve to some
    other tool's data.
    """
    if name == "list_students":
        return await client.list_students()
    if name == "get_mastery_summary":
        return await client.get_mastery_summary(
            arguments["student_name"],
            arguments.get("subject_area", "mathematics"),
        )
    if name == "get_work_ledger":
        return await client.get_work_ledger(arguments["student_name"])
    if name == "get_pod_work_roster":
        return await client.get_pod_work_roster()
    if name == "get_narration_assessments":
        return await client.get_narration_assessments(arguments["student_name"])
    if name == "get_learner_profile":
        return await client.get_learner_profile(arguments["student_name"])
    raise ValueError(f"Unknown tool: {name}")
