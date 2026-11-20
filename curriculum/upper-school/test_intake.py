"""Offline intake checks; no internet or production connections."""
import io
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import intake


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(intake.CATALOG.read_text())["sources"][0]
        intake.HOST_RETRY_AT.clear()

    def test_explicit_catalog(self):
        catalog = json.loads(intake.CATALOG.read_text())
        self.assertEqual(len(catalog["sources"]), 9)
        records = intake.source_records(catalog)
        self.assertEqual(len(records), 18)
        self.assertEqual(sum(s["acquire"] for s in records), 16)
        self.assertEqual(len({s["id"] for s in records}), len(records))
        self.assertTrue(any(s["id"] == "python-license" and s["acquire"] for s in records))
        self.assertFalse(any("openstax" in s["url"].lower() for s in catalog["sources"]))
        self.assertEqual(len(self.source["expected_sha256"]), 64)

    def test_url_boundary(self):
        for url in ("http://www.gutenberg.org/x", "https://example.com/x",
                    "https://user:password@www.gutenberg.org/x",
                    "https://www.gutenberg.org:8443/x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                intake.checked_url(url)

    def test_payload_boundaries(self):
        with self.assertRaises(ValueError):
            intake.validate_payload(b"<html>service unavailable</html>", "pdf")
        with self.assertRaises(ValueError):
            intake.validate_payload(b"%PDF-truncated", "pdf")
        with self.assertRaises(ValueError):
            intake.validate_payload(b"Book without retained notices", "gutenberg-text")
        intake.validate_payload(
            b"*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
            b"Teaching text\n*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
            b"Project Gutenberg terms retained.", "gutenberg-text")
        with self.assertRaises(ValueError):
            intake.validate_payload(b"<html>service error</html>", "python-html")
        intake.validate_payload(
            b"<html><title>Python 3.14.10</title>Python Software Foundation</html>",
            "python-html")

    def test_same_host_redirect_boundary(self):
        handler = intake.SafeRedirect()
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, "redirect", {},
                                     "https://unlisted.example/text")

    def test_failed_download_leaves_no_source_file(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                "intake.download", side_effect=RuntimeError("offline test failure")):
            result = intake.acquire(self.source, Path(directory))
            self.assertEqual(result["acquisition_status"], "failed")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_changed_edition_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                "intake.download", return_value=(b"%PDF-test\n%%EOF",
                                                self.source["url"])):
            result = intake.acquire(self.source, Path(directory))
            self.assertEqual(result["acquisition_status"], "failed")
            self.assertIn("Source changed", result["error"])
            self.assertFalse((Path(directory) / "wallace-algebra.pdf").exists())

    def test_reference_only_never_downloaded(self):
        source = dict(self.source, acquire=False)
        with tempfile.TemporaryDirectory() as directory, patch("intake.download") as get:
            result = intake.acquire(source, Path(directory))
            get.assert_not_called()
            self.assertEqual(result["acquisition_status"], "external-reference-only")

    def test_valid_cache_reused_and_changed_pin_rejected(self):
        payload = b"%PDF-intake-test\n%%EOF"
        source = dict(self.source, expected_sha256=hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as directory, patch(
                "intake.download", return_value=(payload, source["url"])) as get:
            root = Path(directory)
            first = intake.acquire(source, root)
            second = intake.acquire(source, root)
            self.assertEqual(first["acquisition_status"], "acquired")
            self.assertEqual(second["acquisition_status"], "reused")
            self.assertEqual(get.call_count, 1)
            changed_pin = dict(source, expected_sha256="0" * 64)
            third = intake.acquire(changed_pin, root)
            self.assertEqual(third["acquisition_status"], "failed")
            self.assertIn("Cached source differs", third["error"])

    def test_retry_after_stops_other_books_on_same_host(self):
        error = HTTPError("https://www.gutenberg.org/x", 503, "Unavailable",
                          {"Retry-After": "21600"}, io.BytesIO())
        with patch("intake.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(HTTPError):
                intake.download("https://www.gutenberg.org/x")
            with self.assertRaises(RuntimeError):
                intake.download("https://www.gutenberg.org/y")
            self.assertEqual(opener.return_value.open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
