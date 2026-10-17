import SwiftUI
import Foundation

// Bede macOS installer UI. The setup backend is deliberately fail-closed:
// this shell must never claim installation succeeded until the signed
// payload provisioner and passkey enrollment are integrated and verified.
enum Deployment: String, CaseIterable, Identifiable {
    case same = "Same machine"
    case server = "Dedicated server"
    case client = "Client workstation"
    var id: String { rawValue }
}

struct HostPreflight {
    let architecture: String
    let memoryGiB: Int
    let freeDiskGiB: Int
    let containerReady: Bool
    static func inspect() -> HostPreflight {
        var size = 0
        var count = MemoryLayout<Int>.size
        let memory = sysctlbyname("hw.memsize", &size, &count, nil, 0) == 0 ? size : 0
        let free = (try? FileManager.default.attributesOfFileSystem(forPath: NSHomeDirectory())[.systemFreeSize] as? NSNumber)?.int64Value ?? 0
        let architecture: String
        #if arch(arm64)
        architecture = "arm64"
        #else
        architecture = "amd64"
        #endif
        let docker = Process()
        docker.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        docker.arguments = ["docker", "info", "--format", "{{.Architecture}}"]
        docker.standardOutput = Pipe()
        docker.standardError = Pipe()
        let ready: Bool
        do {
            try docker.run()
            docker.waitUntilExit()
            ready = docker.terminationStatus == 0
        } catch {
            ready = false
        }
        return HostPreflight(
            architecture: architecture,
            memoryGiB: Int(memory / (1024 * 1024 * 1024)),
            freeDiskGiB: Int(free / (1024 * 1024 * 1024)),
            containerReady: ready
        )
    }
}

struct InstallerView: View {
    @State private var deployment: Deployment = .same
    @State private var localInference = true
    @State private var usePasskey = true
    @State private var preflight = HostPreflight.inspect()
    @State private var showDetails = false

    private var eligible: Bool {
        deployment == .client || (preflight.memoryGiB >= 16 && preflight.freeDiskGiB >= 30)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Welcome to Bede").font(.largeTitle).bold()
            Text("Set up a secure learning environment. Recommended settings are selected for this Mac.")
                .foregroundStyle(.secondary)
            Picker("Where will Bede run?", selection: $deployment) {
                ForEach(Deployment.allCases) { option in
                    Text(option.rawValue).tag(option)
                }
            }.pickerStyle(.radioGroup)
            if deployment != .client {
                Toggle("Run AI locally on this machine", isOn: $localInference)
                Text("Local inference is recommended; model selection will be verified against available resources.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Toggle("Enroll administrator using a passkey", isOn: $usePasskey)
                .disabled(true)
            GroupBox("Detected on this Mac") {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Architecture: \(preflight.architecture)")
                    Text("Memory: \(preflight.memoryGiB) GiB")
                    Text("Available disk: \(preflight.freeDiskGiB) GiB")
                    if deployment != .client {
                        Text("Container engine: \(preflight.containerReady ? "Ready" : "Not ready — guided setup required")")
                    } else {
                        Text("Client-only installation does not require a container engine.")
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            if !eligible {
                Text("This Mac does not meet the provisional local-server memory or disk preflight. Client mode remains available.")
                    .foregroundStyle(.red)
            }
            if showDetails {
                Text("Installation is not yet available: signed payload provisioning, prerequisite approval, and passkey enrollment must be integrated and certified.")
                    .foregroundStyle(.orange)
            }
            HStack {
                Button("Refresh checks") { preflight = HostPreflight.inspect() }
                Spacer()
                Button("Continue") { showDetails = true }
                    .disabled(!eligible)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(28)
        .frame(minWidth: 570, minHeight: 560)
    }
}

@main
struct BedeInstallerApp: App {
    var body: some Scene {
        WindowGroup { InstallerView() }
    }
}
