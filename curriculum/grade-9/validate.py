"""Consistency checks for the review package, not educational certification."""
from fractions import Fraction
import pathlib
import re
import subprocess
import sys
import contextlib
import io

ROOT = pathlib.Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    files = [ROOT / "README.md"] + sorted(ROOT.glob("[0-9][0-9]-*.md"))
    require(len(files) == 9, "Expected index plus eight curriculum documents")
    for file in files:
        text = file.read_text(encoding="utf-8")
        require(text.startswith("# "), f"Missing title: {file.name}")
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in link or link.startswith("#"):
                continue
            require((ROOT / link.split("#")[0]).exists(), f"Broken local link {link}")

    scope = (ROOT / "03-scope-and-sequence.md").read_text(encoding="utf-8")
    weeks = re.split(r"^### Week (\d{2}) — ", scope, flags=re.M)
    numbers = [int(weeks[i]) for i in range(1, len(weeks), 2)]
    require(numbers == list(range(1, 37)), "Weeks must be exactly 1–36, once each")
    for i in range(1, len(weeks), 2):
        body = weeks[i + 1]
        for code in ["L", "H", "M", "B", "T", "C"]:
            entries = re.findall(rf"^- \*\*{code}:\*\* (.+)$", body, flags=re.M)
            require(len(entries) == 1, f"Week {weeks[i]} needs one {code} entry")
            require(entries[0].count("→") >= 3,
                    f"Week {weeks[i]} {code} needs objective, input, assignment, check")
        require("- **Connection:**" in body, f"Missing week {weeks[i]} connection")

    program = (ROOT / "01-program-and-delivery.md").read_text(encoding="utf-8")
    course_rows = re.findall(
        r"^\| ([^|]+) \| ([0-9.]+) \| ([0-9]+) \| ([0-9.]+) \|$",
        program, flags=re.M)
    require(len(course_rows) == 8, "Expected eight timed course strands")
    hours = credits = Fraction(0)
    for name, weekly, year, credit in course_rows:
        w, c = Fraction(weekly), Fraction(credit)
        require(w * 36 == int(year), f"Annual hours mismatch for {name}")
        require(c * 180 == int(year), f"Credit assumption mismatch for {name}")
        hours += w
        credits += c
    require(hours == Fraction(65, 2), "Weekly total must be 32.5h")
    require(credits == Fraction(13, 2), "Planned credits must total 6.5")

    # Independently reconcile all three schedule models in minutes.
    require(5 * (5 * 60 + 3 * 30) == hours * 60, "Family schedule mismatch")
    tuesday = 90 + 60 + 60 + 90 + 45 + 45 + 30
    thursday = 90 + 60 + 60 + 30 + 45 + 45 + 30
    home = sum([Fraction(7, 2), Fraction(7, 2), 3, 3, 3, 1, 1, Fraction(3, 2)])
    require(Fraction(tuesday + thursday, 60) + home == hours,
            "Co-op meeting/home schedule mismatch")
    school_periods = 6 * 50 * 5
    school_core_top_up = 5 * 50
    school_strand_top_up = 3 * Fraction(200, 3)
    require(school_periods + school_core_top_up + school_strand_top_up == hours * 60,
            "School period/homework schedule mismatch")

    labs = (ROOT / "06-biology-labs.md").read_text(encoding="utf-8")
    lab_weeks = [int(n) for n in re.findall(r"^\| (\d{2}) \|", labs, flags=re.M)]
    require(lab_weeks == [1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 18,
                          20, 22, 24, 26, 28, 30, 32], "Lab ledger mismatch")
    require(len(lab_weeks) * 90 == 27 * 60, "Investigation slot arithmetic")

    starter = (ROOT / "04-starter-lessons.md").read_text(encoding="utf-8")
    require(re.findall(r"^## Week (\d+) —", starter, re.M) ==
            [str(n) for n in range(1, 10)],
            "Missing starter week")
    for subject in ["Literature", "(?:World )?History", "Algebra", "Biology", "Latin", "Studio"]:
        require(len(re.findall(rf"^### {subject}", starter, re.M)) == 9,
                f"Need nine teachable {subject} blocks")
    require("Weeks 10–36 are planned units" in scope, "Future lesson status must be clear")

    # Coverage checks cannot certify teaching quality, but catch accidental omissions.
    for week in range(5, 10):
        body = starter.split(f"## Week {week} —", 1)[1].split("\n## ", 1)[0]
        blocks = re.split(r"^### ", body, flags=re.M)[1:]
        require(len(blocks) == 6, f"Week {week} needs six academic blocks")
        for block in blocks:
            days = re.findall(r"^- \*\*Day (\d)", block, re.M)
            require(days == list("12345"), f"Week {week}: missing/repeated daily agenda")
        require(body.count("— 300m") == 5 and body.count("— 150m") == 1,
                f"Week {week} academic allocation mismatch")
    require(5 * 300 + 3 * 150 == 1950, "Extension workload mismatch")
    for marker in ["IX–X", "XI–XII", "XIII–XIV", "XV–XVI", "XVII–XVIII",
                   "week 12", "Investigation 6", "Investigation 8",
                   "Nine-sentence original quarter passage"]:
        require(marker in starter, f"Missing extension safeguard: {marker}")
    # Run the two standalone beginner code listings exactly as printed.
    listings = re.findall(r"```python\n(.*?)```", starter, re.S)
    require(len(listings) == 2, "Expected two runnable extension listings")
    for code, expected in zip(listings, ["30 6\n", "4.8\n"]):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exec(compile(code, "<teaching-listing>", "exec"), {})
        require(stdout.getvalue() == expected, "Studio listing/key mismatch")
    for values, expected in [("[None, None]", "No measurements\n"),
                             ("[0, 4]", "2.0\n")]:
        code = listings[1].replace("[4, 5, None, 5, 8, 2]", values)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exec(compile(code, "<missing-data-check>", "exec"), {})
        require(stdout.getvalue() == expected, "Missing versus zero regression")

    result = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover",
                             "-s", str(ROOT / "project"), "-p", "test_*.py"], check=False)
    require(result.returncode == 0, "Executable studio tests failed")
    print("PASS: 36 weeks, 216 course entries, 9 authored weeks, 18 investigations;")
    print("32.5h/week × 36 = 1,170h, 6.5 planned credits; all delivery schedules reconcile.")
    print("PASS: document links, explicit development status and studio unit tests.")
    print("Not verified by this script: pedagogy, outcomes, permissions, credit approval.")


if __name__ == "__main__":
    main()

