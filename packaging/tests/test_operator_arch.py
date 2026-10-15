"""Exercise the actual Mac installer ARCH shell expression with realistic manifests."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "packaging" / "bundle" / "start.sh"


class OperatorArchitectureTests(unittest.TestCase):
    def test_manifest_reader_retains_architecture_letters(self):
        source = INSTALLER.read_text()
        reader = next(line for line in source.splitlines() if line.startswith("required_arch="))
        for architecture in ("arm64", "amd64"):
            for endings in (b"\n", b"\r\n"):
                with self.subTest(architecture=architecture, endings=endings):
                    with tempfile.TemporaryDirectory() as directory:
                        Path(directory, "ARCH").write_bytes(architecture.encode() + endings)
                        result = subprocess.run(
                            ["bash", "-c", reader + "\nprintf '%s' \"$required_arch\""],
                            cwd=directory,
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        self.assertEqual(result.stdout, architecture)


if __name__ == "__main__":
    unittest.main()
