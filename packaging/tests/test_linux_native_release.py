"""Static gates for Linux native Bede packages; not physical-device GO."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[2]

class NativeLinuxReleaseTests(unittest.TestCase):
    def test_native_packages_for_each_architecture(self):
        ci = (ROOT / ".github/workflows/build-bede-operator.yml").read_text()
        part = ci.split("  package-linux-native:", 1)[1]
        for item in ("needs: package", "arch: amd64", "arch: arm64",
                     "name: bede-standard-linux-${{ matrix.arch }}-${{ github.sha }}",
                     "sha256sum -c", "dpkg-deb --field", "rpm -qpl",
                     "bede-linux-native-standard-${{ matrix.arch }}-${{ github.sha }}"):
            self.assertIn(item, part)

    def test_native_desktop_and_provenance_built_without_sources(self):
        build = (ROOT / "packaging/linux/build-native-packages.sh").read_text()
        for item in ("dpkg-deb --build", "rpmbuild -bb",
                     "bede-installer.desktop", "bede-installer",
                     "RELEASE_PROVENANCE.json", "IMAGE_DIGESTS",
                     "NOT_FOR_DISTRIBUTION.txt", "sha256sum",
                     "pilot_go"):
            self.assertIn(item, build)
        self.assertNotIn("git clone", build)
        self.assertNotIn("git pull", build)

    def test_linux_launcher_preserves_per_user_isolation(self):
        source = (ROOT / "packaging/linux/bede-installer").read_text()
        for item in ("/opt/bede/standard", "BEDE_INSTALL_CONTEXT",
                     "BEDE_CAMPUS_ID", "XDG_DATA_HOME", "COMPOSE_PROJECT_NAME",
                     "docker compose version", "data belongs to another SHA",
                     "chmod 700", "exec bash ./start.sh", '"$(id -u)" -ne 0'):
            self.assertIn(item, source)
        self.assertNotIn("git clone", source)
        self.assertNotIn("git pull", source)

if __name__ == "__main__":
    unittest.main()
