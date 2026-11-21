"""Exhaustive checks of the authored Boolean examples, not academic approval."""
import itertools
from pathlib import Path
import re
import unittest

TEXT = (Path(__file__).parent / "grade-9-week-10-computing.md").read_text()


class ComputingTests(unittest.TestCase):
    def test_all_truth_table_rows(self):
        expressions = {
            "A and R": lambda a, r: a and r,
            "A or R": lambda a, r: a or r,
            "not A": lambda a, r: not a,
            "not (A or R)": lambda a, r: not (a or r),
            "(not A) and R": lambda a, r: (not a) and r,
            "not (A and R)": lambda a, r: not (a and r),
        }
        for label, fn in expressions.items():
            row = next(line for line in TEXT.splitlines()
                       if line.startswith(f"| {label} |"))
            expected = [cell.strip() == "T" for cell in row.split("|")[2:-1]]
            actual = [fn(a, r) for a, r in itertools.product((False, True), repeat=2)]
            self.assertEqual(actual, expected, label)

    def test_printed_python_function(self):
        blocks = re.findall(r"```python\n(.*?)```", TEXT, re.S)
        self.assertEqual(len(blocks), 1)
        namespace = {}
        exec(compile(blocks[0], "<authored-local-example>", "exec"), namespace)
        function = namespace["cabinet_rule"]
        for a, r in itertools.product((False, True), repeat=2):
            self.assertEqual(function(a, r), a and r)
        self.assertEqual(function(None, True), "unknown")
        self.assertEqual(function(False, None), "unknown")
        with self.assertRaises(ValueError):
            function("false", True)
        with self.assertRaises(ValueError):
            function(1, True)

    def test_delayed_and_counterexample(self):
        pairs = list(itertools.product((False, True), repeat=2))
        self.assertEqual([c and not v for c, v in pairs], [False, False, True, False])
        self.assertNotEqual(not (True or False), (not True) or (not False))

    def test_five_sessions(self):
        sections = re.split(r"^### Day \d[^\n]*\n", TEXT, flags=re.M)[1:]
        self.assertEqual(len(sections), 5)
        for section in sections:
            section = section.split("\n## ", 1)[0]
            self.assertEqual(sum(map(int, re.findall(r"\*\*(\d+)m ", section))), 30)
        self.assertEqual(TEXT.count("## Adult-only teaching key"), 1)


if __name__ == "__main__":
    unittest.main()
