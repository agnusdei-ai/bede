import pathlib
import tempfile
import unittest
from leaf_baseline import classify, evaluate, load_records, parse_divided


class LeafBaselineTests(unittest.TestCase):
    def test_simple_broad(self):
        self.assertEqual(classify("flat", False), "simple_broad")

    def test_compound(self):
        self.assertEqual(classify("flat", True), "compound_broad")

    def test_needle(self):
        self.assertEqual(classify("needle", False), "needle_like")

    def test_missing(self):
        self.assertEqual(classify("flat", None), "unknown")
        self.assertEqual(classify("unknown", None), "unknown")

    def test_inconsistent_and_bad_type(self):
        self.assertEqual(classify("needle", True), "unknown")
        self.assertEqual(classify("flat", "false"), "unknown")
        self.assertEqual(classify("flat", 1), "unknown")

    def test_parser(self):
        self.assertIs(parse_divided("false"), False)
        self.assertIs(parse_divided("true"), True)
        self.assertIsNone(parse_divided(""))
        with self.assertRaises(ValueError):
            parse_divided("maybe")

    def test_needle_rejects_numeric_and_string_division(self):
        for divided in (0, 0.0, 1, "false", ""):
            with self.subTest(divided=divided):
                self.assertEqual(classify("needle", divided), "unknown")
        self.assertEqual(classify("needle", None), "needle_like")

    def test_schema_width_and_duplicate_headers(self):
        header = "id,split,blade,divided,reference,note"
        cases = [
            header + "\nx,test,flat,false,simple_broad,ok,EXTRA\n",
            header + "\nx,test,flat,false,simple_broad\n",
            header + ",id\nx,test,flat,false,simple_broad,ok,y\n",
        ]
        with tempfile.TemporaryDirectory() as folder:
            p = pathlib.Path(folder) / "bad.csv"
            for text in cases:
                with self.subTest(text=text):
                    p.write_text(text, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_records(p)

    def test_present_blank_note_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            p = pathlib.Path(folder) / "blank.csv"
            p.write_text("id,split,blade,divided,reference,note\n"
                         "x,test,flat,false,simple_broad,\n", encoding="utf-8")
            self.assertEqual(load_records(p)[0]["note"], "")

    def test_fictional_counts(self):
        records = load_records(pathlib.Path(__file__).with_name("observations.csv"))
        result = evaluate(records)
        self.assertEqual(result["known_reference"], 5)
        self.assertEqual(result["correct"], 3)
        self.assertEqual(result["wrong"], 1)
        self.assertEqual(result["abstain"], 1)
        self.assertEqual(result["unknown_reference"], 1)
        self.assertAlmostEqual(result["accuracy_including_abstentions"], .6)
        self.assertAlmostEqual(result["coverage"], .8)
        self.assertAlmostEqual(result["accuracy_when_covered"], .75)

    def test_empty(self):
        self.assertIsNone(evaluate([])["coverage"])
        self.assertIsNone(evaluate([])["accuracy_when_covered"])

    def test_bad_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            p = pathlib.Path(folder) / "bad.csv"
            p.write_text("name,value\nsomeone,1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_records(p)

    def test_duplicate_id(self):
        with tempfile.TemporaryDirectory() as folder:
            p = pathlib.Path(folder) / "bad.csv"
            p.write_text("id,split,blade,divided,reference,note\n"
                         "x,test,flat,false,simple_broad,one\n"
                         "x,test,flat,true,compound_broad,two\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_records(p)


if __name__ == "__main__":
    unittest.main()

