"""Private additive SQLite ledger with append-only hash chain and OS fencing."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
import sqlite3

from boundary import Error, contract as c, enabled, safe_path, store_path


def now():
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, root):
        enabled()
        self.root = store_path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        path = safe_path(self.root / "ledger.sqlite", self.root)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS jobs (
            key TEXT PRIMARY KEY, scope TEXT NOT NULL, snapshot TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, payload TEXT NOT NULL,
            previous TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
          CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'append-only'); END;
          CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        """)
        os.chmod(path, 0o600)
        self.audit()

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @contextmanager
    def worker(self):
        """One OS lock per store, released on crash, not an expiring time-only lease."""
        path = safe_path(self.root / "worker.lock", self.root)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Error("Another development worker holds the store fence") from error
            yield
        finally:
            os.close(fd)

    def get(self, key):
        row = self.db.execute("SELECT snapshot FROM jobs WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def record(self, job, action):
        """Caller holds write transaction; snapshot and event commit together."""
        last = self.db.execute("SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, previous = (last[0]+1, last[1]) if last else (1, "0"*64)
        payload = dict(action=action, at=now(), job=job)
        text = c.canonical(payload).decode()
        checksum = c.digest(dict(seq=seq, previous=previous, payload=payload))
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                        (seq, job["key"], text, previous, checksum))
        self.db.execute("INSERT INTO jobs VALUES (?,?,?) ON CONFLICT(key) DO UPDATE "
                        "SET snapshot=excluded.snapshot",
                        (job["key"], job["scope"], c.canonical(job).decode()))

    def audit(self):
        # A consistent read snapshot prevents concurrent cancellation from
        # appearing to corrupt the event/checkpoint correspondence.
        with self.transaction():
            self._audit()

    def _audit(self):
        previous, latest = "0"*64, {}
        for seq, key, text, before, checksum in self.db.execute("SELECT * FROM events ORDER BY seq"):
            payload = json.loads(text)
            if (before != previous or checksum != c.digest(
                    dict(seq=seq, previous=before, payload=payload)) or payload["job"]["key"] != key):
                raise Error("Ledger hash chain is corrupt")
            previous, latest[key] = checksum, c.canonical(payload["job"]).decode()
        snapshots = dict(self.db.execute("SELECT key,snapshot FROM jobs"))
        if snapshots != latest:
            raise Error("Ledger checkpoint does not match committed events")

    def mutate(self, key, epoch, action, **changes):
        with self.transaction():
            job = self.get(key)
            if not job or job["epoch"] != epoch or job["status"] != "running":
                raise Error("Worker fenced, canceled, or stale")
            job.update(changes)
            self.record(job, action)
            return job

    def cancel(self, key, reason):
        enabled()
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
            raise Error("Cancellation requires a nonempty bounded reason")
        with self.transaction():
            job = self.get(key)
            if not job or job["status"] not in ("queued", "running", "failed", "blocked"):
                raise Error("Job cannot be canceled")
            job.update(status="canceled", cancellation=dict(at=now(), reason=reason),
                       finished_at=now(), epoch=job["epoch"]+1, outputs={})
            self.record(job, "cancel")
