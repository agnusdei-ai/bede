"""Portable document-only validation. No app, network, DB, environment or writes."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
EXPECTED = {
    "README.md", "01-decisions.md", "02-capabilities.md", "03-gates-and-risks.md",
    "04-rights-guide.md", "05-research-evidence.md", "06-operating-model.md",
    "07-verification.md", "INTEGRATION.md", "source-register.json",
    "source-register-template.json", "source-evidence.json", "validate.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    actual = {p.name for p in ROOT.iterdir() if p.is_file()}
    require(actual == EXPECTED, f"Unexpected/missing files: {actual ^ EXPECTED}")
    template = json.loads((ROOT / "source-register-template.json").read_text())
    register = json.loads((ROOT / "source-register.json").read_text())
    entries = register["entries"]
    require(len(entries) == 12, "Expected bounded twelve-source register")
    require(len({x["source_id"] for x in entries}) == 12, "Duplicate source IDs")
    totals = {}
    for entry in entries:
        require(set(entry) == set(template), f"Entry fields: {entry['source_id']}")
        require(set(entry["permissions"]) == set(template["permissions"]),
                f"Seven separate uses required: {entry['source_id']}")
        require(all(isinstance(v, str) and v.strip()
                    for v in entry["permissions"].values()), "Empty use judgment")
        require(entry["permissions"]["train"] == "NOT AUTHORIZED BY THIS PROJECT",
                "No default model training")
        require(entry["reviewer"]["human_review"] == "PENDING", "No fabricated approval")
        require(entry["rights_evidence"]["asset_hash"] is None, "No asset acquisition")
        for url in (entry["source_url"], entry["rights_evidence"]["url"]):
            require(url.startswith("https://"), "Exact HTTPS source/evidence required")
        require(re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                             entry["rights_evidence"]["checked_date"]), "Evidence date")
        totals[entry["decision"]] = totals.get(entry["decision"], 0) + 1
    require(totals == {"APPROVED CANDIDATE": 5, "EXTERNAL ONLY": 3,
                       "HOLD": 3, "REJECT": 1}, f"Unexpected decisions: {totals}")
    evidence = json.loads((ROOT / "source-evidence.json").read_text())
    require(evidence["head"] == "597057406489880a1abe3fb57ac1beaafc48e776",
            "Historical evidence must not be silently relabeled current")
    require(len(evidence["sample_checks_executed"]) == 15,
            "Historical checks changed")
    require(not evidence["upstream_curriculum_tests"]["executed"],
            "Do not fabricate upstream execution")
    for item in evidence["files"]:
        require(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "Source digest format")
        require(item["line_count"] > 0 and ".." not in Path(item["path"]).parts,
                "Invalid historical source reference")
    secrets = re.compile(
        r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        r"|AKIA[0-9A-Z]{16}"
    )
    links = 0
    for file in ROOT.iterdir():
        if not file.is_file():
            continue
        require(file.stat().st_size < 150_000, f"Unexpected bulk file: {file.name}")
        text = file.read_text(encoding="utf-8")
        require("\0" not in text and not secrets.search(text), f"Unsafe text: {file.name}")
        if file.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if "://" not in target and not target.startswith("#"):
                    require((ROOT / target.split("#")[0]).is_file(),
                            f"Broken local link: {file.name}: {target}")
                    links += 1
    print("PASS: 13 text-only files; 12 source entries; 7 separate use judgments each")
    print(f"PASS: candidate totals/pending reviews/no training; {links} local links")
    print("PASS: historical evidence preserved; common token-pattern/bulk-text checks")
    print("LIMIT: not current runtime, authenticated review, rights or deployment approval")


if __name__ == "__main__":
    main()
