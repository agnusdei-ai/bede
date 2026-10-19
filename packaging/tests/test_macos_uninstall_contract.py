"""Hermetic Bede Mac removal contract: no Docker daemon or user files touched."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "macos" / "uninstall.sh"

DOCKER = """#!/usr/bin/env bash
set -e
echo "$*" >> "$BEDE_MOCK_LOG"
if [[ "${1:-}" = info ]]; then
    [[ "${BEDE_MOCK_DOCKER_DOWN:-0}" != 1 ]]
elif [[ "${1:-}" = compose ]]; then
    [[ "${BEDE_MOCK_COMPOSE_FAIL:-0}" != 1 ]]
elif [[ "${1:-}" = ps || "${1:-}" = volume ]]; then
    if [[ "${BEDE_MOCK_RESIDUAL:-0}" = 1 ]]; then echo "still-running"; fi
fi
"""

class RemovalContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        docker = self.bin / "docker"
        docker.write_text(DOCKER)
        docker.chmod(0o755)
        self.log = self.root / "docker.log"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            "BEDE_MOCK_LOG": str(self.log),
        }
        self.outside = self.root / "never-delete.txt"
        self.outside.write_text("preserve")

    def install(self, context="campus", campus="campus_test"):
        if context == "campus":
            base = self.home / "Library/Application Support/Bede/Campus" / campus
        else:
            base = self.home / "Library/Application Support/Bede/Homeschool/local"
        operator = base / "bede-operator"
        operator.mkdir(parents=True)
        for file in ("RELEASE", "compose.yaml", ".env"):
            (operator / file).write_text("pilot")
        return base, operator

    def invoke(self, *args, **env):
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env={**self.env, **{k: str(v) for k, v in env.items()}},
            capture_output=True,
            text=True,
        )

    def assertOutsidePreserved(self):
        self.assertEqual(self.outside.read_text(), "preserve")

    def test_campus_removal_scoped(self):
        base, _ = self.install()
        other, _ = self.install(campus="another_campus")
        r = self.invoke("campus", "campus_test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(base.exists())
        self.assertTrue(other.exists())
        self.assertOutsidePreserved()
        self.assertIn("bede_campus_campus_test", self.log.read_text())

    def test_homeschool_removal_scoped(self):
        base, _ = self.install("homeschool")
        r = self.invoke("homeschool")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(base.exists())
        self.assertIn("bede_homeschool_local", self.log.read_text())
        self.assertOutsidePreserved()

    def test_reject_invalid_context_and_ids(self):
        for args in [("campus", "../escape"), ("campus", "UPPER"), ("campus", "x"), ("school", "campus_test"), ("homeschool", "campus_test")]:
            with self.subTest(args=args):
                self.assertNotEqual(self.invoke(*args).returncode, 0)
        self.assertOutsidePreserved()

    def test_missing_metadata_refuses_removal(self):
        base, operator = self.install()
        (operator / "RELEASE").unlink()
        self.assertNotEqual(self.invoke("campus", "campus_test").returncode, 0)
        self.assertTrue(base.exists())
        self.assertOutsidePreserved()

    def test_stopped_docker_refuses_removal(self):
        base, _ = self.install()
        self.assertNotEqual(self.invoke("campus", "campus_test", BEDE_MOCK_DOCKER_DOWN=1).returncode, 0)
        self.assertTrue(base.exists())

    def test_compose_failure_preserves_files(self):
        base, _ = self.install()
        self.assertNotEqual(self.invoke("campus", "campus_test", BEDE_MOCK_COMPOSE_FAIL=1).returncode, 0)
        self.assertTrue(base.exists())

    def test_residual_containers_preserve_files(self):
        base, _ = self.install()
        self.assertNotEqual(self.invoke("campus", "campus_test", BEDE_MOCK_RESIDUAL=1).returncode, 0)
        self.assertTrue(base.exists())

    def test_symlink_content_refuses_final_deletion(self):
        base, operator = self.install()
        (operator / "linked").symlink_to(self.outside)
        self.assertNotEqual(self.invoke("campus", "campus_test").returncode, 0)
        self.assertTrue(base.exists())
        self.assertOutsidePreserved()

    def test_lan_configuration_requires_overlay(self):
        base, operator = self.install()
        (operator / ".env").write_text("BEDE_LAN_ENABLED=true\n")
        self.assertNotEqual(self.invoke("campus", "campus_test").returncode, 0)
        self.assertTrue(base.exists())
        (operator / "compose.lan.yaml").write_text("services: {}\n")
        self.assertEqual(self.invoke("campus", "campus_test").returncode, 0)
        self.assertFalse(base.exists())


if __name__ == "__main__":
    unittest.main()
