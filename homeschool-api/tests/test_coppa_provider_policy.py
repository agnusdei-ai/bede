"""Synthetic-only tests for COPPA provider routing and audio guards."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.coppa_provider_policy import (approved_provider, require_external_feature,
                                        require_qualified_local_endpoint)


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

    def test_direct_anthropic_factory_denied_before_sdk_construction(self):
        """Router bypasses cannot create a cloud client in enforced pilot mode."""
        from core.config import settings
        from services.adapters.anthropic_adapter import build_anthropic_client
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true"}),
              patch.object(settings, "educator_pilot_enabled", False),
              patch("anthropic.AsyncAnthropic") as sdk_factory):
            with self.assertRaises(PermissionError):
                build_anthropic_client("synthetic-only")
            sdk_factory.assert_not_called()

        # The institutional pilot wins over a concurrently enabled demo flag.
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", "synthetic-demo"),
              patch("anthropic.AsyncAnthropic") as sdk_factory):
            with self.assertRaises(PermissionError):
                build_anthropic_client("synthetic-only")
            sdk_factory.assert_not_called()

    def test_direct_anthropic_factory_preserves_nonpilot_behavior(self):
        """Ordinary nonpilot clients still use the unchanged SDK interface."""
        from core.config import settings
        from services.adapters.anthropic_adapter import build_anthropic_client
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", False),
              patch("anthropic.AsyncAnthropic") as sdk_factory):
            client = build_anthropic_client("synthetic-only")
            self.assertIs(client, sdk_factory.return_value)
            sdk_factory.assert_called_once_with(api_key="synthetic-only")

    def test_external_audio_is_denied(self):
        with patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true"}):
            for feature in ("transcription", "speech synthesis"):
                with self.assertRaises(PermissionError):
                    require_external_feature(feature)

    def test_demo_switch_cannot_downgrade_active_school_pilot(self):
        """An accidentally mixed demo/pilot configuration stays fail-closed."""
        from core.config import settings
        from core.coppa_provider_policy import enforcement_enabled
        from services.adapters.router import get_default_client
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", "demo-enabled"),
              patch.object(settings, "anthropic_api_key", "synthetic-not-real"),
              patch.object(settings, "bede_force_adapter", "anthropic")):
            self.assertTrue(enforcement_enabled())
            self.assertFalse(approved_provider("anthropic"))
            with self.assertRaises(PermissionError):
                require_external_feature("transcription")
            with self.assertRaises(PermissionError):
                get_default_client()

    def test_demo_without_school_pilot_retains_existing_policy(self):
        """The dedicated public demo is not implicitly a school pilot."""
        from core.config import settings
        from core.coppa_provider_policy import enforcement_enabled
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", False),
              patch.object(settings, "demo_pin", "demo-enabled")):
            self.assertFalse(enforcement_enabled())
            self.assertTrue(approved_provider("anthropic"))

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

    def test_pilot_rejects_public_urls_masquerading_as_local(self):
        from core.config import settings
        from services.adapters.router import get_default_client
        bad = (
            "https://api.example.org/v1",
            "http://8.8.8.8:11434/v1",
            "http://localhost.evil.example/v1",
            "http://user:secret@localhost:11434/v1",
            "http://169.254.169.254/v1",
            "http://[::ffff:169.254.169.254]/v1",
            "http://[::ffff:8.8.8.8]/v1",
            "http://0.0.0.0:11434/v1",
            "http://localhost:99999/v1",
            "file:///tmp/local",
        )
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", ""),
              patch.object(settings, "bede_force_adapter", "local")):
            for url in bad:
                with self.subTest(url=url):
                    with self.assertRaises(PermissionError):
                        require_qualified_local_endpoint(url)
                    with patch.object(settings, "local_llm_base_url", url):
                        with self.assertRaises(PermissionError):
                            get_default_client()

    def test_pilot_allows_known_mac_and_private_local_endpoints(self):
        from core.config import settings
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", "")):
            for url in (
                "http://localhost:11434/v1",
                "http://127.0.0.1:11434/v1",
                "http://host.docker.internal:11434/v1",
                "http://192.168.1.42:11434/v1",
                "http://10.0.0.5:11434/v1",
                "http://[::1]:11434/v1",
            ):
                with self.subTest(url=url):
                    self.assertIsNone(require_qualified_local_endpoint(url))

    def test_nonpilot_legacy_behavior_unchanged(self):
        from core.config import settings
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", False)):
            self.assertIsNone(require_qualified_local_endpoint("https://example.org/v1"))

    def test_public_demo_switch_cannot_override_pilot_policy(self):
        """Mixed demo/pilot mode must never disable local-only inference.

        Demo-only behavior is independently covered above. This former
        legacy expectation would otherwise contradict the security fix.
        """
        from core.config import settings
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", "synthetic-demo-only")):
            self.assertFalse(approved_provider("anthropic"))
            self.assertTrue(approved_provider("local"))
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true"}),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", "synthetic-demo-only")):
            self.assertFalse(approved_provider("anthropic"))


if __name__ == "__main__":
    unittest.main()
