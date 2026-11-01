"""Static guards for the Mac/Windows exact-SHA candidate packaging contract.

These tests are not a substitute for signing, installer or device qualification.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MacWindowsCandidateContract(unittest.TestCase):
    def test_both_native_candidates_share_exact_operator_build(self):
        workflow = (ROOT / ".github/workflows/build-bede-operator.yml").read_text()
        self.assertIn("package-mac-pilot:", workflow)
        self.assertIn("package-windows-standard:", workflow)
        windows = workflow.split("  package-windows-standard:", 1)[1]
        self.assertIn("needs: package", windows)
        self.assertIn("name: bede-standard-linux-amd64-${{ github.sha }}", windows)
        self.assertIn("RELEASE_PROVENANCE.json", windows)
        self.assertIn("BedeRelease.iss", windows)
        self.assertIn("Get-FileHash", windows)
        self.assertIn("Bede-Engineering-Windows-amd64.exe", windows)
        self.assertIn("NOT_FOR_DISTRIBUTION.txt", windows)
        self.assertIn("Get-AuthenticodeSignature", windows)
        self.assertIn("name: bede-windows-engineering-unsigned-amd64-${{ github.sha }}", windows)
        mac = workflow.split("  package-mac-pilot:", 1)[1].split("  package-windows-standard:", 1)[0]
        self.assertIn("bede-standard-linux-arm64-${{ github.sha }}", mac)
        self.assertIn("Bede-Engineering-Mac-arm64.dmg", mac)
        self.assertIn("NOT_FOR_DISTRIBUTION.txt", mac)

    def test_windows_native_exe_uses_sealed_payload_not_git_checkout(self):
        iss = (ROOT / "packaging/windows/BedeRelease.iss").read_text()
        self.assertIn('Source: "release-payload\\*"', iss)
        self.assertIn("Install-Bede.ps1", iss)
        self.assertNotIn("Setup-Bede.ps1", iss)
        script = (ROOT / "packaging/bundle/Install-Bede.ps1").read_text()
        for required in (
            "RELEASE_PROVENANCE.json", "IMAGE_DIGESTS", "WIZARD_IMAGE",
            "Get-Content -LiteralPath", "docker.exe", "pull",
            "tag", "'--pull','never'", "--cacert",
            "BEDE_INSTALL_CONTEXT", "COMPOSE_PROJECT_NAME",
        ):
            self.assertIn(required, script)
        self.assertNotIn("Invoke-WebRequest", script)
        self.assertNotIn("git clone", script)
        self.assertNotIn("git pull", script)
        self.assertNotIn("docker build", script)
        self.assertIn("if ($entries.Count -ne 6)", script)
        self.assertIn("sha256:[0-9a-f]{64}", script)
        self.assertIn("Start-Process 'https://localhost'", script)

    def test_distribution_signing_is_manual_and_fail_closed(self):
        mac = (ROOT / ".github/workflows/macos-trusted-distribution.yml").read_text()
        windows = (ROOT / ".github/workflows/windows-trusted-distribution.yml").read_text()
        self.assertIn("workflow_dispatch:", mac)
        self.assertIn("Developer ID sign and notarize", mac)
        self.assertIn("stapler validate", mac)
        self.assertIn("environment: windows-trusted-distribution", windows)
        self.assertIn("workflow_dispatch:", windows)
        self.assertIn("if: github.ref == 'refs/heads/main'", windows)
        self.assertIn("run.head_sha", windows)
        self.assertIn("run.conclusion", windows)
        self.assertIn("Get-AuthenticodeSignature", windows)
        self.assertIn("sig.Status -ne 'Valid'", windows)
        self.assertIn("Unexpected code signing publisher identity", windows)
        self.assertNotIn("  pull_request:", windows)
        self.assertNotIn("  push:", windows)


if __name__ == "__main__":
    unittest.main()
