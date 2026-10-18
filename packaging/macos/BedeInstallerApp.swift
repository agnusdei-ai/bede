import SwiftUI
import AppKit
import Foundation

// This is the only supported Mac setup entry point. The app runs the sealed
// operator runtime. It never reports success before the runtime health check.
enum SetupStage: String, CaseIterable, Identifiable {
    case requirements = "Checking this Mac"
    case files = "Preparing Bede"
    case settings = "Completing setup"
    case services = "Starting Bede"
    case health = "Confirming secure access"

    var id: String { rawValue }
}

struct MacCheck {
    let architecture: String
    let memoryGiB: Int
    let diskGiB: Int
    let dockerReady: Bool

    static func inspect() -> MacCheck {
        var memory: Int64 = 0
        var length = MemoryLayout<Int64>.size
        let result = sysctlbyname("hw.memsize", &memory, &length, nil, 0)
        let freeSpace = (try? FileManager.default.attributesOfFileSystem(
            forPath: NSHomeDirectory())[.systemFreeSize] as? NSNumber)?.int64Value ?? 0
        let cpu: String
        #if arch(arm64)
        cpu = "Apple Silicon"
        #else
        cpu = "Intel"
        #endif
        let docker = Process()
        docker.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        docker.arguments = ["docker", "info", "--format", "{{.Architecture}}"]
        docker.environment = InstallerController.commandEnvironment()
        docker.standardOutput = Pipe()
        docker.standardError = Pipe()
        var working = false
        do {
            try docker.run()
            docker.waitUntilExit()
            working = docker.terminationStatus == 0
        } catch {
            working = false
        }
        return MacCheck(
            architecture: cpu,
            memoryGiB: result == 0 ? Int(memory / 1_073_741_824) : 0,
            diskGiB: Int(freeSpace / 1_073_741_824),
            dockerReady: working
        )
    }
}

@MainActor
final class InstallerController: ObservableObject {
    @Published var current: SetupStage = .requirements
    @Published var finished = Set<SetupStage>()
    @Published var running = false
    @Published var completed = false
    @Published var stopped = false
    @Published var message = "Bede will guide you through the installation."
    @Published var details = false
    @Published var check = MacCheck.inspect()

    private var process: Process?
    private var pending = ""

    nonisolated static func commandEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        let home = NSHomeDirectory()
        env["PATH"] = [
            "/opt/homebrew/bin", "/usr/local/bin", home + "/.docker/bin",
            "/usr/bin", "/bin", "/usr/sbin", "/sbin"
        ].joined(separator: ":")
        env["BEDE_GUI_PROGRESS"] = "1"
        return env
    }

    var prepared: Bool {
        check.dockerReady && check.diskGiB >= 30 && check.memoryGiB >= 16
    }

    var bundleDirectory: URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let payload = resources.appendingPathComponent("bede-operator", isDirectory: true)
        let script = payload.appendingPathComponent("start.sh")
        let manifest = payload.appendingPathComponent("RELEASE")
        return FileManager.default.fileExists(atPath: script.path)
            && FileManager.default.fileExists(atPath: manifest.path) ? payload : nil
    }

    func begin() {
        guard !running else { return }
        check = MacCheck.inspect()
        stopped = false
        completed = false
        finished = []
        current = .requirements
        guard prepared else {
            message = check.dockerReady
                ? "This Mac needs at least 16 GB of memory and 30 GB of free space."
                : "Start your container engine, then choose Check again."
            return
        }
        guard let sealed = bundleDirectory else {
            message = "Installation files are missing. Open the official Bede installer package."
            return
        }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Bede Pilot", isDirectory: true)
        let payload = support.appendingPathComponent("bede-operator", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: payload.appendingPathComponent("RELEASE").path) {
                message = "Preparing the local installation files..."
                let staging = support.appendingPathComponent("bede-operator.pending", isDirectory: true)
                if FileManager.default.fileExists(atPath: staging.path) {
                    try FileManager.default.removeItem(at: staging)
                }
                try FileManager.default.copyItem(at: sealed, to: staging)
                try FileManager.default.moveItem(at: staging, to: payload)
            } else {
                let currentRelease = (try? String(contentsOf: payload.appendingPathComponent("RELEASE"), encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
                let sealedRelease = (try? String(contentsOf: sealed.appendingPathComponent("RELEASE"), encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
                guard currentRelease == sealedRelease else {
                    message = "This Mac has another Bede pilot build. Review the installation before upgrading."
                    return
                }
            }
        } catch {
            message = "Could not prepare the local installation files. Check available disk space."
            return
        }

        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/bash")
        task.arguments = ["./start.sh"]
        task.currentDirectoryURL = payload
        task.environment = Self.commandEnvironment()
        let stdout = Pipe()
        let stderr = Pipe()
        task.standardOutput = stdout
        task.standardError = stderr

        let consume: (FileHandle) -> Void = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            Task { @MainActor [weak self] in
                self?.consumeOutput(data)
            }
        }
        stdout.fileHandleForReading.readabilityHandler = consume
        // Errors are only reported through the script's safe stage diagnostic.
        // Never display raw Docker output or credentials in the installer.
        stderr.fileHandleForReading.readabilityHandler = { handle in
            _ = handle.availableData
        }

        task.terminationHandler = { [weak self] ended in
            stdout.fileHandleForReading.readabilityHandler = nil
            stderr.fileHandleForReading.readabilityHandler = nil
            let code = ended.terminationStatus
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.process = nil
                self.running = false
                if self.stopped || code == 130 {
                    self.message = "Setup was stopped. You can return when you are ready."
                    self.completed = false
                } else if code == 0 {
                    self.finished = Set(SetupStage.allCases)
                    self.completed = true
                    self.message = "Bede is installed. Review the pilot checks before using it."
                } else {
                    self.completed = false
                    self.message = "Setup stopped before Bede was ready. Open the support report for details."
                }
            }
        }
        do {
            try task.run()
            process = task
            running = true
            message = "Checking this Mac..."
        } catch {
            message = "Bede could not start the installer. Please use the official package."
        }
    }

    private func consumeOutput(_ data: Data) {
        pending += String(decoding: data, as: UTF8.self)
        // Bound memory growth if an external tool prints a long line.
        if pending.count > 8192 { pending = String(pending.suffix(4096)) }
        while let cut = pending.firstIndex(of: "\n") {
            let line = String(pending[..<cut])
            pending = String(pending[pending.index(after: cut)...])
            guard line.hasPrefix("BEDE_PROGRESS|") else { continue }
            let fields = line.split(separator: "|", maxSplits: 3, omittingEmptySubsequences: false)
            guard fields.count == 4, let stage = SetupStage(rawValue: String(fields[1])) else { continue }
            if fields[2] == "done" { finished.insert(stage) }
            if fields[2] == "working" { current = stage }
            message = String(fields[3])
        }
    }

    func stop() {
        guard running else { return }
        stopped = true
        message = "Stopping setup..."
        process?.interrupt()
    }

    func refresh() {
        check = MacCheck.inspect()
        message = prepared ? "This Mac is ready." : "Review the requirements below."
    }

    func openSupport() {
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Bede Pilot/bede-operator/bede-support")
        NSWorkspace.shared.open(directory)
    }
}

struct InstallerView: View {
    @StateObject private var installer = InstallerController()
    private let green = Color(red: 0.29, green: 0.38, blue: 0.32)
    private let cream = Color(red: 0.97, green: 0.95, blue: 0.92)

    var body: some View {
        VStack(alignment: .leading, spacing: 19) {
            HStack(alignment: .center, spacing: 16) {
                if let image = Bundle.main.url(forResource: "BedeIcon", withExtension: "png"),
                   let icon = NSImage(contentsOf: image) {
                    Image(nsImage: icon)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 72, height: 72)
                        .clipShape(RoundedRectangle(cornerRadius: 13))
                        .accessibilityLabel("Bede")
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("Welcome to Bede").font(.system(size: 29, weight: .semibold, design: .serif))
                    Text("Prepare Bede for your pilot on this Mac.")
                        .foregroundStyle(.secondary)
                }
            }
            Divider()
            Text(installer.completed ? "Bede is ready" : "Installation")
                .font(.title3.weight(.semibold))
            VStack(alignment: .leading, spacing: 13) {
                ForEach(SetupStage.allCases) { stage in
                    HStack(spacing: 11) {
                        if installer.finished.contains(stage) {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(green)
                        } else if installer.running && installer.current == stage {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "circle").foregroundStyle(.secondary)
                        }
                        Text(stage.rawValue)
                            .foregroundStyle(installer.finished.contains(stage) || installer.current == stage
                                ? .primary : .secondary)
                        Spacer()
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(18)
            .background(.white.opacity(0.80), in: RoundedRectangle(cornerRadius: 14))

            if installer.running {
                ProgressView().progressViewStyle(.linear)
                    .accessibilityLabel("Installation in progress")
            }

            Text(installer.message)
                .foregroundStyle(installer.completed ? green : .secondary)
                .frame(maxWidth: .infinity, alignment: .leading)

            if installer.details || !installer.prepared {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Mac: \(installer.check.architecture)")
                    Text("Memory: \(installer.check.memoryGiB) GB")
                    Text("Free space: \(installer.check.diskGiB) GB")
                    Text("Container engine: \(installer.check.dockerReady ? "Ready" : "Not running")")
                }
                .font(.callout)
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 4)
            HStack {
                Button(installer.details ? "Hide Mac details" : "Mac details") {
                    installer.details.toggle()
                }
                .disabled(installer.running)
                if !installer.prepared && !installer.running {
                    Button("Check again") { installer.refresh() }
                }
                Spacer()
                if installer.running {
                    Button("Stop setup") { installer.stop() }
                } else if installer.completed {
                    Button("Open Bede") {
                        NSWorkspace.shared.open(URL(string: "https://localhost")!)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(green)
                } else {
                    Button("Install Bede") { installer.begin() }
                        .buttonStyle(.borderedProminent)
                        .tint(green)
                        .disabled(!installer.prepared)
                }
                if !installer.running && !installer.completed {
                    Button("Support report") { installer.openSupport() }
                }
            }
        }
        .padding(28)
        .background(cream)
        .frame(width: 620, height: 620)
    }
}

@main
struct BedeInstallerApp: App {
    var body: some Scene {
        WindowGroup("Bede Installer") { InstallerView() }
    }
}
