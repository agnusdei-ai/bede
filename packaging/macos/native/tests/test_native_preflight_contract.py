from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]

class NativePreflightContract(unittest.TestCase):
    def test_manifest_schema_is_fail_closed(self):
        schema = json.loads((ROOT / "NATIVE_RUNTIME_MANIFEST.schema.json").read_text())
        self.assertEqual(schema["properties"]["architecture"]["const"], "arm64")
        self.assertEqual(schema["properties"]["signature_status"]["enum"], ["verified"])
        self.assertEqual(schema["properties"]["pilot_go"]["const"], "HOLD")
        self.assertEqual(set(schema["required"]), {"source_sha", "architecture", "components", "sha256", "signature_status", "pilot_go"})

    def test_native_preflight_does_not_invoke_docker(self):
        source = (ROOT / "NativeRuntimePreflight.swift").read_text()
        self.assertNotIn("docker", source.lower())
        for binary in ("bede-api", "bede-inference", "bede-teacher"):
            self.assertIn(binary, source)
        self.assertIn("missingManifest", source)
        self.assertIn("missingCampusIdentifier", source)

if __name__ == "__main__":
    unittest.main()
