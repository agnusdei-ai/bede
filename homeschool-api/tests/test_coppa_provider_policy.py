"""Synthetic-only tests for COPPA provider routing and audio guards."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.coppa_provider_policy import approved_provider, require_external_feature


class CoppaProviderPolicyTests(unittest.TestCase):
    def test_legacy_mode_preserves_existing_routing(self):
        with patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}):
            self.assertTrue(approved_provider("openai"))
            self.assertTrue(approved_provider("mistral"))

    def test_enforced_mode_allows_only_local(self):
        with patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true"}):
            self.assertTrue(approved_provider("local"))
            for provider in ("openai", "anthropic", "mistral", "experiment"):
                self.assertFalse(approved_provider(provider))

    def test_external_audio_is_denied(self):
        with patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true"}):
            for feature in ("transcription", "speech synthesis"):
                with self.assertRaises(PermissionError):
                    require_external_feature(feature)


if __name__ == "__main__":
    unittest.main()
