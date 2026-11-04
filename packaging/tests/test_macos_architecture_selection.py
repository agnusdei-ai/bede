from pathlib import Path
import unittest

SWIFT = (Path(__file__).resolve().parents[1] / "macos" / "BedeInstallerApp.swift").read_text()

class UnifiedArchitectureSelection(unittest.TestCase):
    def test_modes_declared_but_only_qualified_runtime_offered(self):
        self.assertIn('case native = "Native macOS"', SWIFT)
        self.assertIn('case containerized = "Containerized"', SWIFT)
        self.assertIn('Picker("Runtime (requires a container engine)"', SWIFT)
        self.assertIn('DeploymentArchitecture.allCases.filter { $0 == .containerized || installer.nativeRuntimeReady }', SWIFT)
        self.assertIn('@Published var context: InstallContext = .campus', SWIFT)
        self.assertIn('@Published var architecture: DeploymentArchitecture = .containerized', SWIFT)
        self.assertNotIn('@Published var architecture: DeploymentArchitecture = .native', SWIFT)

    def test_native_fails_closed_without_runtime(self):
        self.assertIn('architecture == .containerized ? check.dockerReady : nativeRuntimeReady', SWIFT)
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
