"""Pure, synthetic checks for the #726 voice dependency migration preflight."""
import unittest

from scripts.qa.voice_dependency_preflight import (
    assess,
    fixed_setuptools,
    required_vad_distributions,
)


class VoiceDependencyPreflightTests(unittest.TestCase):
    def setUp(self):
        self.fork = {
            "setuptools": "84.1.0",
            "resemblyzer": "0.1.1",
            "webrtcvad-wheels": "2.0.14.post1",
        }

    def results(self, versions, requirements, providers):
        return {
            row["check"]: row["result"]
            for row in assess(versions, requirements, providers)
        }

    def test_candidate_fork_requires_compatible_resemblyzer_metadata(self):
        checks = self.results(
            self.fork, ["webrtcvad-wheels>=2.0.14"], ["webrtcvad-wheels"]
        )
        self.assertTrue(all(result == "PASS" for result in checks.values()))

    def test_fork_does_not_satisfy_original_distribution_requirement(self):
        checks = self.results(
            self.fork, ["webrtcvad==2.0.10"], ["webrtcvad-wheels"]
        )
        self.assertEqual(checks["resemblyzer_metadata_compatible"], "FAIL")
        self.assertEqual(checks["single_vad_distribution"], "PASS")

    def test_missing_or_unrelated_vad_metadata_fails_closed(self):
        for requirements in ([], ["numpy>=1.0"]):
            with self.subTest(requirements=requirements):
                checks = self.results(
                    self.fork, requirements, ["webrtcvad-wheels"]
                )
                self.assertEqual(checks["resemblyzer_metadata_compatible"], "FAIL")

    def test_rejects_two_overlapping_vad_distributions(self):
        versions = {**self.fork, "webrtcvad": "2.0.10"}
        checks = self.results(
            versions, ["webrtcvad==2.0.10"], ["webrtcvad", "webrtcvad-wheels"]
        )
        self.assertEqual(checks["single_vad_distribution"], "FAIL")
        self.assertEqual(checks["module_provenance"], "FAIL")

    def test_rejects_module_owned_by_unexpected_distribution(self):
        checks = self.results(
            self.fork, ["webrtcvad-wheels>=2.0.14"], ["webrtcvad"]
        )
        self.assertEqual(checks["module_provenance"], "FAIL")

    def test_rejects_vulnerable_or_prerelease_setuptools(self):
        for version in ("83.0.0", "84.0.9", "84.1.0rc1", None, ""):
            with self.subTest(version=version):
                self.assertFalse(fixed_setuptools(version))
        self.assertTrue(fixed_setuptools("84.1.0"))
        self.assertTrue(fixed_setuptools("85.0.0"))

    def test_detects_dependency_name_not_python_module_name(self):
        self.assertEqual(
            required_vad_distributions([
                "numpy>=1.0", "webrtcvad==2.0.10; python_version >= '3.10'",
                "webrtcvad-wheels>=2.0.14",
            ]),
            {"webrtcvad", "webrtcvad-wheels"},
        )

    def test_missing_encoder_distribution_is_not_a_pass(self):
        versions = {key: value for key, value in self.fork.items()
                    if key != "resemblyzer"}
        checks = self.results(
            versions, ["webrtcvad-wheels>=2.0.14"], ["webrtcvad-wheels"]
        )
        self.assertEqual(checks["resemblyzer_installed"], "FAIL")


if __name__ == "__main__":
    unittest.main()
