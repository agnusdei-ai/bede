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

enum InstallContext: String, CaseIterable, Identifiable {
    case campus = "Campus"
    case homeschool = "Homeschool"
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
    @Published var removing = false
    @Published var removalError: String? = nil
    @Published var completed = false
    @Published var stopped = false
    @Published var message = "Bede will guide you through the installation."
    @Published var details = false
    @Published var context: InstallContext = .campus
    @Published var campusID = "bede-mac-pilot-2026"
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

    var validContext: Bool {
        if context == .homeschool { return true }
        return campusID.range(of: "^[a-z0-9][a-z0-9_-]{2,63}$", options: .regularExpression) != nil
    }

    var prepared: Bool {
        check.dockerReady && check.diskGiB >= 30 && check.memoryGiB >= 16 && validContext
    }

    private var installationDirectory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Bede", isDirectory: true)
        if context == .campus {
            return base.appendingPathComponent("Campus", isDirectory: true)
                .appendingPathComponent(campusID, isDirectory: true)
        }
        return base.appendingPathComponent("Homeschool", isDirectory: true)
            .appendingPathComponent("local", isDirectory: true)
    }

    var installed: Bool {
        FileManager.default.fileExists(atPath: installationDirectory.appendingPathComponent("bede-operator/RELEASE").path)
    }

    func removeInstallation() {
        guard !running && !removing && installed && validContext else { return }
        guard let script = Bundle.main.resourceURL?.appendingPathComponent("BedeUninstall.sh"),
              FileManager.default.fileExists(atPath: script.path) else {
            removalError = "Removal tools are missing from this installer. Please use an updated Bede installer."
            return
        }
        removalError = nil
        removing = true
        message = "Removing Bede services and their saved data..."
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/bash")
        task.arguments = [script.path, context == .campus ? "campus" : "homeschool", context == .campus ? campusID : ""]
        task.environment = Self.commandEnvironment()
        let output = Pipe()
        let errors = Pipe()
        task.standardOutput = output
        task.standardError = errors
        task.terminationHandler = { [weak self] ended in
            let diagnostic = String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.removing = false
                self.completed = false
                self.finished = []
                self.current = .requirements
                if ended.terminationStatus == 0 {
                    self.message = "Bede was removed from this Mac. You can install it again."
                } else {
                    self.message = "Bede could not be completely removed."
                    self.removalError = diagnostic.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        ? "Removal stopped. Check Docker Desktop and retry." :
                        String(diagnostic.suffix(1400))
                }
            }
        }
        do {
            try task.run()
        } catch {
            removing = false
            removalError = "Could not start removal. Please verify the installer is complete."
        }
    }

    func reconcileInstallationState() {
        guard !running && !removing else { return }
        check = MacCheck.inspect()
        // A previously successful UI session is not evidence that the
        // containers or data still exist after external Docker cleanup.
        if !installed {
            completed = false
            finished = []
            current = .requirements
            removalError = nil
            message = "Bede is not installed for this location. You can install it now."
        } else if completed && !check.dockerReady {
            completed = false
            finished = []
            message = "Bede is installed, but Docker is not running. Start Docker and check again."
        }
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
            if !validContext { message = "Enter the campus ID shown in your pilot license."; return }
            message = check.dockerReady
                ? "This Mac needs at least 16 GB of memory and 30 GB of free space."
                : "Start your container engine, then choose Check again."
            return
        }
        guard let sealed = bundleDirectory else {
            message = "Installation files are missing. Open the official Bede installer package."
            return
        }
        let support = installationDirectory
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
        var environment = Self.commandEnvironment()
        environment["BEDE_INSTALL_CONTEXT"] = context == .campus ? "campus" : "homeschool"
        if context == .campus { environment["BEDE_CAMPUS_ID"] = campusID }
        task.environment = environment
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
        reconcileInstallationState()
        if installed { message = "Bede installation files detected. Verify the running service before using Bede." }
    }

    func openSupport() {
        let directory = installationDirectory.appendingPathComponent("bede-operator/bede-support")
        NSWorkspace.shared.open(directory)
    }
}

struct InstallerView: View {
    @StateObject private var installer = InstallerController()
    @Environment(\\.scenePhase) private var scenePhase
    @State private var confirmRemoval = false
    private let green = Color(red: 0.29, green: 0.38, blue: 0.32)
    private let cream = Color(red: 0.97, green: 0.95, blue: 0.92)

    @ViewBuilder private var headerSection: some View {
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
    }

    private var contextSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Install for").font(.headline)
            Picker("Install for", selection: $installer.context) {
                ForEach(InstallContext.allCases) { item in
                    Text(item.rawValue).tag(item)
                }
            }.pickerStyle(.segmented).disabled(installer.running || installer.completed)
            if installer.context == .campus {
                TextField("Campus ID", text: $installer.campusID)
                    .textFieldStyle(.roundedBorder)
                    .disabled(installer.running || installer.completed)
                Text("Use the campus ID printed with your pilot license.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder private var stagesSection: some View {
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
    }

    @ViewBuilder private var statusSection: some View {
        if installer.running || installer.removing {
            ProgressView().progressViewStyle(.linear)
                .accessibilityLabel("Installation in progress")
        }

        Text(installer.message)
            .foregroundStyle(installer.completed ? green : .secondary)
            .frame(maxWidth: .infinity, alignment: .leading)

        if let error = installer.removalError {
            VStack(alignment: .leading, spacing: 4) {
                Text("Removal needs attention").font(.headline)
                Text(error).font(.caption).textSelection(.enabled)
            }
            .foregroundStyle(.red)
        }

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
    }

    private var actionsSection: some View {
        HStack {
            Button(installer.details ? "Hide Mac details" : "Mac details") {
                installer.details.toggle()
            }
            .disabled(installer.running || installer.removing)
            if !installer.prepared && !installer.running && !installer.removing {
                Button("Check again") { installer.refresh() }
            }
            Spacer()
            if installer.installed && !installer.running && !installer.removing {
                Button("Remove Bede", role: .destructive) { confirmRemoval = true }
            }
            if installer.removing {
                Text("Removing…").foregroundStyle(.secondary)
            } else if installer.running {
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
                    .disabled(!installer.prepared || installer.removing)
            }
            if !installer.running && !installer.removing && !installer.completed {
                Button("Support report") { installer.openSupport() }
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 19) {
            headerSection
            contextSection
            stagesSection
            statusSection
            Spacer(minLength: 4)
            actionsSection
        }
        .padding(28)
        .background(cream)
        .frame(width: 620, height: 700)
        .onAppear { installer.reconcileInstallationState() }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active { installer.reconcileInstallationState() }
        }
        .alert("Permanently remove Bede?", isPresented: $confirmRemoval) {
            Button("Cancel", role: .cancel) { }
            Button("Remove Bede and its data", role: .destructive) { installer.removeInstallation() }
        } message: {
            Text("This permanently removes the selected Bede installation, its local learning records, containers, and certificates associated with this installation. Other Docker apps and your separately stored installer and license are preserved.")
        }
    }
}

@main
struct BedeInstallerApp: App {
    var body: some Scene {
        WindowGroup("Bede Installer") { InstallerView() }
    }
}
