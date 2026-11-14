"""Bounded local factory. CLI has no review, approval, model, or activation flag."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile
import time

from boundary import Error, ROOT, contract as c, enabled, safe_path, tools
from ledger import Ledger, now
from render import artifacts
from validation import validate_bundle

MAX_OUTPUT = 10 * 1024 * 1024


def bounded_read(path):
    with path.open("rb") as f:
        data = f.read(c.MAX_INPUT + 1)
    if len(data) > c.MAX_INPUT:
        raise Error("Input exceeds 1 MiB")
    return data


def collect(path):
    """Return parsed bundle plus actual local dependency hashes; never fetch URLs."""
    path = safe_path(path, ROOT)
    bundle = c.read_bundle(path)
    c.validate(bundle)
    records = [s["asset"] for s in bundle.get("sources", [])]
    records += [a for e in bundle.get("evidence", []) for a in e["artifacts"]]
    ledger = bundle.get("ledger", {})
    for key in ("inputs", "outputs", "artifacts"):
        records += ledger.get(key, [])
    if len(records) > 256:
        raise Error("Too many input files")
    dependencies = {}
    total = 0
    for record in records:
        local = safe_path(path.parent / record["path"], path.parent)
        data = bounded_read(local)
        total += len(data)
        if total > 8 * 1024 * 1024:
            raise Error("Aggregate input limit exceeded")
        dependencies[record["path"]] = hashlib.sha256(data).hexdigest()
    return bundle, dependencies


def verify_outputs(ledger, job):
    directory = safe_path(ledger.root / job["key"], ledger.root)
    if not directory.is_dir() or set(p.name for p in directory.iterdir()) != set(job["outputs"]):
        raise Error("Missing or extra output; reuse blocked")
    for name, record in job["outputs"].items():
        path = safe_path(directory / name, directory)
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]):
            raise Error("Output checksum mismatch; reuse blocked")


def binding(ledger, job, lesson):
    """Review target binds manifest, asset bytes, tool bytes, and exact lesson version."""
    enabled()
    current = ledger.get(job["key"])
    if not current or current["status"] != "succeeded":
        raise Error("Only a current committed draft can be submitted for human review")
    verify_outputs(ledger, current)
    bundle, inputs = collect(Path(current["manifest"]))
    expected = c.digest(dict(
        scope=current["scope"], manifest=hashlib.sha256(bounded_read(Path(current["manifest"]))).hexdigest(),
        inputs=inputs, tools=tools(),
    ))
    if expected != current["key"]:
        with ledger.transaction():
            current.update(status="stale", outputs=current["outputs"], finished_at=now())
            ledger.record(current, "invalidate_review_target")
        raise Error("Draft or tools changed; prior review binding is stale")
    validate_bundle(bundle, Path(current["manifest"]).parent)
    matches = [l for l in bundle["lessons"] if l["id"] == lesson]
    if len(matches) != 1:
        raise Error("Unknown lesson review target")
    return dict(factory_key=current["key"], content_hash=c.digest(c.export(bundle)),
                lesson=c.ref(matches[0])), bundle, matches[0]


def execute(ledger, manifest, task, *, hook=lambda phase, job: None):
    """One finite job. Hooks are trusted fault-injection tests, never manifest code."""
    enabled()
    manifest = safe_path(manifest, ROOT)
    scope = c.digest(dict(task=task, workspace=str(ROOT), manifest=str(manifest)))
    raw = None
    preflight = None
    try:
        raw = bounded_read(manifest)
        bundle, inputs = collect(manifest)
    except (Error, OSError, KeyError, TypeError, ValueError) as error:
        bundle, inputs, preflight = None, {}, error
    raw_hash = hashlib.sha256(raw).hexdigest() if raw is not None else None
    key = c.digest(dict(scope=scope, manifest=raw_hash,
                        inputs=inputs, tools=tools()))
    with ledger.worker():
        ledger.audit()
        with ledger.transaction():
            prior_rows = ledger.db.execute(
                "SELECT j.snapshot FROM jobs j JOIN events e ON e.key=j.key "
                "WHERE j.scope=? ORDER BY e.seq DESC", (scope,)).fetchall()
            prior = json.loads(prior_rows[0][0]) if prior_rows else None
            budgets = {}
            for (text,) in prior_rows:
                for cluster, count in json.loads(text)["repairs"].items():
                    budgets[cluster] = max(budgets.get(cluster, 0), count)
            for oldkey, text in ledger.db.execute("SELECT key,snapshot FROM jobs").fetchall():
                old = json.loads(text)
                changed = (old.get("manifest_sha256") != raw_hash
                           or old["inputs"] != inputs or old["tools"] != tools())
                if (old["manifest"] == str(manifest) and changed
                        and old["status"] in ("succeeded", "running")):
                    old.update(status="stale", finished_at=now())
                    ledger.record(old, "invalidate_inputs_tools_and_transitive_bundle")
            job = ledger.get(key)
            if job and job["status"] in ("canceled", "blocked", "stale"):
                raise Error(f'Job {job["status"]}; new explicit task identity required')
            if job and job["status"] == "succeeded":
                # Verification happens below so a denial can be durably committed.
                pass
            elif job:
                job["repairs"] = budgets
                if job["status"] == "running":
                    job.update(status="failed", failure_cluster="recovery",
                               finished_at=now())
                    ledger.record(job, "recover_crashed_worker")
                cluster = job["failure_cluster"]
                count = job["repairs"].get(cluster, 0)
                if count >= 3:
                    job.update(status="blocked", blocker="repair budget exhausted", finished_at=now())
                    ledger.record(job, "repair_exhausted")
                else:
                    job["repairs"][cluster] = count+1
                    job.update(status="queued", epoch=job["epoch"]+1)
                    ledger.record(job, "repair_requested")
            else:
                repair_cluster = None
                if prior and prior["status"] in ("failed", "running", "blocked"):
                    repair_cluster = prior["failure_cluster"] or "recovery"
                exhausted = repair_cluster and budgets.get(repair_cluster, 0) >= 3
                if repair_cluster and not exhausted:
                    budgets[repair_cluster] = budgets.get(repair_cluster, 0)+1
                job = dict(
                    key=key, scope=scope, task=task, manifest=str(manifest),
                    manifest_sha256=raw_hash,
                    workspace=str(ROOT), parent_ref=bundle["ledger"]["parent_ref"] if bundle else None,
                    dependencies=bundle["ledger"]["dependencies"] if bundle else [],
                    inputs=inputs, tools=tools(), status="blocked" if exhausted else "queued", epoch=1,
                    repairs=budgets, failure_cluster=repair_cluster, outputs={}, started_at=now(),
                    finished_at=now() if exhausted else None,
                    cancellation=None, usage=dict(tokens=None, cost=None, seconds=None,
                                                  measurement_source=None),
                    limits=dict(wall_seconds=30, memory_mib=256, concurrency=1,
                                input_bytes=c.MAX_INPUT, output_bytes=MAX_OUTPUT, paid_spend=0),
                    approvals="pending; never locally asserted", validations=[],
                )
                if exhausted:
                    job["blocker"] = "repair budget exhausted across content versions"
                ledger.record(job, "repair_exhausted" if exhausted else "queued")
        if job["status"] == "blocked":
            raise Error("Maximum three repairs per failure cluster exhausted")
        if job["status"] == "succeeded":
            try:
                verify_outputs(ledger, job)
            except (Error, OSError) as error:
                with ledger.transaction():
                    job.update(status="blocked", blocker=str(error), finished_at=now())
                    ledger.record(job, "output_integrity_failed")
                raise
            return job
        epoch = job["epoch"]
        with ledger.transaction():
            job = ledger.get(key)
            if job["status"] != "queued":
                raise Error("Not queued")
            job.update(status="running", finished_at=None)
            ledger.record(job, "attempt_started")
        phase, start = "preflight", time.monotonic()

        def checkpoint(name):
            nonlocal phase
            phase = name
            hook(name, job)
            current = ledger.get(key)
            if current["status"] != "running" or current["epoch"] != epoch:
                raise Error("Canceled or fenced")
            if time.monotonic() - start > 30:
                raise Error("30-second wall budget exceeded")
            ledger.mutate(key, epoch, name, phase=name)

        staging = None
        try:
            checkpoint("validation")
            if preflight:
                raise preflight
            validate_bundle(bundle, manifest.parent)
            checkpoint("render")
            files = artifacts(bundle, key, job["tools"])
            if sum(map(len, files.values())) > MAX_OUTPUT:
                raise Error("Output exceeds 10 MiB")
            checkpoint("write")
            staging = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=ledger.root))
            for name, data in sorted(files.items()):
                with safe_path(staging / name, ledger.root).open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            checkpoint("before_rename")
            target = safe_path(ledger.root / key, ledger.root)
            if target.exists():
                # A pre-commit orphan has no authority; preserve it for investigation.
                os.rename(target, ledger.root / f".orphan-{key}-{epoch}")
            _sync_directory(staging)
            os.rename(staging, target)
            staging = None
            _sync_directory(ledger.root)
            checkpoint("after_rename")
            # Re-read inputs/tools at commit, not just before rendering.
            newbundle, newinputs = collect(manifest)
            current_key = c.digest(dict(scope=scope,
                manifest=hashlib.sha256(bounded_read(manifest)).hexdigest(),
                inputs=newinputs, tools=tools()))
            if current_key != key:
                raise Error("Inputs or tools changed during build")
            output_records = {name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                              for name, data in files.items()}
            checkpoint("before_commit")
            job = ledger.mutate(
                key, epoch, "succeeded_review_stop", status="succeeded",
                outputs=output_records, finished_at=now(),
                usage=dict(tokens=None, cost=None, seconds=time.monotonic()-start,
                           measurement_source="time.monotonic; no inference"),
                validations=[dict(check="specification contract and output checksums", result="pass")])
            hook("after_commit", job)
            return job
        except Exception as error:
            current = ledger.get(key)
            if current["status"] == "running" and current["epoch"] == epoch:
                ledger.mutate(key, epoch, "failure", status="failed",
                              failure_cluster=phase, finished_at=now(),
                              failure=dict(type=type(error).__name__, detail=str(error)[:1024]),
                              validations=[dict(check=phase, result="fail")])
            raise
        finally:
            if staging is not None:
                shutil.rmtree(staging)


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def limits():
    """CLI enforces OS budgets after the wrapped interpreter starts."""
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    signal.alarm(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fixture", "build", "status", "cancel"))
    parser.add_argument("--store", type=Path,
                        default=ROOT / "generated-artifacts/curriculum-factory/local")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--task", default="sample-draft")
    parser.add_argument("--key")
    parser.add_argument("--reason")
    args = parser.parse_args()
    try:
        enabled()
        limits()
        if args.action == "fixture":
            from fixture import write_fixture
            destination = safe_path(args.store, ROOT / "generated-artifacts/curriculum-factory")
            write_fixture(destination / "input")
            print(destination / "input/bundle.json")
            return
        ledger = Ledger(args.store)
        try:
            if args.action == "build":
                if args.manifest is None:
                    raise Error("--manifest required")
                result = execute(ledger, args.manifest, args.task)
            elif args.action == "cancel":
                ledger.cancel(args.key, args.reason)
                result = ledger.get(args.key)
            else:
                result = ledger.get(args.key)
                if result is None:
                    raise Error("Unknown job")
            print(c.canonical(result).decode())
        finally:
            ledger.close()
    except (Error, OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f"BLOCKED: {error}\n")


if __name__ == "__main__":
    main()
