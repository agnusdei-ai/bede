"""Structural regression checks, not substitutes for academic review."""
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent


class HumanitiesPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.student = (HERE / "grade-9-week-10-humanities.md").read_text()
        cls.teacher = (HERE / "grade-9-week-10-humanities-teacher.md").read_text()

    def test_three_subjects_with_five_days_each(self):
        for subject in ("Literature", "History", "Latin"):
            section = self.student.split("## " + subject + " —", 1)[1].split("\n## ", 1)[0]
            self.assertEqual(re.findall(r"### Day (\d)", section), list("12345"))
            self.assertEqual(section.count("(60 minutes)"), 5)
            self.assertIn("**Delayed check:**", section)

    def test_each_daily_agenda_is_sixty_minutes(self):
        days = re.split(r"### Day \d[^\n]+\n", self.student)[1:]
        self.assertEqual(len(days), 15)
        for day in days:
            agenda = day.strip().split("\n\n")[0]
            self.assertEqual(sum(map(int, re.findall(r"\b(\d+)m\b", agenda))), 60, agenda)

    def test_keys_separated_and_status_honest(self):
        self.assertNotIn("Day 5 rubric", self.student)
        self.assertNotIn("Day 5:\n1. bonus:", self.student)
        for phrase in ("not approved course completion", "invented practice dossier",
                       "not learner retrieval content"):
            self.assertIn(phrase, self.student)
        self.assertIn("not a separate specialist review", self.teacher)

    def test_latin_keys_preserve_taught_agreement(self):
        # Explicit expected keys protect critical forms from editorial drift.
        for phrase in ("nauta bonus", "puellae bonae dōna parva portant",
                       "Nautae bonī dōnum parvum portant",
                       "nautās bonōs puellae bonae amant"):
            self.assertIn(phrase, self.teacher)
        self.assertIn("masculine accusative plural", self.teacher)
        self.assertIn("neuter nominative/accusative", self.teacher)


if __name__ == "__main__":
    unittest.main()
