from pathlib import Path
import unittest

SWIFT = (Path(__file__).resolve().parents[1] / "BedeInstallerApp.swift").read_text()

class UnifiedArchitectureSelection(unittest.TestCase):
    def test_both_modes_present(self):
        self.assertIn('case native = "Native macOS"', SWIFT)
        self.assertIn('case containerized = "Containerized"', SWIFT)
        self.assertIn('Picker("Deployment architecture"', SWIFT)
        self.assertIn('@Published var context: InstallContext = .campus', SWIFT)
        self.assertIn('@Published var architecture: DeploymentArchitecture = .native', SWIFT)

    def test_native_fails_closed_without_runtime(self):
        self.assertIn('architecture == .containerized && check.dockerReady', SWIFT)
        self.assertIn('guard architecture == .containerized else {', SWIFT)
        self.assertIn('Native runtime components have not passed integrity, signing and service qualification.', SWIFT)
        self.assertIn('var nativeRuntimeReady: Bool', SWIFT)
        self.assertIn('return false', SWIFT)
        self.assertIn('object["signature_status"] as? String == "verified"', SWIFT)
        self.assertIn('for name in ["bede-api", "bede-inference", "bede-teacher"]', SWIFT)
        self.assertIn('Native campus removal is not available', SWIFT)

    def test_containerized_runtime_preserves_existing_gate(self):
        self.assertIn('check.diskGiB >= 30 && check.memoryGiB >= 16 && validContext', SWIFT)
        self.assertIn('Text("Container engine:', SWIFT)

if __name__ == "__main__":
    unittest.main()
