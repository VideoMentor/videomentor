import Foundation
import os
import VideoMentorCore

let log = Logger(subsystem: "org.videomentor.mac", category: "app")

enum EngineState: Equatable {
    case starting
    case running(external: Bool)
    case restarting(in: Int)
    case stopped(reason: String)
}

/// Runs `vm serve` as a child process, or adopts an engine that is already running.
/// Never logs the pairing code.
@MainActor
final class Engine: ObservableObject {
    @Published private(set) var state: EngineState = .stopped(reason: "Not started")
    @Published private(set) var info: LaunchInfo?
    private(set) var client: StatusClient?

    /// Where `vm install` puts the command.
    static let vm = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/vm")
    /// An engine that stays up this long resets the backoff to 1 s.
    static let healthyUptime: TimeInterval = 5 * 60
    static let killAfter: Duration = .seconds(5)

    private var process: Process?
    private var startedAt: Date?
    private var backoff = Backoff()
    private var stopping = false
    private var booting = false
    private var reprobing = false
    private var restartTask: Task<Void, Never>?
    private var readyTask: Task<Void, Never>?
    private var killTask: Task<Void, Never>?
    private var onStopped: (() -> Void)?

    /// The address to call: an engine listening on every interface still answers on 127.0.0.1.
    static func reachableHost(_ host: String) -> String {
        ["", "0.0.0.0", "::", "*"].contains(host) ? "127.0.0.1" : host
    }

    /// True while a child that this app started is alive. Adopted engines are never ours to stop.
    var ownsChild: Bool { process?.isRunning == true }

    func start() {
        guard !booting, process == nil else { return }
        stopping = false
        booting = true
        restartTask?.cancel()
        state = .starting
        Task {
            defer { booting = false }
            await launch()
        }
    }

    /// Reads `vm launch-info` again (off the main actor: it blocks on a pipe) and rebuilds the
    /// client, so a new pairing code is picked up. Returns false if it could not be read.
    @discardableResult
    func reloadLaunchInfo() async -> Bool {
        let vm = Self.vm
        do {
            let loaded = try await Task.detached { try LaunchInfo.load(vm: vm) }.value
            info = loaded
            client = StatusClient(port: loaded.port, pairCode: loaded.pairCode, host: Self.reachableHost(loaded.host))
            return true
        } catch {
            log.error("vm launch-info failed: \(error.localizedDescription, privacy: .public)")
            return false
        }
    }

    /// Checks the port, then adopts, reports a conflict, or spawns.
    /// Every start and restart reads launch info fresh, so the probe never uses an old code.
    private func launch() async {
        guard !stopping, process == nil else { return }
        guard await reloadLaunchInfo() else {
            state = .stopped(reason: "Can't find the engine. Run vm install, then open the app again.")
            return
        }
        guard !stopping, process == nil, let info, let client else { return }
        let result: Result<EngineStatus, Error>
        do { result = .success(try await client.status()) } catch { result = .failure(error) }
        guard !stopping, process == nil else { return }
        switch PortProbe.classify(result) {
        case .ours:
            log.info("Port \(info.port) already runs VideoMentor; using it")
            state = .running(external: true)
        case .otherApp:
            log.error("Port \(info.port) answers but refuses the pairing code")
            state = .stopped(reason: "Port \(info.port) is used by another app")
        case .free:
            spawn(info)
        }
    }

    private func spawn(_ info: LaunchInfo) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: info.program)
        p.arguments = info.args
        // The launch-info environment wins; HOME, USER and the like come from the app.
        p.environment = ProcessInfo.processInfo.environment.merging(info.env) { _, new in new }
        p.standardInput = FileHandle.nullDevice
        let logHandle: FileHandle
        do {
            logHandle = try Self.appendHandle(path: info.log)
        } catch {
            log.error("Can't open the engine log: \(error.localizedDescription, privacy: .public)")
            state = .stopped(reason: "Can't write the log file \(info.log)")
            return
        }
        p.standardOutput = logHandle
        p.standardError = logHandle
        p.terminationHandler = { [weak self] proc in
            let status = proc.terminationStatus
            let signalled = proc.terminationReason == .uncaughtSignal
            Task { @MainActor in self?.childExited(proc, status: status, signalled: signalled) }
        }
        do {
            try p.run()
        } catch {
            try? logHandle.close()
            log.error("Can't start the engine: \(error.localizedDescription, privacy: .public)")
            state = .stopped(reason: "Can't start the engine: \(error.localizedDescription)")
            return
        }
        try? logHandle.close()  // The child has its own copy.
        process = p
        startedAt = Date()
        state = .starting
        log.info("Started the engine, pid \(p.processIdentifier)")
        waitUntilReady(p)
    }

    /// Polls the status endpoint until the new child answers (up to a minute).
    private func waitUntilReady(_ p: Process) {
        readyTask?.cancel()
        readyTask = Task { [weak self] in
            for _ in 0..<120 {
                try? await Task.sleep(for: .milliseconds(500))
                guard let self, !Task.isCancelled, self.process === p else { return }
                guard let client = self.client else { return }
                let result: Result<EngineStatus, Error>
                do { result = .success(try await client.status()) } catch { result = .failure(error) }
                switch StatusPoll.outcome(of: result) {
                case .networkError, .otherError:
                    continue  // Not listening yet.
                case .ok, .unauthorized, .rateLimited:
                    // It answers, so it's up. A refused code is the status timer's business:
                    // never keep sending it here.
                    if self.process === p, self.state == .starting { self.state = .running(external: false) }
                    return
                }
            }
        }
    }

    private func childExited(_ p: Process, status: Int32, signalled: Bool) {
        guard p === process else { return }
        process = nil
        readyTask?.cancel()
        killTask?.cancel()
        log.info("Engine exited, \(signalled ? "signal" : "status", privacy: .public) \(status)")
        if stopping {
            state = .stopped(reason: "Quit")
            finishStop()
            return
        }
        if let startedAt, Date().timeIntervalSince(startedAt) >= Self.healthyUptime { backoff.reset() }
        let delay = backoff.next()
        state = .restarting(in: delay)
        restartTask?.cancel()
        restartTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self, !Task.isCancelled, !self.stopping else { return }
            self.state = .starting
            await self.launch()
        }
    }

    /// The status refresh reports what it saw, so the state follows the real engine.
    func noteStatus(answered: Bool) {
        switch state {
        case .starting where answered && process != nil:
            state = .running(external: false)
        case .running(external: true) where !answered && !reprobing:
            // The adopted engine may have gone away: start our own only if the port is now free.
            // A busy engine that timed out keeps being used.
            reprobing = true
            Task {
                defer { reprobing = false }
                guard let client else { return }
                let result: Result<EngineStatus, Error>
                do { result = .success(try await client.status()) } catch { result = .failure(error) }
                guard !stopping, process == nil, case .running(external: true) = state,
                      PortProbe.classify(result) == .free, let info else { return }
                log.info("The adopted engine stopped; starting our own")
                spawn(info)
            }
        default:
            break
        }
    }

    /// Stops the child this app started: SIGTERM, then SIGKILL after 5 s.
    /// An adopted engine keeps running. `then` runs once the child is gone.
    func stop(then: (() -> Void)? = nil) {
        stopping = true
        restartTask?.cancel()
        readyTask?.cancel()
        guard let p = process, p.isRunning else {
            process = nil
            if case .running(external: true) = state {} else { state = .stopped(reason: "Quit") }
            then?()
            return
        }
        onStopped = then
        log.info("Stopping the engine, pid \(p.processIdentifier)")
        p.terminate()
        killTask?.cancel()
        killTask = Task { [weak self] in
            try? await Task.sleep(for: Engine.killAfter)
            guard !Task.isCancelled else { return }
            if p.isRunning {
                log.error("Engine ignored SIGTERM; sending SIGKILL")
                kill(p.processIdentifier, SIGKILL)
            }
            // Don't hold up Quit forever if the exit notice never arrives.
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            self?.finishStop()
        }
    }

    private func finishStop() {
        let done = onStopped
        onStopped = nil
        done?()
    }

    private static func appendHandle(path: String) throws -> FileHandle {
        let url = URL(fileURLWithPath: path)
        let fm = FileManager.default
        try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !fm.fileExists(atPath: path) { fm.createFile(atPath: path, contents: nil) }
        let handle = try FileHandle(forWritingTo: url)
        try handle.seekToEnd()
        return handle
    }
}
