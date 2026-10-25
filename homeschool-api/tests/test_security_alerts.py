"""Synthetic regression coverage for privacy-safe blocked-access notifications."""
import asyncio
import hashlib
import hmac
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
            "core.security_alerts._send_alert_email", sender
        ):
            ok = await security_alerts.alert_blocked_access("prohibited_endpoint", "192.0.2.10")
        self.assertTrue(ok)
        sender.assert_awaited_once()
        args = sender.await_args
        self.assertEqual(args.args[0], "bede@agnusdei.ai")
        self.assertNotIn("192.0.2.10", args.kwargs["html_body"])
        self.assertIn("prohibited_endpoint", args.kwargs["html_body"])

    async def test_fingerprint_uses_secret_key_not_reversible_plain_ip_hash(self):
        ip = "192.0.2.10"
        key = b"bede-synthetic-test-key-only-1234"
        sender = AsyncMock(return_value=True)
        with patch.object(security_alerts, "_FINGERPRINT_KEY", key), patch(
            "core.security_alerts._send_alert_email", sender
        ):
            self.assertTrue(await security_alerts.alert_blocked_access("prohibited_endpoint", ip))
        html = sender.await_args.kwargs["html_body"]
        expected = hmac.new(key, ip.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
        unsafe_plain = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:12]
        self.assertIn(f"Source fingerprint: {expected}", html)
        self.assertNotEqual(expected, unsafe_plain)
        self.assertNotIn(unsafe_plain, html)
        self.assertNotIn(ip, html)

    async def test_fingerprint_rotates_with_secret_without_exposing_ip(self):
        ip = "192.0.2.99"
        sender = AsyncMock(return_value=True)
        with patch("core.security_alerts._send_alert_email", sender):
            with patch.object(security_alerts, "_FINGERPRINT_KEY", b"a" * 32):
                self.assertTrue(await security_alerts.alert_blocked_access("prohibited_endpoint", ip))
            with patch.object(security_alerts, "_FINGERPRINT_KEY", b"b" * 32):
                self.assertTrue(await security_alerts.alert_blocked_access("prohibited_endpoint", ip))
        self.assertEqual(sender.await_count, 2)
        first, second = [call.kwargs["html_body"] for call in sender.await_args_list]
        self.assertNotEqual(first, second)
        self.assertNotIn(ip, first + second)

    async def test_successful_alert_prunes_expired_fingerprints(self):
        sender = AsyncMock(return_value=True)
        security_alerts._last_alert.update({
            "expired": 699.0,
            "recent": 999.0,
        })
        with patch("core.security_alerts.time.monotonic", return_value=1000.0), patch(
            "core.security_alerts._send_alert_email", sender
        ):
            self.assertTrue(await security_alerts.alert_blocked_access(
                "prohibited_endpoint", "192.0.2.50"
            ))
        self.assertNotIn("expired", security_alerts._last_alert)
        self.assertIn("recent", security_alerts._last_alert)
        self.assertEqual(len(security_alerts._last_alert), 2)

    async def test_many_distinct_sources_cannot_grow_alert_cache_unbounded(self):
        limit = security_alerts._MAX_TRACKED_ALERTS
        security_alerts._last_alert.update({
            f"prior:{index}": 800.0 + index / (limit + 1)
            for index in range(limit)
        })
        sender = AsyncMock(return_value=True)
        with patch("core.security_alerts.time.monotonic", return_value=1000.0), patch(
            "core.security_alerts._send_alert_email", sender
        ):
            self.assertTrue(await security_alerts.alert_blocked_access(
                "prohibited_endpoint", "192.0.2.51"
            ))
        self.assertEqual(len(security_alerts._last_alert), limit)
        self.assertNotIn("prior:0", security_alerts._last_alert)
        sender.assert_awaited_once()

    async def test_duplicate_is_suppressed(self):
        sender = AsyncMock(return_value=True)
        with patch("core.security_alerts._send_alert_email", sender):
            await security_alerts.alert_blocked_access("sensitive_response", "192.0.2.20")
            await security_alerts.alert_blocked_access("sensitive_response", "192.0.2.20")
        sender.assert_awaited_once()

    async def test_delivery_failure_is_retryable(self):
        sender = AsyncMock(side_effect=[False, True])
        with patch("core.security_alerts._send_alert_email", sender):
            self.assertFalse(await security_alerts.alert_blocked_access("prohibited_endpoint", "192.0.2.40"))
            self.assertTrue(await security_alerts.alert_blocked_access("prohibited_endpoint", "192.0.2.40"))
        self.assertEqual(sender.await_count, 2)

    async def test_alert_failure_does_not_expose_or_unblock(self):
        with patch("core.security_alerts._send_alert_email", AsyncMock(side_effect=RuntimeError("offline"))):
            self.assertFalse(await security_alerts.alert_blocked_access("prohibited_endpoint", "192.0.2.30"))


if __name__ == "__main__":
    unittest.main()
