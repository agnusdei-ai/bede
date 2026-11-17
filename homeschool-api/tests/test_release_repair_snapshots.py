"""Snapshot lineage and event delivery for the release-repair state store.

A missing, corrupt, expired or ambiguous snapshot is BLOCKED, never a silent
new cycle. Duplicate, refused and interrupted submissions are safe, and the
coordinator can tell which submissions were acknowledged.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys

import pytest

from release_repair_helpers import A, REPO, WEBKIT, Cycle, fail_row
from release_repair import controller, state_store

CLI = [sys.executable, str(REPO / "scripts" / "release_repair" / "controller.py")]
TEST_ACC = str(REPO / "config" / "acceptance" / "test-only.json")


def export(c: Cycle, out, run="r1"):
    return c.store.export(out, cycle_id="c1", controller_revision="rev", run_id=run, run_attempt="1")


def test_a_snapshot_round_trips_and_carries_its_lineage(tmp_path):
    c = Cycle(tmp_path)
    m0 = export(c, tmp_path / "s0")
    s1 = state_store.load(tmp_path / "s0", tmp_path / "w1", cycle_id="c1")
    controller.apply(s1, {"kind": "results", "event_id": "x", "sha": A, "results": [fail_row("u/v")]}, c.pol, c.acc)
    m1 = s1.export(tmp_path / "s1", cycle_id="c1", controller_revision="rev", run_id="r2", run_attempt="1")
    assert (m0["state_sequence"], m1["state_sequence"]) == (0, 1)
    assert m1["previous_snapshot_digest"] == m0["snapshot_digest"]
    assert m1["last_accepted_event_id"] == "x"
    loaded = state_store.load(tmp_path / "s1", tmp_path / "w2", cycle_id="c1")
    assert loaded.get("state")["failures"]["browser_journeys:u/v"]["occurrences"] == 1


@pytest.mark.parametrize("damage", ["missing_db", "missing_meta", "flip_byte", "other_cycle", "lineage", "event"])
def test_an_untrustworthy_snapshot_is_refused(tmp_path, damage):
    c = Cycle(tmp_path)
    export(c, tmp_path / "s0")
    s1 = state_store.load(tmp_path / "s0", tmp_path / "w1", cycle_id="c1")
    s1.export(tmp_path / "s1", cycle_id="c1", controller_revision="rev", run_id="r2", run_attempt="1")
    d = tmp_path / "s1"
    meta = json.loads((d / "snapshot.json").read_text())
    if damage == "missing_db":
        (d / "state.sqlite").unlink()
    elif damage == "missing_meta":
        (d / "snapshot.json").unlink()
    elif damage == "flip_byte":
        b = bytearray((d / "state.sqlite").read_bytes()); b[200] ^= 0xFF; (d / "state.sqlite").write_bytes(bytes(b))
    elif damage == "other_cycle":
        meta["cycle_id"] = "c2"
    elif damage == "lineage":
        meta["previous_snapshot_digest"] = "0" * 64
    elif damage == "event":
        meta["last_accepted_event_id"] = "not-the-last"
    if (d / "snapshot.json").exists() and damage not in ("missing_meta",):
        (d / "snapshot.json").write_text(json.dumps(meta))
    with pytest.raises(state_store.SnapshotError):
        state_store.load(d, tmp_path / "w2", cycle_id="c2" if damage == "other_cycle" else "c1")


def _art(seq, **over):
    return {"name": f"release-repair-state-c1-{seq}", "state_sequence": seq, "expired": False,
            "workflow_path": ".github/workflows/release-repair.yml", "head_branch": "main",
            "from_record_job": True, **over}


@pytest.mark.parametrize("listing,reason", [
    ([], "snapshot_missing"),
    ([_art(0), _art(1), _art(1)], "snapshot_ambiguous"),
    ([_art(0), _art(1, expired=True)], "snapshot_expired"),
    ([_art(0, head_branch="release-repair/c1/t")], "snapshot_missing"),
    ([_art(0, workflow_path=".github/workflows/other.yml")], "snapshot_missing"),
    ([_art(0, from_record_job=False)], "snapshot_missing"),
])
def test_choosing_a_snapshot_refuses_missing_ambiguous_expired_and_untrusted(listing, reason):
    with pytest.raises(state_store.SnapshotError, match=reason):
        state_store.choose_latest(listing, cycle_id="c1")


def test_a_candidate_forged_snapshot_is_dated_before_record_and_refused():
    from release_repair import artifacts
    assert artifacts.from_record_job("2026-11-15T16:20:00Z", "2026-11-15T16:19:00Z")
    assert not artifacts.from_record_job("2026-11-15T16:18:59Z", "2026-11-15T16:19:00Z")
    assert not artifacts.from_record_job("2026-11-15T16:20:00Z", None)


def test_the_highest_trusted_sequence_wins():
    assert state_store.choose_latest([_art(0), _art(2), _art(1)], cycle_id="c1")["state_sequence"] == 2


def test_events_are_append_only(tmp_path):
    c = Cycle(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        c.store.conn.execute("update events set accepted=0")
    with pytest.raises(sqlite3.IntegrityError):
        c.store.conn.execute("delete from events")


def test_an_interrupted_transition_rolls_back_entirely(tmp_path, monkeypatch):
    c = Cycle(tmp_path)
    before = (c.s, c.store.events())

    def boom(*a, **k):
        raise RuntimeError("runner lost mid-transition")
    monkeypatch.setitem(controller.HANDLERS, "results", boom)
    with pytest.raises(RuntimeError):
        c.ev("results", sha=A, results=[fail_row("x/y")], event_id="lost")
    assert (c.s, c.store.events()) == before
    assert c.store.seen("lost") is None          # never acked, so the coordinator resubmits it


def test_reconcile_names_the_unacknowledged_submissions(tmp_path):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[fail_row("x/y")], event_id="got-it")
    r = controller.reconcile(c.store, ["got-it", "replaced-pending-run"])
    assert r == {"acknowledged": ["got-it"], "unacknowledged": ["replaced-pending-run"]}


def test_the_cli_refuses_to_record_without_a_snapshot(tmp_path):
    out = subprocess.run(CLI + ["--action", "record", "--cycle", "c1", "--work", str(tmp_path / "w"),
                                "--snapshot-in", str(tmp_path / "none"), "--acceptance", TEST_ACC],
                         capture_output=True, text=True)
    assert out.returncode == 2 and json.loads(out.stdout)["reason"] == "snapshot_missing"


def test_the_cli_start_then_record_resubmission_is_idempotent(tmp_path):
    start = tmp_path / "start.json"; start.write_text(json.dumps({"candidate_sha": A}))
    subprocess.run(CLI + ["--action", "start", "--cycle", "c1", "--work", str(tmp_path / "w0"), "--event", str(start),
                          "--snapshot-out", str(tmp_path / "s0"), "--acceptance", TEST_ACC], check=True, capture_output=True)
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps([{"kind": "results", "event_id": "r-1", "sha": A, "results": [fail_row("x/y")]}]))
    for i, (src, dst) in enumerate((("s0", "s1"), ("s1", "s2"))):
        out = subprocess.run(CLI + ["--action", "record", "--cycle", "c1", "--work", str(tmp_path / f"w{i+1}"),
                                    "--snapshot-in", str(tmp_path / src), "--snapshot-out", str(tmp_path / dst),
                                    "--event", str(ev), "--acceptance", TEST_ACC], check=True, capture_output=True, text=True)
        ack = json.loads(out.stdout)["ack"][0]
        assert ack["event_id"] == "r-1" and ack["duplicate"] is (i == 1)
    state = state_store.load(tmp_path / "s2", tmp_path / "w9", cycle_id="c1").get("state")
    assert state["failures"]["browser_journeys:x/y"]["occurrences"] == 1


def _artifacts_main(monkeypatch, capsys, listing, argv):
    from release_repair import artifacts
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r"); monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(artifacts, "listing", lambda repo, token, cycle: listing)
    monkeypatch.setattr(sys, "argv", ["artifacts.py", *argv])
    code = artifacts.main()
    return code, json.loads(capsys.readouterr().out)


def test_no_snapshot_answers_snapshot_missing_which_is_the_only_answer_start_accepts(monkeypatch, capsys):
    code, out = _artifacts_main(monkeypatch, capsys, [], ["latest", "--cycle", "c1", "--out", "x"])
    assert code == 2 and out["reason"] == "snapshot_missing"
    assert 'grep -q \'"snapshot_missing"\'' in (REPO / "scripts/release_repair/record.sh").read_text()


def test_a_newer_snapshot_published_meanwhile_refuses_this_publish(monkeypatch, capsys):
    code, out = _artifacts_main(monkeypatch, capsys, [_art(0), _art(1)],
                                ["check-unchanged", "--cycle", "c1", "--loaded-sequence", "0"])
    assert code == 3 and out["status"] == "INFRA_ERROR"
    code, out = _artifacts_main(monkeypatch, capsys, [_art(0), _art(1)],
                                ["check-unchanged", "--cycle", "c1", "--loaded-sequence", "1"])
    assert code == 0


def test_downloads_follow_the_storage_redirect_without_sending_the_token():
    """GitHub answers an artifact download with 302 to blob storage. The token
    must reach GitHub and never the storage host, which refuses it (401). Real
    sockets, real urllib redirect handling: the first live cycle failed here."""
    import http.server
    import threading
    from release_repair import artifacts

    seen = {}

    class Storage(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen["storage_auth"] = self.headers.get("Authorization")
            code, body = (401, b"no") if self.headers.get("Authorization") else (200, b"zip-bytes")
            self.send_response(code); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass

    storage = http.server.HTTPServer(("127.0.0.1", 0), Storage)

    class GitHub(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen["github_auth"] = self.headers.get("Authorization")
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{storage.server_port}/blob?sig=x")
            self.end_headers()

        def log_message(self, *a):
            pass

    github = http.server.HTTPServer(("127.0.0.1", 0), GitHub)
    for srv in (storage, github):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        body = artifacts._get(f"http://127.0.0.1:{github.server_port}/zip", "secret-token", raw=True)
    finally:
        storage.shutdown(); github.shutdown()
    assert body == b"zip-bytes"
    assert seen["github_auth"] == "Bearer secret-token"
    assert seen["storage_auth"] is None
