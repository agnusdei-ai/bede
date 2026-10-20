import Foundation
import Network
import Darwin

// Local-only synthetic service for native installer qualification.
// NOT the production Bede tutor API, identity provider, or inference engine.
@main
struct NativeSmokeService {
    static func main() throws {
        let env = ProcessInfo.processInfo.environment
        guard env["BEDE_SYNTHETIC_ONLY"] == "1" else {
            fputs("BEDE_NATIVE_ERROR: synthetic mode is required; real learner data is prohibited\n", stderr)
            exit(2)
        }
        let port = UInt16(env["BEDE_NATIVE_PORT"] ?? "0") ?? 0
        guard port > 0, let endpoint = NWEndpoint.Port(rawValue: port) else {
            fputs("BEDE_NATIVE_ERROR: specify a nonzero local port\n", stderr)
            exit(2)
        }
        let listener = try NWListener(using: .tcp, on: endpoint)
        listener.service = nil
        listener.newConnectionHandler = { connection in
            connection.start(queue: .global(qos: .utility))
            connection.receive(minimumIncompleteLength: 1, maximumLength: 4096) { data, _, _, _ in
                let request = String(decoding: data ?? Data(), as: UTF8.self)
                let firstLine = request.components(separatedBy: "\r\n").first ?? ""
                let path = firstLine.split(separator: " ").dropFirst().first.map(String.init) ?? ""
                let (status, type, body): (String, String, String)
                switch (firstLine.hasPrefix("GET "), path) {
                case (true, "/health"):
                    status = "200 OK"; type = "application/json"
                    body = #"{"status":"synthetic-only","pilotGO":"HOLD","native":true}"#
                case (true, "/"):
                    status = "200 OK"; type = "text/html; charset=utf-8"
                    body = "<!doctype html><html><head><meta charset=\"utf-8\"><title>Bede native qualification</title></head><body><main><h1>Bede native qualification</h1><p>Local synthetic diagnostic only. Teacher login and inference are not enabled.</p></main></body></html>"
                default:
                    status = "404 Not Found"; type = "application/json"
                    body = #"{"error":"not_available","pilotGO":"HOLD"}"#
                }
                let response = "HTTP/1.1 \(status)\r\nContent-Type: \(type)\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src 'none'\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n\(body)"
                connection.send(content: Data(response.utf8), completion: .contentProcessed { _ in connection.cancel() })
                let timestamp = ISO8601DateFormatter().string(from: Date())
                fputs("\(timestamp) native-smoke path=\(path.prefix(64)) status=\(status)\n", stderr)
            }
        }
        listener.stateUpdateHandler = { state in
            if case .failed(let error) = state {
                fputs("BEDE_NATIVE_ERROR: listener failed: \(error)\n", stderr)
                exit(1)
            }
        }
        listener.start(queue: .global(qos: .utility))
        fputs("BEDE_NATIVE_SMOKE_STARTED port=\(port) pilotGO=HOLD\n", stderr)
        dispatchMain()
    }
}
