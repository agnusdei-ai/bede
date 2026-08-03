#!/usr/bin/env python3
"""
Mutation probe — does the suite actually notice when a control is defeated?

The evidence behind docs/ARCHITECTURE_PRINCIPLES.md P11 ("every control has
a test that fails when the control is absent"). For each control: neuter it,
run the suite, record whether anything failed, restore.

  python3 scripts/mutation_probe.py

Run this after adding a security control, and before any pentest engagement.
A green suite is not evidence that a control works; this is.

TWO KINDS OF MUTATION, and the difference is the entire point. Breaking a
control's own LOGIC tests whether it is exercised. Breaking its WIRING —
unmounting the middleware, reordering the stack, swapping an endpoint's
guard — tests whether it is composed correctly, which is the failure mode
P11 is named after and the one a unit test cannot see. The 2026-08-03 run
caught 16 of 16 logic mutations and 0 of 8 wiring mutations; the wiring half
is now covered by tests/test_app_composition.py. Add mutations of both kinds
when adding a control.

SAFETY. Each mutation is applied, tested, and reverted in a `finally`. Run it
on a clean tree so `git status` tells you unambiguously whether a crash left
anything behind — a SIGKILL mid-run has left a mutation applied before.
"""
import subprocess
import pathlib
import sys
import time

API = pathlib.Path("/workspace/bede/homeschool-api")

# (label, relative path, needle, replacement)
# Each replacement must keep the file syntactically valid and semantically
# defeat exactly one control.
MUTATIONS = [
    ("P9-ish: device fingerprint binding",
     "core/security.py",
     "    token_fp = payload.get(\"fp\")",
     "    return True  # MUTANT\n    token_fp = payload.get(\"fp\")"),

    ("Token expiry enforcement",
     "core/security.py",
     '        if "exp" in payload and payload["exp"] < datetime.now(timezone.utc).timestamp():\n            return None',
     '        if False:\n            return None  # MUTANT'),

    ("P10: role/domain agreement",
     "core/security.py",
     "            if identity.domain_for_role(payload.get(\"role\")) != domain:",
     "            if False:  # MUTANT"),

    ("P10: domain-scoped signing keys",
     "core/identity.py",
     "    if domain == DEMO and settings.demo_secret_key:\n        return _derive(settings.demo_secret_key, domain)\n    return _derive(settings.secret_key, domain)",
     "    return settings.secret_key.encode(\"utf-8\")  # MUTANT"),

    ("credentials_version (password change kills tokens)",
     "core/deps.py",
     '    if payload.get("role") in ("parent", "parent_pending") and "cv" in payload:',
     '    if False:  # MUTANT'),

    ("Policy deny-by-default on unknown action",
     "core/policy.py",
     "    if action not in _POLICY:\n        return Decision(",
     "    if action not in _POLICY:\n        return _ALLOW  # MUTANT\n        return Decision("),

    ("require_parent role gate",
     "core/deps.py",
     '    return await _authorize(request, payload, "admin.manage")',
     '    return await _authorize(request, payload, "session.self")  # MUTANT'),

    ("P8: elevation check",
     "core/deps.py",
     "    if not await elevation.is_elevated(db, payload.get(\"jti\")):",
     "    if False:  # MUTANT"),

    ("Demo session liveness",
     "core/deps.py",
     '    if payload.get("role") != "demo_code":\n        return payload',
     '    return payload  # MUTANT\n    if payload.get("role") != "demo_code":\n        return payload'),

    ("ExfiltrationGuard",
     "core/middleware.py",
     "    async def dispatch(self, request: Request, call_next: Callable) -> Response:\n        path = request.url.path.rstrip(\"/\").lower()",
     "    async def dispatch(self, request: Request, call_next: Callable) -> Response:\n        return await call_next(request)  # MUTANT\n        path = request.url.path.rstrip(\"/\").lower()"),

    ("Security headers",
     "core/middleware.py",
     "    async def dispatch(self, request: Request, call_next: Callable) -> Response:\n        response = await call_next(request)\n\n        h = response.headers",
     "    async def dispatch(self, request: Request, call_next: Callable) -> Response:\n        response = await call_next(request)\n        return response  # MUTANT\n        h = response.headers"),

    ("Rate limiting",
     "core/middleware.py",
     "    async def dispatch(self, request: Request, call_next: Callable) -> Response:\n        ip = request.client.host if request.client else \"0.0.0.0\"",
     "    async def dispatch(self, request: Request, call_next: Callable) -> Response:\n        return await call_next(request)  # MUTANT\n        ip = request.client.host if request.client else \"0.0.0.0\""),

    ("License gate",
     "core/middleware.py",
     "        if not license_state.is_gated():\n            return await call_next(request)",
     "        if True:  # MUTANT\n            return await call_next(request)"),

    ("Child PIN throttle",
     "core/child_throttle.py",
     "    return _delay_for_count(count)",
     "    return 0.0  # MUTANT"),

    ("P5: AAD context binding on encrypt",
     "core/encryption.py",
     "def aad_for(table: str, column: str, row_key: str) -> bytes:",
     "def aad_for(table: str, column: str, row_key: str) -> bytes:\n    return b\"bede/v2/MUTANT\"  # MUTANT — every row shares one AAD"),

    ("P3: per-student key isolation",
     "core/student_keys.py",
     "    _cache[student_name] = (key, time.monotonic() + _CACHE_TTL_SECONDS)\n    return key\n\n\nasync def get_existing",
     "    _cache[student_name] = (key, time.monotonic() + _CACHE_TTL_SECONDS)\n    return b\"M\" * 32  # MUTANT — one shared key for every student\n\n\nasync def get_existing"),
]


def run_suite() -> tuple[bool, str]:
    """Returns (something_failed, summary_line)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "-p", "no:cacheprovider",
         "--tb=no", "-W", "ignore"],
        cwd=API, capture_output=True, text=True, timeout=2400,
    )
    tail = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    summary = tail[-1] if tail else "(no output)"
    return proc.returncode != 0, summary


def main():
    results = []
    for label, rel, needle, repl in MUTATIONS:
        path = API / rel
        original = path.read_text()
        if needle not in original:
            results.append((label, "SKIPPED", "needle not found — harness out of date"))
            print(f"[skip] {label}", flush=True)
            continue

        path.write_text(original.replace(needle, repl, 1))
        # A mutation that breaks the parse would give a false "detected".
        syn = subprocess.run([sys.executable, "-c", f"import ast;ast.parse(open({str(path)!r}).read())"],
                             capture_output=True)
        if syn.returncode != 0:
            path.write_text(original)
            results.append((label, "SKIPPED", "mutation broke the parse"))
            print(f"[skip] {label} (syntax)", flush=True)
            continue

        t0 = time.time()
        try:
            failed, summary = run_suite()
        finally:
            path.write_text(original)

        verdict = "DETECTED" if failed else "SURVIVED"
        results.append((label, verdict, summary))
        print(f"[{verdict:8}] {label}  ({time.time()-t0:.0f}s)  {summary}", flush=True)

    print("\n" + "=" * 78)
    survived = [r for r in results if r[1] == "SURVIVED"]
    print(f"{len(results)} mutations · {len(results)-len(survived)-sum(1 for r in results if r[1]=='SKIPPED')} detected · {len(survived)} SURVIVED")
    if survived:
        print("\nUNTESTED CONTROLS (suite stayed green with the control defeated):")
        for label, _, summary in survived:
            print(f"  - {label}")


if __name__ == "__main__":
    main()
