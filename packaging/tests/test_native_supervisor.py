import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "macos/native/native-supervisor.py"
spec = importlib.util.spec_from_file_location("native_supervisor", MODULE)
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


class NativeSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.previous_root = supervisor.ROOT
        supervisor.ROOT = self.root
        self.addCleanup(setattr, supervisor, "ROOT", self.previous_root)
        self.campus = self.root / "campus-one"
        self.campus.mkdir()
        (self.campus / "campus.json").write_text(json.dumps({
            "campusID": "campus-one", "architecture": "native-macos"
        }))

    def test_invalid_identifier_and_traversal(self):
        for name in ("../outside", "ab", "bad space", "/tmp/escape"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                supervisor.campus_path(name)

    def test_symlink_campus_refused(self):
        (self.root / "campus-link").symlink_to(self.campus)
        with self.assertRaises(ValueError):
            supervisor.campus_path("campus-link")

    def test_cross_campus_metadata_refused(self):
        with self.assertRaises(ValueError):
            supervisor.record(self.campus, "campus-two")

    def test_stopped_status_does_not_delete_campus(self):
        self.assertEqual(supervisor.stop(self.campus, "campus-one"), {"running": False})
        self.assertTrue((self.campus / "campus.json").exists())

    def test_missing_executable_refused(self):
        with self.assertRaises(ValueError):
            supervisor.start(self.campus, "campus-one", self.root, 18743)
        self.assertFalse((self.campus / "native-service.json").exists())

    def test_occupied_port_refused(self):
        payload = self.root / "payload/bin"
        payload.mkdir(parents=True)
        executable = payload / "bede-native-smoke"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            port = occupied.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, "port unavailable"):
                supervisor.start(self.campus, "campus-one", payload.parent, port)
        self.assertFalse((self.campus / "native-service.json").exists())


if __name__ == "__main__":
    unittest.main()
