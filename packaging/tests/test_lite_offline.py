"""Contract tests for Lite and Offline distribution paths."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LiteOfflineTests(unittest.TestCase):
    def test_launcher_pins_registry_downloads(self):
        script = (ROOT / "packaging/bundle/start.sh").read_text()
        self.assertIn('[[ -f images.tar || -f IMAGE_DIGESTS ]]', script)
        self.assertIn('docker pull "${image}@${digest}"', script)
        self.assertIn('docker load -i images.tar', script)
        self.assertIn('docker tag "${image}@${digest}" "$image"', script)
        self.assertIn('sha256:[0-9a-f]{64}', script)
        self.assertIn('--pull never', script)

    def test_workflow_generates_both_architectures_and_formats(self):
        workflow = (ROOT / ".github/workflows/build-bede-operator.yml").read_text()
        for item in ("arm64", "amd64", "bede-operator-lite-", "bede-operator-", "IMAGE_DIGESTS", "images.tar", "packages: write"):
            self.assertIn(item, workflow)
        self.assertIn('rm -f dist/bede-operator-lite/images.tar', workflow)
        self.assertIn('name: bede-lite-', workflow)
        self.assertIn('name: bede-offline-', workflow)
        self.assertNotIn('dist/bede-operator*.tar.gz', workflow)
        self.assertIn('dist/bede-operator-lite-${{ github.sha }}-${{ matrix.arch }}.tar.gz', workflow)


if __name__ == "__main__":
    unittest.main()
