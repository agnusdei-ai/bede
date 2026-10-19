import Foundation
import Darwin

/// Fail-closed readiness gate for a truly native macOS runtime.
/// This intentionally does not launch the legacy Docker-backed operator payload.
struct NativeRuntimePreflight {
    enum Failure: Error, CustomStringConvertible {
        case unsupportedArchitecture
        case missingExecutable(String)
        case invalidExecutable(String)
        case missingManifest
        case missingCampusIdentifier
        var description: String {
            switch self {
            case .unsupportedArchitecture: return "Native Bede requires Apple Silicon."
            case .missingExecutable(let name): return "Missing native component: \(name)"
            case .invalidExecutable(let name): return "Invalid native executable: \(name)"
            case .missingManifest: return "Missing signed native runtime manifest."
            case .missingCampusIdentifier: return "A valid campus identifier is required."
            }
        }
    }

    static func validate(root: URL, campusID: String, architecture: String) throws {
        guard architecture == "arm64" else { throw Failure.unsupportedArchitecture }
        guard campusID.range(of: "^[a-z0-9][a-z0-9_-]{2,63}$", options: .regularExpression) != nil else {
            throw Failure.missingCampusIdentifier
        }
        guard FileManager.default.fileExists(atPath: root.appendingPathComponent("NATIVE_RUNTIME_MANIFEST.json").path) else {
            throw Failure.missingManifest
        }
        for name in ["bede-api", "bede-inference", "bede-teacher"] {
            let path = root.appendingPathComponent("bin/\(name)")
            guard FileManager.default.fileExists(atPath: path.path) else { throw Failure.missingExecutable(name) }
            guard FileManager.default.isExecutableFile(atPath: path.path) else { throw Failure.invalidExecutable(name) }
        }
    }
}
