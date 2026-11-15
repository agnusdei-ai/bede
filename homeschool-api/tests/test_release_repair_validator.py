"""The release-repair branch validator, against real git histories.

Existing-test changes default to the owner's authorization, four classes are
named and never allowed silently, protected paths need the owner, and a
branch outside release-repair/<cycle>/<task> or off its recorded base is
refused outright.
"""
from __future__ import annotations

import subprocess

import pytest

from release_repair_helpers import pol
from release_repair import validate, verify_regression

BR = "release-repair/c1/t001"


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.invalid"); git(r, "config", "user.name", "t")
    (r / "homeschool-api/tests").mkdir(parents=True)
    (r / "homeschool-api/services").mkdir(parents=True)
    (r / "homeschool-api/tests/test_x.py").write_text(
        "def test_a():\n    assert f() == 3\n\ndef test_b():\n    assert g() is True\n    status = 'FAIL'\n")
    (r / "homeschool-api/services/x.py").write_text("def f():\n    return 2\n")
    git(r, "add", "-A"); git(r, "commit", "-qm", "base")
    return r


def commit(repo, files: dict, msg="change"):
    for path, text in files.items():
        p = repo / path
        if text is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    git(repo, "add", "-A"); git(repo, "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD")


def run(repo, base, head, branch=BR):
    return validate.validate(repo, base, head, branch, pol())


def codes(report):
    return {v["code"] for v in report["violations"]}


def test_a_source_fix_with_a_new_test_passes_clean(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"homeschool-api/services/x.py": "def f():\n    return 3\n",
                         "homeschool-api/tests/test_new.py": "def test_new():\n    assert f() == 3\n"})
    assert run(repo, base, head)["ok"]


def test_editing_an_existing_test_needs_the_owner(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"homeschool-api/tests/test_x.py":
                         (repo / "homeschool-api/tests/test_x.py").read_text() + "\ndef test_c():\n    assert True\n"})
    r = run(repo, base, head)
    assert r["needs_authorization"] and not r["refused"] and codes(r) == {"existing_test_changed"}


@pytest.mark.parametrize("new_text,cls", [
    ("def test_a():\n    pass\n\ndef test_b():\n    assert g() is True\n    status = 'FAIL'\n", "removed_acceptance_assertion"),
    ("def test_a():\n    assert f() in (2, 3)\n\ndef test_b():\n    assert g() is True\n    status = 'FAIL'\n", "weakened_expected_result"),
    ("import pytest\n@pytest.mark.skip\ndef test_a():\n    assert f() == 3\n\ndef test_b():\n    assert g() is True\n    status = 'FAIL'\n",
     "new_skip_for_unresolved_failure"),
    ("def test_a():\n    assert f() == 3\n\ndef test_b():\n    assert g() is True\n    status = 'PASS'\n", "failure_relabelled_as_success"),
    (None, "removed_acceptance_assertion"),
])
def test_never_silent_test_changes_are_named(repo, new_text, cls):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"homeschool-api/tests/test_x.py": new_text})
    r = run(repo, base, head)
    named = [v for v in r["violations"] if v["code"] == cls]
    assert named and all(v["never_silent"] for v in named)
    assert not r["ok"]


def test_a_skip_in_a_brand_new_test_file_is_still_named(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"homeschool-api/tests/test_new.py": "import pytest\n@pytest.mark.skip\ndef test_n():\n    assert 0\n"})
    assert "new_skip_for_unresolved_failure" in codes(run(repo, base, head))


@pytest.mark.parametrize("path", [".github/workflows/x.yml", "scripts/release_repair/policy.py",
                                  "config/release-repair.json", "homeschool-api/core/encryption.py"])
def test_protected_paths_need_the_owner(repo, path):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {path: "x = 1\n"})
    r = run(repo, base, head)
    assert "protected_path_changed" in codes(r) and r["needs_authorization"]


def test_a_branch_outside_release_repair_is_refused(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"homeschool-api/services/x.py": "def f():\n    return 3\n"})
    for branch in ("main", "release-repair/c1", "copilot/x", "release-repair/C1/t"):
        r = run(repo, base, head, branch=branch)
        assert r["refused"] and "branch_name_outside_release_repair" in codes(r)


def test_a_head_not_built_on_the_recorded_base_is_refused(repo):
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "--orphan", "other")
    head = commit(repo, {"unrelated.txt": "x\n"}, "orphan")
    r = run(repo, base, head)
    assert r["refused"] and codes(r) == {"base_is_not_an_ancestor_of_head"}


def test_the_regression_check_demands_fail_before_and_pass_after(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"homeschool-api/services/x.py": "def f():\n    return 3\n",
                         "homeschool-api/tests/test_new.py": "def test_new():\n    assert True\n"})
    calls = []

    def fake(cmd, cwd, timeout):
        calls.append(str(cwd))
        return 1 if cwd.parent.name == "repo-base" or "repo-base" in str(cwd) else 0
    r = verify_regression.verify(repo, base, head, pol(), runner=fake)
    assert r["pre_fix_failed"] and r["post_fix_passed"] and r["tests"] == ["homeschool-api/tests/test_new.py"]
    assert any("repo-base" in c for c in calls)

    def always_pass(cmd, cwd, timeout):
        return 0
    head2 = commit(repo, {"homeschool-api/tests/test_new2.py": "def test_n():\n    assert True\n"})
    assert not verify_regression.verify(repo, head, head2, pol(), runner=always_pass)["pre_fix_failed"]


def test_a_change_with_no_regression_test_cannot_pass_verification(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"homeschool-api/services/x.py": "def f():\n    return 3\n"})
    r = verify_regression.verify(repo, base, head, pol(), runner=lambda *a: 0)
    assert r["reason"] == "no_runnable_regression_test_in_change" and not r["post_fix_passed"]


def test_neighboring_tests_need_every_report_for_this_head(tmp_path):
    import json
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"head": "h", "merge_status": "ready"}))
    assert not verify_regression.adjacent_passed([str(a), str(b)], "h")
    b.write_text(json.dumps({"head": "h", "merge_status": "blocked"}))
    assert not verify_regression.adjacent_passed([str(a), str(b)], "h")
    b.write_text(json.dumps({"head": "other", "merge_status": "ready"}))
    assert not verify_regression.adjacent_passed([str(a), str(b)], "h")
    b.write_text(json.dumps({"head": "h", "merge_status": "ready"}))
    assert verify_regression.adjacent_passed([str(a), str(b)], "h")
    assert not verify_regression.adjacent_passed([], "h")
