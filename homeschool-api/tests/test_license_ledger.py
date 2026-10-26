"""The issuance ledger: every key minted by hand leaves one local CSV row.

Pilots and trials are issued with scripts/issue_license.py, and nothing in
the product reports installs back (deliberately: a family's server runs
offline). So the operator's count of who holds a key is this ledger, and
these tests pin the three things that make it trustworthy: a row is written
for every key, a key is never printed without its row, and the ledger never
holds the key itself or lands in this public repository.

Ephemeral test-only Ed25519 keys; no real customer data.
"""
import csv
import sys

import pytest
from Crypto.PublicKey import ECC

from core import licensing
from scripts import issue_license


@pytest.fixture
def pem(tmp_path, monkeypatch):
    private = ECC.generate(curve="Ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", private.public_key().export_key(format="PEM"))
    path = tmp_path / "test-only.pem"
    path.write_text(private.export_key(format="PEM"))
    return path


def _issue(monkeypatch, pem, *extra):
    monkeypatch.setattr(sys, "argv", [
        "issue_license.py", "--tier", "trial", "--licensee", "trial-pilot-1",
        "--seats", "6", "--days", "30", "--private-key", str(pem), *extra,
    ])
    issue_license.main()


def _key(out: str) -> str:
    return out.split("LICENSE_KEY=", 1)[1].strip()


def test_each_issued_key_appends_one_row(tmp_path, monkeypatch, pem, capsys):
    ledger = tmp_path / "pilots" / "ledger.csv"
    _issue(monkeypatch, pem, "--ledger", str(ledger), "--customer", "Tester A")
    first = _key(capsys.readouterr().out)
    _issue(monkeypatch, pem, "--ledger", str(ledger), "--customer", "Tester B")
    second = _key(capsys.readouterr().out)

    rows = list(csv.DictReader(ledger.open(encoding="utf-8")))
    assert [r["customer"] for r in rows] == ["Tester A", "Tester B"]
    assert list(rows[0].keys()) == issue_license.LEDGER_COLUMNS

    info = licensing.verify_license(first)
    assert rows[0]["license_id"] == info.license_id
    assert rows[0]["tier"] == "trial" and rows[0]["seats"] == "6"
    assert rows[0]["licensee"] == "trial-pilot-1"
    assert rows[0]["expires"] == info.expires.isoformat()
    assert rows[0]["key_fingerprint"] == issue_license.key_fingerprint(first)
    assert rows[1]["key_fingerprint"] == issue_license.key_fingerprint(second)


def test_the_ledger_never_holds_the_key(tmp_path, monkeypatch, pem, capsys):
    ledger = tmp_path / "ledger.csv"
    _issue(monkeypatch, pem, "--ledger", str(ledger))
    key = _key(capsys.readouterr().out)
    text = ledger.read_text(encoding="utf-8")
    assert key not in text
    assert key.split(".")[0] not in text and key.split(".")[1] not in text


def test_the_environment_variable_sets_the_default(tmp_path, monkeypatch, pem, capsys):
    ledger = tmp_path / "from-env.csv"
    monkeypatch.setenv("BEDE_LICENSE_LEDGER", str(ledger))
    _issue(monkeypatch, pem)
    assert "LICENSE_KEY=" in capsys.readouterr().out
    assert len(list(csv.DictReader(ledger.open(encoding="utf-8")))) == 1


@pytest.mark.parametrize("inside", ["ledger.csv", "docs/pilots.csv"])
def test_a_ledger_inside_the_public_repository_is_refused_and_no_key_is_printed(
    monkeypatch, pem, capsys, inside,
):
    target = issue_license._REPO_ROOT / inside
    with pytest.raises(SystemExit) as exc:
        _issue(monkeypatch, pem, "--ledger", str(target))
    assert exc.value.code != 0
    assert not target.exists()
    captured = capsys.readouterr()
    assert "LICENSE_KEY=" not in captured.out
    assert "inside the repository" in captured.err


def test_an_unwritable_ledger_means_no_key(tmp_path, monkeypatch, pem, capsys):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    with pytest.raises(SystemExit):
        _issue(monkeypatch, pem, "--ledger", str(blocker / "ledger.csv"))
    assert "LICENSE_KEY=" not in capsys.readouterr().out
