"""Tests for the standalone local-first operator wizard LAN configuration."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("bede_setup_wizard", ROOT / "scripts/setup_wizard/wizard.py")
wizard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wizard)


def fields(**kwargs):
    f = {
        "db_choice": "local",
        "provider": "openai",
        "openai_key": "synthetic-do-not-send",
        "parent_password": "synthetic-strong-test-passphrase",
        "child_pin": "805274199",
        "license_key": "synthetic-license-not-valid",
    }
    return {**f, **kwargs}


class WizardLanTests(unittest.TestCase):
    def test_default_install_does_not_expose_lan(self):
        env = wizard.build_env_file(fields())
        self.assertIn("BEDE_LAN_ENABLED=false\n", env)
        self.assertNotIn("BEDE_LAN_BIND_IP", env)
        self.assertIn("WEBAUTHN_RP_ID=localhost\n", env)
        self.assertIn("WEBAUTHN_ORIGIN=https://localhost\n", env)

    def test_private_mac_mini_lan_uses_exact_dns_host_for_passkeys(self):
        cfg = fields(lan_mode="yes", lan_ip="192.168.8.24", lan_host="bede-pilot.school.org")
        self.assertEqual(wizard.validate_lan_fields(cfg), "")
        env = wizard.build_env_file(cfg)
        self.assertIn("BEDE_LAN_ENABLED=true\nBEDE_LAN_BIND_IP=192.168.8.24\n", env)
        self.assertIn("WEBAUTHN_RP_ID=bede-pilot.school.org\n", env)
        self.assertIn("WEBAUTHN_ORIGIN=https://bede-pilot.school.org\n", env)
        self.assertIn("https://bede-pilot.school.org,http://ui:80", env)
        self.assertIn("https://bede-pilot.school.org", wizard.render_success(cfg))

    def test_invalid_lan_addresses_and_origins_fail_closed(self):
        for cfg in (
            ("127.0.0.1", "bede.school.org"),
            ("0.0.0.0", "bede.school.org"),
            ("fe80::1", "bede.school.org"),
            ("8.8.8.8", "bede.school.org"),
            ("192.168.8.24", "localhost"),
            ("192.168.8.24", "bede.local"),
            ("192.168.8.24", "https://bede.school.org"),
            ("192.168.8.24", "bad.example"),
        ):
            with self.subTest(cfg=cfg):
                self.assertNotEqual(wizard.validate_lan_fields(
                    fields(lan_mode="yes", lan_ip=cfg[0], lan_host=cfg[1])
                ), "")

    def test_form_makes_private_network_a_separate_opt_in(self):
        page = wizard.render_form()
        self.assertIn('name="lan_mode"', page)
        self.assertIn('onchange="toggleLan(this.checked)"', page)
        self.assertIn('id="lan_settings" style="display:none"', page)


if __name__ == "__main__":
    unittest.main()
