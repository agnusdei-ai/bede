"""Load and query the repair-loop policy. Default deny.

The policy is read only from the trusted checkout of main (the run's own
github.sha), never from the candidate under test, so a candidate cannot
loosen the rules it is judged by.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = REPO / "config" / "release-repair.json"

REQUIRED_KEYS = ("budgets", "branch_pattern", "protected_paths", "sensitive_paths",
                 "test_paths", "existing_test_changes", "failures", "execution")
NEVER_SILENT = ("removed_acceptance_assertion", "weakened_expected_result",
                "new_skip_for_unresolved_failure", "failure_relabelled_as_success")


class PolicyError(ValueError):
    pass


def _match(path: str, patterns) -> bool:
    for pat in patterns:
        if fnmatch.fnmatchcase(path, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatchcase(path, pat[3:]):
            return True
    return False


@dataclass(frozen=True)
class Policy:
    data: dict
    revision: str

    @property
    def repair_budget(self) -> int:
        return int(self.data["budgets"]["repair_attempts_per_task"])

    @property
    def lease_ttl(self) -> int:
        return int(self.data.get("lease_ttl_seconds", 21600))

    def branch_ok(self, branch: str) -> bool:
        return re.fullmatch(self.data["branch_pattern"], branch or "") is not None

    def is_protected(self, path: str) -> bool:
        return _match(path, self.data["protected_paths"])

    def is_sensitive(self, path: str) -> bool:
        return _match(path, self.data["sensitive_paths"])

    def is_test(self, path: str) -> bool:
        return _match(path, self.data["test_paths"])

    def failure_rules(self) -> list[dict]:
        return list(self.data["failures"])

    def diagnosis_for(self, failure_key: str) -> dict | None:
        """The trusted-diagnosis pins for one failure, or None when it has none."""
        for rule in self.data["failures"]:
            if rule.get("key") == failure_key:
                return rule.get("trusted_diagnosis")
        return None

    def trusted_diagnoses(self) -> list[dict]:
        return [r["trusted_diagnosis"] for r in self.data["failures"] if r.get("trusted_diagnosis")]


_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _check_diagnosis(key, d: dict):
    """A trusted diagnosis names one workflow and exact pins, never a range."""
    if not re.fullmatch(r"\.github/workflows/[a-z0-9-]+\.yml", str(d.get("workflow", ""))):
        raise PolicyError(f"{key}: trusted_diagnosis.workflow must name one workflow file")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", str(d.get("node", ""))):
        raise PolicyError(f"{key}: trusted_diagnosis.node must be one exact version")
    for side in ("baseline", "comparison"):
        pin = d.get(side) or {}
        if not _VERSION.match(str(pin.get("playwright", ""))) or not pin.get("webkit"):
            raise PolicyError(f"{key}: trusted_diagnosis.{side} needs an exact playwright and webkit pin")
    if d["baseline"]["playwright"] == d["comparison"]["playwright"]:
        raise PolicyError(f"{key}: the control and the comparison must be different versions")
    if not d.get("engine") or not d.get("artifact_prefix") or int(d.get("macos_min_major", 0)) < 1:
        raise PolicyError(f"{key}: trusted_diagnosis needs engine, artifact_prefix and macos_min_major")


def load(path: Path | str = DEFAULT_POLICY) -> Policy:
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise PolicyError(f"policy missing {missing}")
    ex = data["execution"]
    if ex.get("model_in_ci") or ex.get("secrets_in_ci") or ex.get("deploy") or ex.get("merge"):
        raise PolicyError("policy may not enable a model, secrets, deploy or merge in CI")
    if int(data["budgets"]["repair_attempts_per_task"]) not in (1, 2):
        raise PolicyError("repair budget is bounded to 1 or 2 attempts (qa-reliability.md)")
    etc = data["existing_test_changes"]
    if etc.get("default") != "require_authorization":
        raise PolicyError("existing test changes must default to require_authorization")
    if set(NEVER_SILENT) - set(etc.get("never_allow_silently", [])):
        raise PolicyError("a never-silent test-change class was removed from policy")
    for rule in data["failures"]:
        if rule.get("suppress_repair") and not rule.get("owner_approval_ref"):
            raise PolicyError(f"{rule.get('key')}: suppress_repair needs an owner_approval_ref")
        if rule.get("disposition") != "investigate" and not rule.get("owner_approval_ref"):
            raise PolicyError(f"{rule.get('key')}: only 'investigate' needs no owner approval")
        diag = rule.get("trusted_diagnosis")
        if diag is not None:
            _check_diagnosis(rule.get("key"), diag)
    return Policy(data=data, revision=hashlib.sha256(raw).hexdigest())


def load_acceptance(path: Path | str) -> dict:
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if "gates" not in data or "test_only" not in data or "label" not in data:
        raise PolicyError("acceptance manifest needs label, test_only and gates")
    data["_revision"] = hashlib.sha256(raw).hexdigest()
    return data
