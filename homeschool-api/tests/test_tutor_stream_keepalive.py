"""The tutor stream sends a keep-alive at least every 15 seconds.

Both clients (homeschool-tutor/src/services/api.ts, demo/src/api.ts) treat
TUTOR_SILENCE_MS (35s) of total silence on /tutor/chat as a lost connection
and ask again. That is only safe while the server keeps the line busy with
keep-alives as long as it is working, so a turn that is merely slow is never
mistaken for a dead one. If either of these breaks, the clients must change
with it.
"""
import re
from pathlib import Path

from sse_starlette.sse import EventSourceResponse

ROOT = Path(__file__).resolve().parents[2]
TUTOR = ROOT / "homeschool-api" / "routers" / "tutor.py"
CLIENTS = [ROOT / "homeschool-tutor" / "src" / "services" / "api.ts", ROOT / "demo" / "src" / "api.ts"]


def test_the_library_pings_at_least_every_fifteen_seconds():
    assert EventSourceResponse.DEFAULT_PING_INTERVAL <= 15


def test_the_tutor_stream_keeps_the_default_ping():
    returns = re.findall(r"return EventSourceResponse\((.*)\)", TUTOR.read_text())
    assert returns, "tutor.py no longer returns an EventSourceResponse"
    for args in returns:
        assert "ping" not in args, "a custom ping on /tutor/chat must stay under the clients' silence window"


def test_the_clients_wait_for_at_least_two_missed_keepalives():
    for path in CLIENTS:
        match = re.search(r"const TUTOR_SILENCE_MS = ([\d_]+)", path.read_text())
        assert match, path
        assert int(match.group(1).replace("_", "")) >= 2 * EventSourceResponse.DEFAULT_PING_INTERVAL * 1000 + 5_000, path
