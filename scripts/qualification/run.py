#!/usr/bin/env python3
"""Start the real stack, seed through the real API, run the matrix.

Expects preflight.py --phase pre-start to have passed (it writes the route
table the matrix reads). Exit status:

  0  every cell PASS
  1  the run completed and at least one cell is not PASS (the normal state
     of a candidate whose routes are still being built)
  2  the harness itself could not complete (startup, seeding, browser)

Evidence is written to QUAL_OUT_DIR either way.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualconfig as cfg  # noqa: E402
import preflight  # noqa: E402
from harness import Api, Driver, HarnessError, Stack, load_route_table  # noqa: E402
from matrix import Matrix, write_reports  # noqa: E402
from seed import Seeder, write_transcript  # noqa: E402


def main() -> int:
    out = cfg.OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    stack = Stack(env=env, out=out)
    driver = api = None
    status = 2
    started = time.time()
    try:
        routes = load_route_table(out)
        stack.start_stub()
        stack.start_server()
        driver = Driver(cfg.API_ORIGIN, out)
        ua = driver.user_agent("admin")
        api = Api(stack.base, ua)
        seeder = Seeder(api, driver, env)
        try:
            seeder.run()
        finally:
            write_transcript(seeder.fx, out)
        post = preflight.run("post-seed", env, skip_import=True)
        (out / "preflight-post-seed.json").write_text(json.dumps(
            {"phase": "post-seed", "ok": post.ok, "checks": post.checks}, indent=2) + "\n")
        if not post.ok:
            raise HarnessError("post-seed preflight failed; see preflight-post-seed.json")
        cells = Matrix(api, driver, stack, seeder, routes).run()
        summary = write_reports(cells, out)
        print(json.dumps(summary["total"]), f"cells={summary['cells']}")
        status = 0 if summary["qualified"] else 1
    except Exception as exc:  # noqa: BLE001
        (out / "harness-error.txt").write_text("".join(traceback.format_exception(exc)))
        print(f"harness error: {exc}", file=sys.stderr)
        status = 2
    finally:
        if api:
            api.close()
        if driver:
            driver.close()
        stack.stop_all()
        (out / "stack-events.json").write_text(json.dumps(
            {"events": stack.events, "seconds": round(time.time() - started, 1)}, indent=2) + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
