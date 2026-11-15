"""SQLite state with an append-only event log and verified snapshot lineage.

Every transition is one SQLite transaction. The state of a cycle is rebuilt
only from a snapshot whose digest and lineage verify; a missing, corrupt,
expired or ambiguous snapshot is BLOCKED, never a silent fresh start.

Limit, stated plainly: snapshots travel as GitHub Actions artifacts, and
listing artifacts has no compare-and-swap. Two publishes very close together
can race. The sequence check at publish time plus the coordinator's
acknowledgement/retry DETECT that; nothing here prevents it.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

DB_NAME = "state.sqlite"
META_NAME = "snapshot.json"

SCHEMA = """
create table if not exists meta (key text primary key, value text not null);
create table if not exists events (
  seq integer primary key autoincrement,
  event_id text not null unique,
  kind text not null,
  payload text not null,
  accepted integer not null,
  reason text,
  at real not null
);
create table if not exists lineage (state_sequence integer primary key, snapshot_digest text not null);
create trigger if not exists events_append_only_u before update on events
  begin select raise(abort, 'events are append-only'); end;
create trigger if not exists events_append_only_d before delete on events
  begin select raise(abort, 'events are append-only'); end;
"""


class SnapshotError(RuntimeError):
    """Any reason the state cannot be trusted. The controller maps it to BLOCKED."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Store:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / DB_NAME
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # meta ------------------------------------------------------------------
    def get(self, key, default=None):
        row = self.conn.execute("select value from meta where key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _set(self, key, value):
        self.conn.execute("insert into meta(key,value) values(?,?) on conflict(key) do update set value=excluded.value",
                          (key, json.dumps(value, sort_keys=True)))

    # events ----------------------------------------------------------------
    def seen(self, event_id: str):
        row = self.conn.execute("select accepted, reason from events where event_id=?", (event_id,)).fetchone()
        return None if row is None else {"accepted": bool(row[0]), "reason": row[1]}

    def transact(self, event_id: str, kind: str, payload: dict, at: float, apply):
        """Run `apply(state) -> (state, accepted, reason)` and record the event,
        all in one transaction. A duplicate event_id is a no-op that returns the
        original outcome."""
        prior = self.seen(event_id)
        if prior is not None:
            return {**prior, "duplicate": True}
        self.conn.execute("begin immediate")
        try:
            state = self.get("state")
            new_state, accepted, reason = apply(state)
            self._set("state", new_state)
            self.conn.execute("insert into events(event_id,kind,payload,accepted,reason,at) values(?,?,?,?,?,?)",
                              (event_id, kind, json.dumps(payload, sort_keys=True), int(accepted), reason, at))
            self.conn.execute("commit")
        except BaseException:
            self.conn.execute("rollback")
            raise
        return {"accepted": accepted, "reason": reason, "duplicate": False}

    def events(self) -> list[dict]:
        cur = self.conn.execute("select seq,event_id,kind,accepted,reason from events order by seq")
        return [dict(zip(("seq", "event_id", "kind", "accepted", "reason"), r)) for r in cur]

    def last_event_id(self):
        row = self.conn.execute("select event_id from events order by seq desc limit 1").fetchone()
        return row[0] if row else None

    # snapshots -------------------------------------------------------------
    def export(self, out_dir: Path, *, cycle_id, controller_revision, run_id, run_attempt) -> dict:
        """Write state.sqlite + snapshot.json for the NEXT sequence."""
        previous = self.get("snapshot")
        seq = 0 if previous is None else previous["state_sequence"] + 1
        if previous is not None:
            self.conn.execute("insert or replace into lineage values(?,?)",
                              (previous["state_sequence"], previous["snapshot_digest"]))
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / DB_NAME
        if dst.exists():
            dst.unlink()
        self.conn.execute("vacuum into ?", (str(dst),))
        meta = {
            "cycle_id": cycle_id, "state_sequence": seq,
            "previous_snapshot_digest": previous["snapshot_digest"] if previous else None,
            "snapshot_digest": digest(dst), "controller_revision": controller_revision,
            "producing_run_id": str(run_id), "producing_run_attempt": str(run_attempt),
            "last_accepted_event_id": self.last_event_id(),
        }
        (out_dir / META_NAME).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        self._set("snapshot", {"state_sequence": seq, "snapshot_digest": meta["snapshot_digest"]})
        return meta


def load(snapshot_dir: Path, work_dir: Path, *, cycle_id: str) -> Store:
    """Open a snapshot for further transitions, verifying it first."""
    snapshot_dir, work_dir = Path(snapshot_dir), Path(work_dir)
    meta_p, db_p = snapshot_dir / META_NAME, snapshot_dir / DB_NAME
    if not meta_p.exists() or not db_p.exists():
        raise SnapshotError("snapshot_missing")
    try:
        meta = json.loads(meta_p.read_text())
    except ValueError as exc:
        raise SnapshotError("snapshot_meta_corrupt") from exc
    if meta.get("cycle_id") != cycle_id:
        raise SnapshotError("snapshot_for_another_cycle")
    if digest(db_p) != meta.get("snapshot_digest"):
        raise SnapshotError("snapshot_digest_mismatch")
    work_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(db_p, work_dir / DB_NAME)
    try:
        store = Store(work_dir)
        state = store.get("state")
    except sqlite3.DatabaseError as exc:
        raise SnapshotError("snapshot_db_corrupt") from exc
    if state is None or state.get("cycle_id") != cycle_id:
        raise SnapshotError("snapshot_state_missing")
    seq = meta["state_sequence"]
    if seq > 0:
        row = store.conn.execute("select snapshot_digest from lineage where state_sequence=?", (seq - 1,)).fetchone()
        if row is None or row[0] != meta.get("previous_snapshot_digest"):
            raise SnapshotError("snapshot_lineage_broken")
    if meta.get("last_accepted_event_id") != store.last_event_id():
        raise SnapshotError("snapshot_event_mismatch")
    store._set("snapshot", {"state_sequence": seq, "snapshot_digest": meta["snapshot_digest"]})
    return store


def choose_latest(candidates: list[dict], *, cycle_id: str) -> dict:
    """Pick the snapshot artifact to load from a listing.

    Each candidate: {name, state_sequence, expired, workflow_path, head_branch,
    from_record_job}. Only snapshots the trusted workflow's `record` job
    uploaded on main count. Ambiguity, absence
    and expiry are all refusals."""
    trusted = [c for c in candidates
               if c.get("workflow_path") == ".github/workflows/release-repair.yml"
               and c.get("head_branch") == "main"
               and c.get("from_record_job")
               and c.get("name", "").startswith(f"release-repair-state-{cycle_id}-")]
    if not trusted:
        raise SnapshotError("snapshot_missing")
    top = max(c["state_sequence"] for c in trusted)
    best = [c for c in trusted if c["state_sequence"] == top]
    if len(best) != 1:
        raise SnapshotError("snapshot_ambiguous")
    if best[0].get("expired"):
        raise SnapshotError("snapshot_expired")
    return best[0]
