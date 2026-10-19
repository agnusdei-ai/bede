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

enum DeploymentArchitecture: String, CaseIterable, Identifiable {
    case native = "Native macOS"
    case containerized = "Containerized"
    var id: String { rawValue }
}

// Searches only conventional user install/download folders, never the entire Mac.
// A Finder/Trash approval is required; matching names alone never causes deletion.
enum BedeBinaryHousekeeping {
    static func candidates() -> [URL] {
        let fm = FileManager.default
        let home = fm.homeDirectoryForCurrentUser
        let roots: [(URL, Int)] = [
            (home.appendingPathComponent("Downloads"), 3),
            (home.appendingPathComponent("Desktop"), 4),
            (home.appendingPathComponent("Applications"), 1),
            (URL(fileURLWithPath: "/Applications"), 1)
        ]
        let activeApp = Bundle.main.bundleURL.standardizedFileURL.resolvingSymlinksInPath()
        var found: [URL] = []
        var seen = Set<String>()
        for (root, maxDepth) in roots {
            guard let walker = fm.enumerator(at: root, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey], options: [.skipsHiddenFiles, .skipsPackageDescendants]) else {
                continue
            }
            while let url = walker.nextObject() as? URL {
                let depth = url.pathComponents.count - root.pathComponents.count
                if depth > maxDepth { walker.skipDescendants(); continue }
                let props = try? url.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
                if props?.isSymbolicLink == true { walker.skipDescendants(); continue }
                if url.pathExtension == "app" { walker.skipDescendants() }
                let name = url.lastPathComponent.lowercased()
                let isDmg = url.pathExtension.lowercased() == "dmg" &&
                    (name == "bede-pilot-mac-arm64.dmg" || name == "bede-pilot-mac-amd64.dmg")
                let isApp = url.pathExtension.lowercased() == "app" &&
                    (Bundle(url: url)?.bundleIdentifier == "ai.agnusdei.bede.installer")
                guard isDmg || isApp else { continue }
                if url.standardizedFileURL.resolvingSymlinksInPath() == activeApp { continue }
                let key = url.standardizedFileURL.path
                if seen.insert(key).inserted { found.append(url) }
            }
        }
        return found.sorted { $0.path < $1.path }
    }

    static func moveToTrash(_ files: [URL]) -> (retired: Int, failures: [String]) {
        let fm = FileManager.default
        var retired = 0
        var failures: [String] = []
        for url in files {
            // Revalidate at deletion time: refuse symlinks and any running app.
            let props = try? url.resourceValues(forKeys: [.isSymbolicLinkKey])
            if props?.isSymbolicLink == true || url.standardizedFileURL.resolvingSymlinksInPath() == Bundle.main.bundleURL.standardizedFileURL.resolvingSymlinksInPath() {
                failures.append("Skipped protected installer: \(url.lastPathComponent)")
                continue
            }
            let isApp = url.pathExtension.lowercased() == "app" && Bundle(url: url)?.bundleIdentifier == "ai.agnusdei.bede.installer"
            let isDmg = ["bede-pilot-mac-arm64.dmg", "bede-pilot-mac-amd64.dmg"].contains(url.lastPathComponent.lowercased())
            guard isApp || isDmg else { continue }
            do {
                var result: NSURL?
                try fm.trashItem(at: url, resultingItemURL: &result)
                retired += 1
            } catch {
                failures.append("Could not move \(url.lastPathComponent) to Trash.")
            }
        }
        return (retired, failures)
    }
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
    @Published var oldInstallers: [URL] = []
    @Published var completed = false
    @Published var browserTrustReady = false
    @Published var stopped = false
    @Published var message = "Bede will guide you through the installation."
    @Published var details = false
    // Report completed checkpoints, not estimated transfer bytes.
    var verifiedPercent: Int { finished.count * 100 / SetupStage.allCases.count }
    var pullingImages: Bool { running && current == .files && !finished.contains(.files) }
    @Published var architecture: DeploymentArchitecture = .native
    @Published var context: InstallContext = .campus
    @Published var campusID = "bede-mac-pilot-2026"
    @Published var check = MacCheck(architecture: "Checking", memoryGiB: 0, diskGiB: 0, dockerReady: false)
    @Published var checkingMac = false

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
        architecture == .containerized && check.dockerReady && check.diskGiB >= 30 && check.memoryGiB >= 16 && validContext
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
        guard architecture == .containerized else {
            removalError = "Native campus removal is not available until the native runtime is qualified."
            return
        }
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

    func scanOldInstallers() {
        guard !running && !removing else { return }
        oldInstallers = BedeBinaryHousekeeping.candidates()
    }

    func retireOldInstallers() {
        guard !running && !removing else { return }
        let selected = oldInstallers
        let result = BedeBinaryHousekeeping.moveToTrash(selected)
        oldInstallers = BedeBinaryHousekeeping.candidates()
        if !result.failures.isEmpty {
            removalError = result.failures.joined(separator: "\n")
            message = "Some previous installer copies require attention."
        } else {
            removalError = nil
            message = "\(result.retired) previous installer copy/copies moved to Trash."
        }
    }

    func reconcileInstallationState() {
        guard !running && !removing && !checkingMac else { return }
        checkingMac = true
        // File enumeration and Docker subprocesses may block or fail during
        // the first Gatekeeper-authorized launch. Keep both off SwiftUI's main
        // actor, and avoid reentrant refreshes on window activation.
        Task.detached(priority: .userInitiated) {
            let inspected = MacCheck.inspect()
            let candidates = BedeBinaryHousekeeping.candidates()
            await MainActor.run { [weak self] in
                guard let self else { return }
                self.check = inspected
                self.oldInstallers = candidates
                self.checkingMac = false
                if !self.installed {
                    self.completed = false
                    self.finished = []
                    self.current = .requirements
                    self.removalError = nil
                    self.message = "Bede is not installed for this location. You can install it now."
                } else if self.completed && !inspected.dockerReady {
                    self.completed = false
                    self.finished = []
                    self.message = "Bede is installed, but Docker is not running. Start Docker and check again."
                }
            }
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
        guard architecture == .containerized else {
            message = "Native macOS installation is not yet available. No changes were made to this Mac."
            return
        }
        guard !running && !checkingMac else { return }
        stopped = false
        completed = false
        browserTrustReady = false
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
                    self.browserTrustReady = false
                    self.message = "Bede services started. Checking macOS HTTPS trust before opening the browser."
                    self.verifyBrowserTrust()
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

    // Default system trust evaluation: no custom CA bypass and no URLSession
    // challenge delegate. An independently verified service certificate is
    // insufficient until macOS trusts it for browser access.
    func verifyBrowserTrust() {
        guard installed && !running && !removing else { return }
        let session = URLSession(configuration: .ephemeral)
        var request = URLRequest(url: URL(string: "https://localhost/api/health")!)
        request.timeoutInterval = 7
        session.dataTask(with: request) { [weak self] _, response, error in
            let trusted = error == nil && (response as? HTTPURLResponse)?.statusCode == 200
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.browserTrustReady = trusted
                self.message = trusted
                    ? "Secure access is verified by macOS. You can open Bede."
                    : "Bede services are installed, but macOS has not trusted the Bede HTTPS certificate. Review the certificate in Keychain Access, approve it explicitly, then check again."
            }
            session.invalidateAndCancel()
        }.resume()
    }

    func revealCertificate() {
        let certificate = installationDirectory.appendingPathComponent("bede-operator/bede-root-ca.crt")
        guard FileManager.default.fileExists(atPath: certificate.path) else {
            message = "The local certificate is not available yet. Complete service setup before approving trust."
            return
        }
        NSWorkspace.shared.activateFileViewerSelecting([certificate])
        message = "Open the Bede root CA in Keychain Access. After reviewing its fingerprint and approving its trust settings, choose Check secure access."
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
    @Environment(\.scenePhase) private var scenePhase
    @State private var confirmRemoval = false
    @State private var confirmHousekeeping = false
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
            Picker("Deployment architecture", selection: $installer.architecture) {
                ForEach(DeploymentArchitecture.allCases) { item in
                    Text(item.rawValue).tag(item)
                }
            }.pickerStyle(.segmented).disabled(installer.running || installer.completed)
            if installer.architecture == .native {
                Text("Native runtime is pending qualification; installation is unavailable until verified.")
                    .font(.caption).foregroundStyle(.secondary)
            }
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
        Text(installer.completed && installer.browserTrustReady ? "Bede is ready" : "Installation")
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
        if installer.running || installer.completed {
            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text("Setup checkpoints")
                    Spacer()
                    Text("\(installer.verifiedPercent)% complete").monospacedDigit()
                }
                .font(.caption)
                ProgressView(value: Double(installer.verifiedPercent), total: 100)
                    .progressViewStyle(.linear)
                    .accessibilityLabel("Verified setup checkpoints")
                    .accessibilityValue("\(installer.verifiedPercent) percent")
                if installer.pullingImages {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("Downloading verified images — transfer percentage unavailable")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } else if installer.removing {
            ProgressView().progressViewStyle(.linear)
                .accessibilityLabel("Bede removal in progress")
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
                if installer.architecture == .containerized {
                    Text("Container engine: \(installer.check.dockerReady ? "Ready" : "Not running")")
                } else {
                    Text("Native runtime: Not yet qualified")
                }
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
            if !installer.running && !installer.removing {
                Button("Clean Up Installer Files") {
                    installer.scanOldInstallers()
                    if !installer.oldInstallers.isEmpty { confirmHousekeeping = true }
                    else { installer.message = "No older Bede installer files found." }
                }
            }
            if installer.installed && !installer.running && !installer.removing {
                Button("Remove Bede", role: .destructive) { confirmRemoval = true }
            }
            if installer.removing {
                Text("Removing…").foregroundStyle(.secondary)
            } else if installer.running {
                Button("Stop setup") { installer.stop() }
            } else if installer.completed {
                if installer.browserTrustReady {
                    Button("Open Bede") {
                        NSWorkspace.shared.open(URL(string: "https://localhost")!)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(green)
                } else {
                    Button("Review certificate") { installer.revealCertificate() }
                    Button("Check secure access") { installer.verifyBrowserTrust() }
                        .buttonStyle(.borderedProminent)
                        .tint(green)
                }
            } else {
                Button("Install Bede") { installer.begin() }
                    .buttonStyle(.borderedProminent)
                    .tint(green)
                    .disabled(!installer.prepared || installer.removing || installer.checkingMac)
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
        .alert("Previous Bede installers found", isPresented: $confirmHousekeeping) {
            Button("Keep copies", role: .cancel) { }
            Button("Move copies to Trash") { installer.retireOldInstallers() }
        } message: {
            Text("\(installer.oldInstallers.count) older Bede installer file(s) found in Downloads, Desktop, or Applications. Only matching Bede installer apps and DMGs will be retired; this running app and Bede's installed data are preserved.\n\n" + installer.oldInstallers.prefix(8).map(\.path).joined(separator: "\n"))
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
