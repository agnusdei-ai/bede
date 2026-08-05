"""End-to-end check for Bede's MCP server: real protocol, real schemas.

    python scripts/mcp_server/e2e_check.py

Speaks actual MCP stdio to server.py (initialize / tools/list / tools/call)
against a stub Bede API, and exits non-zero on the first failure.

## Why this exists as well as the unit tests

Two defects got past a green unit suite, and each names a gap this file
closes:

1. **The transport never started.** server.py was written against the MCP
   SDK's 1.x decorator API while the installed SDK was 2.0. All 18
   bede_tools tests passed; the server raised AttributeError at import.
   A unit test of the tool layer structurally cannot see that.
2. **The login body used the wrong field name.** bede_tools sent
   `password`; models.schemas.LoginRequest requires `credential`. The real
   API would have 422'd on the very first call. The unit tests stubbed the
   transport, and the original version of THIS file accepted any JSON body
   — so a permissive fake let the same mistake through twice.

The fix for (2) is the rule this file now follows: **the stub validates
every request with the API's own pydantic models**, imported from
homeschool-api rather than reimplemented. A fake that is more permissive
than the real thing is not a test, it is a second place for the bug to
hide.

Not run in CI: it imports from homeschool-api, which lives outside this
directory's dependency set. Run it by hand when changing the wire contract
between this server and Bede.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent.parent.parent / "homeschool-api"
sys.path.insert(0, str(_API_ROOT))

try:
    # The real request model the deployed API validates against. Imported,
    # never reimplemented — see this module's docstring.
    from models.schemas import LoginRequest
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        f"Could not import Bede's schemas from {_API_ROOT}: {exc}\n"
        "Run this from a checkout with homeschool-api present, and with "
        "pydantic installed.\n"
    )
    raise SystemExit(1)

PORT = 8791
FAILURES: list[str] = []

POD = [
    {
        "student_name": "Ada",
        "grade": "4",
        "subjects": ["mathematics"],
        "companion_mode": "full_plan",
        # Fields a roster has no business forwarding — asserted below.
        "faith_tradition": "Baptist",
        "lesson_resume": [{"subject": "mathematics", "stopped_at": "long division"}],
    }
]
SUMMARY = {
    "student_name": "Ada",
    "subject_area": "mathematics",
    "evidence_count": 7,
    "calibration": False,
    "domains": [],
    "gaps": [],
    "next_steps": [],
    "updated_at": "2026-08-05",
}


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "ok  " if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def parse(result, label: str):
    """Decode a tool result, reporting the raw text if it isn't JSON.

    A failing tool returns a human-readable error string rather than JSON
    (server.py deliberately hands errors back as content so the assistant can
    relay the remedy). Without this, the first real failure surfaced as a
    JSONDecodeError traceback that buried the actual message — which is what
    happened when this check was verified against the reintroduced login-field
    bug.
    """
    text = result.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        check(label, False, text.strip().splitlines()[0][:160])
        return None


class StubBede(BaseHTTPRequestHandler):
    """A stub that is STRICTER than a mock, on purpose: it validates the
    login body with the API's own model and rejects anything the real
    deployment would reject."""

    def log_message(self, *args):  # keep stdout clean; it is not the transport here
        pass

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/auth/login":
            self._send({"detail": "not found"}, 404)
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            parsed = LoginRequest.model_validate_json(raw)
        except Exception as exc:
            # Exactly what the real API does with a malformed body.
            self._send({"detail": str(exc)}, 422)
            return
        check(
            "login sends a device_id (so a parent can revoke this)",
            bool(parsed.device_id),
        )
        check("login role is parent", parsed.role == "parent")
        self._send({"access_token": "tok", "role": "parent"})

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer tok":
            self._send({"detail": "unauthorized"}, 401)
            return
        if self.path == "/pod/configs":
            self._send(POD)
        elif self.path.startswith("/diagnostic/Ada/summary"):
            self._send(SUMMARY)
        else:
            self._send({"path": self.path})


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_py = Path(__file__).resolve().parent / "server.py"
    httpd = HTTPServer(("127.0.0.1", PORT), StubBede)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_py)],
        env={
            "BEDE_API_URL": f"http://127.0.0.1:{PORT}",
            "BEDE_PARENT_PASSWORD": "hunter2",
            "PATH": "/usr/bin:/bin",
        },
    )

    print("MCP end-to-end check")
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                check("initialize", init.server_info.name == "bede")

                tools = {t.name: t for t in (await session.list_tools()).tools}
                check(
                    "all six tools are advertised",
                    set(tools) == {
                        "list_students",
                        "get_mastery_summary",
                        "get_work_ledger",
                        "get_pod_work_roster",
                        "get_narration_assessments",
                        "get_learner_profile",
                    },
                    str(sorted(tools)),
                )
                check(
                    "every tool is annotated read-only in the protocol",
                    all(
                        t.annotations and t.annotations.read_only_hint
                        for t in tools.values()
                    ),
                )

                result = await session.call_tool("list_students", {})
                students = parse(result, "list_students returns the roster")
                if students is not None:
                    check("list_students returns the roster", students[0]["student_name"] == "Ada")
                    check(
                        "roster drops non-roster config fields",
                        "faith_tradition" not in students[0]
                        and "lesson_resume" not in students[0],
                        str(students[0]),
                    )

                result = await session.call_tool(
                    "get_mastery_summary",
                    {"student_name": "Ada", "subject_area": "mathematics"},
                )
                summary = parse(result, "get_mastery_summary returns the summary")
                if summary is not None:
                    check("get_mastery_summary returns the summary", summary["evidence_count"] == 7)

                result = await session.call_tool(
                    "get_mastery_summary",
                    {"student_name": "Ada", "subject_area": "astrology"},
                )
                check(
                    "an invalid subject_area is rejected before any request",
                    result.is_error and "literal_error" in result.content[0].text,
                    result.content[0].text[:120],
                )
    finally:
        httpd.shutdown()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED: {', '.join(FAILURES)}")
        return 1
    print("ALL MCP END-TO-END CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
