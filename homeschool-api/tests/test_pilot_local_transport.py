"""Synthetic strict local HTTP transport regression tests; no network requests."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PilotLocalTransportTests(unittest.TestCase):
    def test_pilot_adapter_disables_environment_proxies_and_redirects(self):
        from core.config import settings
        from services.adapters.router import get_default_client
        from services.adapters.openai_compatible_adapter import OpenAICompatibleClient

        with (patch.dict(os.environ, {
                  "BEDE_COPPA_ENFORCE": "false",
                  "HTTPS_PROXY": "https://public-proxy.example.invalid",
                  "HTTP_PROXY": "http://public-proxy.example.invalid",
              }),
              patch.object(settings, "educator_pilot_enabled", True),
              patch.object(settings, "demo_pin", ""),
              patch.object(settings, "bede_force_adapter", "local"),
              patch.object(settings, "local_llm_base_url", "http://127.0.0.1:11434/v1"),
              patch("httpx.AsyncClient") as transport_factory,
              patch("openai.AsyncOpenAI") as sdk_factory):
            adapter = get_default_client()
            self.assertIsInstance(adapter, OpenAICompatibleClient)
            self.assertEqual(transport_factory.call_count, 1)
            kwargs = transport_factory.call_args.kwargs
            self.assertIs(kwargs["trust_env"], False)
            self.assertIs(kwargs["follow_redirects"], False)
            # Retain an inference-friendly timeout; a 5-second httpx read
            # timeout would break ordinary local generation.
            self.assertEqual(kwargs["timeout"].read, 600.0)
            self.assertEqual(kwargs["timeout"].connect, 5.0)
            self.assertIs(sdk_factory.call_args.kwargs["http_client"],
                          transport_factory.return_value)
            self.assertEqual(sdk_factory.call_args.kwargs["base_url"],
                             "http://127.0.0.1:11434/v1")

    def test_strict_transport_rejects_public_endpoint_without_client(self):
        from services.adapters.openai_compatible_adapter import OpenAICompatibleClient
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true"}),
              patch("httpx.AsyncClient") as transport_factory,
              patch("openai.AsyncOpenAI") as sdk_factory):
            with self.assertRaises(PermissionError):
                OpenAICompatibleClient(
                    base_url="https://public.example.invalid/v1",
                    strict_local_transport=True,
                )
            transport_factory.assert_not_called()
            sdk_factory.assert_not_called()

    def test_strict_transport_cannot_run_without_active_egress_policy(self):
        from core.config import settings
        from services.adapters.openai_compatible_adapter import OpenAICompatibleClient
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", False),
              patch("httpx.AsyncClient") as transport_factory,
              patch("openai.AsyncOpenAI") as sdk_factory):
            with self.assertRaises(PermissionError):
                OpenAICompatibleClient(
                    base_url="http://localhost:11434/v1",
                    strict_local_transport=True,
                )
            transport_factory.assert_not_called()
            sdk_factory.assert_not_called()

    def test_direct_adapter_cannot_bypass_school_pilot_egress(self):
        """Even non-router callers cannot opt out of the enforced boundary."""
        from services.adapters.openai_compatible_adapter import OpenAICompatibleClient
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true"}),
              patch("httpx.AsyncClient") as transport_factory,
              patch("openai.AsyncOpenAI") as sdk_factory):
            for url in ("", "https://public.example.invalid/v1",
                        "http://169.254.169.254/v1"):
                with self.subTest(url=url):
                    with self.assertRaises(PermissionError):
                        OpenAICompatibleClient(
                            base_url=url, strict_local_transport=False,
                        )
            transport_factory.assert_not_called()
            sdk_factory.assert_not_called()

    def test_direct_local_adapter_automatically_uses_strict_transport(self):
        """A caller cannot silently inherit proxies or follow redirects."""
        from services.adapters.openai_compatible_adapter import OpenAICompatibleClient
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "true",
                                      "HTTPS_PROXY": "https://public.example.invalid"}),
              patch("httpx.AsyncClient") as transport_factory,
              patch("openai.AsyncOpenAI") as sdk_factory):
            OpenAICompatibleClient(
                base_url="http://127.0.0.1:11434/v1",
                strict_local_transport=False,
            )
            kwargs = transport_factory.call_args.kwargs
            self.assertIs(kwargs["trust_env"], False)
            self.assertIs(kwargs["follow_redirects"], False)
            self.assertIs(sdk_factory.call_args.kwargs["http_client"],
                          transport_factory.return_value)

    def test_legacy_nonpilot_adapter_unchanged(self):
        from core.config import settings
        from services.adapters.router import get_default_client
        with (patch.dict(os.environ, {"BEDE_COPPA_ENFORCE": "false"}),
              patch.object(settings, "educator_pilot_enabled", False),
              patch.object(settings, "bede_force_adapter", "local"),
              patch.object(settings, "local_llm_base_url", "http://localhost:11434/v1"),
              patch("httpx.AsyncClient") as transport_factory,
              patch("openai.AsyncOpenAI") as sdk_factory):
            get_default_client()
            transport_factory.assert_not_called()
            self.assertNotIn("http_client", sdk_factory.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
