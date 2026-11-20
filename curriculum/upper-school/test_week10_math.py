"""Exact arithmetic and source/packet checks, not independent academic approval."""
from fractions import Fraction as Q
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent


def intersection(m1, b1, m2, b2):
    if m1 == m2:
        return "infinite" if b1 == b2 else "none"
    x = Q(b2 - b1) / Q(m1 - m2)
    return x, m1 * x + b1


class MathematicsTests(unittest.TestCase):
    def test_adapted_wallace_examples(self):
        self.assertEqual(3 * 2 - 1, 5)
        self.assertEqual(2 + 1, 3)
        self.assertEqual(intersection(Q(-1, 2), 3, Q(3, 4), -2), (4, 1))

    def test_guided_and_exit_intersections(self):
        cases = [
            (1, 2, 2, 0, (2, 4)),
            (1, 1, -1, 5, (2, 3)),
            (2, 1, -1, 7, (2, 5)),
            (2, 6, 1, 18, (12, 30)),
            (3, 4, 1, 16, (6, 22)),
            (1, 2, -1, 4, (1, 3)),
            (-1, 6, 1, 2, (2, 4)),
            (5, 3, 2, 15, (4, 23)),
            (1, 3, -1, 9, (3, 6)),
        ]
        for m1, b1, m2, b2, expected in cases:
            with self.subTest(expected=expected, lines=(m1, b1, m2, b2)):
                actual = intersection(m1, b1, m2, b2)
                self.assertEqual(actual, expected)
                x, y = actual
                self.assertEqual(y, m1 * x + b1)
                self.assertEqual(y, m2 * x + b2)

    def test_parallel_and_coincident(self):
        for m, a, b in [(2, 1, -3), (3, 1, 7), (4, 1, -2), (5, 2, -1)]:
            self.assertEqual(intersection(m, a, m, b), "none")
        self.assertEqual(intersection(-2, 5, -2, 5), "infinite")
        self.assertEqual(intersection(3, 4, 3, 4), "infinite")

    def test_day_one_and_assessment_checks(self):
        self.assertEqual(3 + 5, 8)
        self.assertEqual(2 * 3 - 5, 1)
        self.assertEqual(2 * 2 + 1, 5)
        self.assertEqual(2 + 5, 7)
        self.assertEqual(6 + 2 * 8, 22)
        self.assertEqual(18 + 8, 26)
        self.assertEqual(6 + 2 * 16, 38)
        self.assertEqual(18 + 16, 34)

    def test_packet_separation_and_time(self):
        student = (HERE / "grade-9-week-10-math-student.md").read_text()
        teacher = (HERE / "grade-9-week-10-math-teacher.md").read_text()
        days = re.split(r"^## Day (\d):[^\n]*\n", student, flags=re.M)
        self.assertEqual(days[1::2], list("12345"))
        for number, body in zip(days[1::2], days[2::2]):
            body = body.split("\n## ", 1)[0]
            if number != "5":
                minutes = [int(n) for n in re.findall(r"— (\d+) minutes", body)]
                self.assertEqual(sum(minutes), 60)
        self.assertEqual(25 + 20 + 15, 60)
        self.assertIn("Independent Day 5 key", teacher)
        self.assertNotIn("Independent Day 5 key", student)
        self.assertIn("Delayed check: seven days later", student)
        for filename in re.findall(r"\]\(([^)]+)\)", student):
            self.assertTrue((HERE / filename).exists())


if __name__ == "__main__":
    unittest.main()
