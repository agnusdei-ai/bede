"""scripts/qualification/mac_check.py decides pass/fail from recorded server
answers. These tests feed it recorded calls and check the verdicts, including
the failing shapes (a read that still works after revocation, a reused
invitation that is accepted, an unknown id that differs from another campus's
learner). It runs in a subprocess because the script sets process environment
at import, which must not leak into other tests.

Not covered here, by design: the Touch ID ceremony itself. That is the part
only a person on a real Mac can show; see docs/SYNTHETIC_QUALIFICATION.md.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

DRIVER = r"""
import json, sys
sys.path.insert(0, %r)
import mac_check as m
def add(route, status, phase, method="POST", body="a", **extra):
    m.REC.marks.append(phase)
    m.REC.calls.append(dict(t=0, method=method, route=route, status=status, body_sha8=body, phase=phase, **extra))
case = json.loads(sys.argv[1])
for c in case["calls"]:
    add(**c)
print(json.dumps({k: v["server_says"] for k, v in m.evaluate().items()}))
""" % str(REPO / "scripts" / "qualification")

R = "/auth/educator-passkey/"
GOOD = [
    dict(route=R + "register/options", status=200, phase="enroll"),
    dict(route=R + "register/verify", status=200, phase="enroll"),
    dict(route=R + "register/options", status=401, phase="enroll"),
    dict(route=R + "login/verify", status=200, phase="enroll"),
    dict(route="/pilot/me/learners", status=200, phase="before_grant", method="GET", count=0, names=[]),
    dict(route="/pilot/me/learners", status=200, phase="after_grant", method="GET", count=1,
         names=["Synthetic Learner"]),
    dict(route="/pilot/me/learners/{id}", status=200, phase="after_grant", method="GET", body="own"),
    dict(route="/pilot/me/learners/{id}", status=404, phase="after_grant", method="GET", body="nf"),
    dict(route="/pilot/me/learners/{id}", status=404, phase="after_grant", method="GET", body="nf"),
    dict(route="/pilot/me/learners", status=401, phase="after_revoke", method="GET"),
    dict(route="/pilot/me/learners", status=200, phase="after_revoke", method="GET", count=0, names=[]),
]


def verdicts(calls):
    out = subprocess.run([sys.executable, "-I", "-c", DRIVER, json.dumps({"calls": calls})],
                         capture_output=True, text=True, cwd=str(REPO),
                         env={"PATH": "/usr/bin:/bin"}, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_correct_run_passes_every_item():
    assert set(verdicts(GOOD).values()) == {"PASS"}


def test_a_read_that_still_works_after_revocation_fails():
    calls = GOOD + [dict(route="/pilot/me/learners", status=200, phase="after_revoke",
                         method="GET", count=1, names=["Synthetic Learner"])]
    assert verdicts(calls)["revoked"] == "FAIL"


def test_a_reused_invitation_that_is_accepted_fails():
    calls = [dict(c, status=200) if c["status"] == 401 and "register" in c["route"] else c for c in GOOD]
    assert verdicts(calls)["reuse"] == "FAIL"


def test_other_campus_and_unknown_id_must_look_identical():
    calls = [dict(c, body="different") if c["route"].endswith("{id}") and c["status"] == 404 and i % 2
             else c for i, c in enumerate(GOOD)]
    assert verdicts(calls)["isolation"] == "FAIL"


def test_a_learner_visible_before_the_grant_fails():
    calls = [dict(c, count=1) if c["phase"] == "before_grant" else c for c in GOOD]
    assert verdicts(calls)["empty"] == "FAIL"

