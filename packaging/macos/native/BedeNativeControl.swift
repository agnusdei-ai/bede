import Foundation
import Darwin

// Native macOS control-plane utility. No Docker, shell invocation, or network
// listener. This does NOT implement the tutor API, inference, or teacher UI.
enum NativeError: Error, CustomStringConvertible {
    case usage, invalidCampus, alreadyExists, missingCampus, invalidState
    var description: String {
        switch self {
        case .usage: return "usage: bede-native-control provision|status|diagnose <campus-id>"
        case .invalidCampus: return "Invalid campus identifier"
        case .alreadyExists: return "Campus already exists; refusing to overwrite"
        case .missingCampus: return "Campus not provisioned"
        case .invalidState: return "Campus metadata failed validation"
        }
    }
}

struct CampusRecord: Codable {
    let schema: Int
    let campusID: String
    let architecture: String
    let pilotGO: String
    let createdAt: String
}

struct NativeControl {
    let base: URL
    let manager = FileManager.default
    init(base: URL? = nil) throws {
        let home = manager.homeDirectoryForCurrentUser
        self.base = base ?? home.appendingPathComponent("Library/Application Support/Bede/Native/Campus", isDirectory: true)
    }
    func directory(_ id: String) throws -> URL {
        guard id.range(of: "^[a-z0-9][a-z0-9_-]{2,63}$", options: .regularExpression) != nil else {
            throw NativeError.invalidCampus
        }
        return base.appendingPathComponent(id, isDirectory: true)
    }
    func provision(_ id: String) throws -> CampusRecord {
        let target = try directory(id)
        guard !manager.fileExists(atPath: target.path) else { throw NativeError.alreadyExists }
        try manager.createDirectory(at: base, withIntermediateDirectories: true)
        let pending = base.appendingPathComponent(".pending-\(UUID().uuidString)", isDirectory: true)
        try manager.createDirectory(at: pending, withIntermediateDirectories: false)
        do {
            let record = CampusRecord(schema: 1, campusID: id, architecture: "native-macos", pilotGO: "HOLD",
                                      createdAt: ISO8601DateFormatter().string(from: Date()))
            let data = try JSONEncoder().encode(record)
            try data.write(to: pending.appendingPathComponent("campus.json"), options: [.atomic, .completeFileProtectionUnlessOpen])
            try manager.moveItem(at: pending, to: target)
            return record
        } catch {
            try? manager.removeItem(at: pending)
            throw error
        }
    }
    func status(_ id: String) throws -> CampusRecord {
        let target = try directory(id)
        let metadata = target.appendingPathComponent("campus.json")
        guard manager.fileExists(atPath: metadata.path) else { throw NativeError.missingCampus }
        let record = try JSONDecoder().decode(CampusRecord.self, from: Data(contentsOf: metadata))
        guard record.schema == 1, record.campusID == id,
              record.architecture == "native-macos", record.pilotGO == "HOLD" else { throw NativeError.invalidState }
        return record
    }
}

@main
struct Main {
    static func main() {
        do {
            let args = Array(CommandLine.arguments.dropFirst())
            guard args.count == 2 else { throw NativeError.usage }
            let control = try NativeControl(base: ProcessInfo.processInfo.environment["BEDE_NATIVE_TEST_ROOT"].map {
                URL(fileURLWithPath: $0, isDirectory: true)
            })
            let record: CampusRecord
            switch args[0] {
            case "provision": record = try control.provision(args[1])
            case "status", "diagnose": record = try control.status(args[1])
            default: throw NativeError.usage
            }
            let encoded = try JSONEncoder().encode(record)
            print(String(decoding: encoded, as: UTF8.self))
        } catch {
            fputs("BEDE_NATIVE_ERROR: \(error)\n", stderr)
            exit(1)
        }
    }
}
