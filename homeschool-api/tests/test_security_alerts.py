"""Synthetic regression coverage for privacy-safe blocked-access notifications."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import security_alerts


class SecurityAlertTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        security_alerts._last_alert.clear()

    async def test_default_mailbox_and_redacted_payload(self):
        sender = AsyncMock(return_value=True)
        with patch.dict(os.environ, {"BEDE_SECURITY_ALERT_EMAIL": "bede@agnusdei.ai"}), patch(
            "services.email_service.send_email", sender
        ):
            ok = await security_alerts.alert_blocked_access("prohibited_endpoint", "192.0.2.10")
        self.assertTrue(ok)
        sender.assert_awaited_once()
        args = sender.await_args
        self.assertEqual(args.args[0], "bede@agnusdei.ai")
        self.assertNotIn("192.0.2.10", args.kwargs["html_body"])
        self.assertIn("prohibited_endpoint", args.kwargs["html_body"])

    async def test_duplicate_is_suppressed(self):
        sender = AsyncMock(return_value=True)
        with patch("services.email_service.send_email", sender):
            await security_alerts.alert_blocked_access("sensitive_response", "192.0.2.20")
            await security_alerts.alert_blocked_access("sensitive_response", "192.0.2.20")
        sender.assert_awaited_once()

    async def test_alert_failure_does_not_expose_or_unblock(self):
        with patch("services.email_service.send_email", AsyncMock(side_effect=RuntimeError("offline"))):
            self.assertFalse(await security_alerts.alert_blocked_access("prohibited_endpoint", "192.0.2.30"))


if __name__ == "__main__":
    unittest.main()
