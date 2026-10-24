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
        from core.config import settings
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", False)):
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

    def test_real_school_pilot_auto_enforces_without_opt_in(self):
        from core.config import settings
        from services.adapters.router import get_default_client, resolve_with_failover
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", ""),
              patch.object(settings, "anthropic_api_key", "synthetic-not-real"),
              patch.object(settings, "bede_force_adapter", "anthropic")):
            self.assertFalse(approved_provider("anthropic"))
            self.assertFalse(approved_provider("openai"))
            self.assertFalse(approved_provider("mistral"))
            self.assertTrue(approved_provider("local"))
            with self.assertRaises(PermissionError):
                require_external_feature("speech synthesis")
            # Forced provider and an unconfigured fallback cannot override
            # policy. This tests the single-client legacy path too.
            with self.assertRaises(PermissionError):
                get_default_client()
            self.assertEqual(resolve_with_failover()._live_order(), [])

    def test_real_pilot_unconfigured_fallback_does_not_construct_cloud(self):
        from core.config import settings
        from services.adapters.router import get_default_client
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", ""),
              patch.object(settings, "anthropic_api_key", ""),
              patch.object(settings, "bede_force_adapter", "not-an-adapter")):
            with self.assertRaises(PermissionError):
                get_default_client()

    def test_public_demo_remains_opt_in_not_pilot(self):
        from core.config import settings
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", "synthetic-demo-only")):
            self.assertTrue(approved_provider("anthropic"))
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", "synthetic-demo-only")):
            self.assertFalse(approved_provider("anthropic"))


if __name__ == "__main__":
    unittest.main()
