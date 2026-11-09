import AppKit
import Combine
import SwiftUI
import VideoMentorCore

@main
struct VideoMentorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    /// The "Show in" choice; AppModel.setShowIn writes it, and this hides the menu bar item.
    @AppStorage(ShowIn.defaultsKey) private var showInRaw = ShowIn.defaultValue.rawValue

    var body: some Scene {
        MenuBarExtra(isInserted: menuBarItemShown) {
            MenuContent(model: delegate.model, engine: delegate.model.engine, login: delegate.model.login)
        } label: {
            Image(nsImage: MenuIcon.image)
        }
        .menuBarExtraStyle(.menu)
    }

    private var menuBarItemShown: Binding<Bool> {
        Binding(
            get: { ShowIn(stored: showInRaw).showsMenuBarItem },
            set: { inserted in
                // Removed by the user (Cmd-drag out of the menu bar): keep the Dock icon.
                if !inserted { delegate.model.setShowIn(.dock) }
            })
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Info.plist sets LSUIElement, so the Dock icon appears only if the setting asks for it.
        DockPresence.apply(model.showIn, activate: false)
        model.launch()
    }

    /// Clicking the Dock icon (or opening the app again) opens the VideoMentor window.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { model.openWindow() }
        return true
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        DockMenu.build(model: model)
    }

    /// Quit waits for the engine this app started to exit (SIGTERM, then SIGKILL after 5 s).
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard model.engine.ownsChild else {
            model.engine.stop()
            return .terminateNow
        }
        model.engine.stop { NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
}

/// Status refresh and the menu's actions.
@MainActor
final class AppModel: ObservableObject {
    let engine = Engine()
    let login = LoginItem()
    let web = WebModel()
    let windows = Windows()

    @Published private(set) var status: EngineStatus?
    @Published private(set) var note: String?
    /// Set once the engine has refused the code after a reload; cleared only by restarting the app.
    @Published private(set) var pollBlocked = false
    @Published private(set) var showIn = ShowIn(stored: UserDefaults.standard.string(forKey: ShowIn.defaultsKey))

    private var refreshing = false
    private var timer: Task<Void, Never>?
    private var menuObserver: NSObjectProtocol?
    private var stateWatch: AnyCancellable?

    func launch() {
        // Fill in the counts as soon as the engine is up, without waiting for the timer.
        stateWatch = engine.$state.removeDuplicates().sink { [weak self] state in
            guard case .running = state else { return }
            Task { @MainActor in await self?.refresh() }
        }
        engine.start()
        timer = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                await self?.refresh()
            }
        }
        // Refresh when the menu opens.
        menuObserver = NotificationCenter.default.addObserver(
            forName: NSMenu.didBeginTrackingNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.login.refresh()
                await self?.refresh()
            }
        }
    }

    /// One status call, then `StatusPoll` decides what follows. A refused code re-reads launch
    /// info once and tries the new code once; refused again, polling stops for good, so the
    /// app can never lock pairing on the engine (refused codes count toward its lockout).
    func refresh() async {
        guard !refreshing,
              StatusPoll.shouldPoll(engineStopped: engineStopped, blocked: pollBlocked),
              let client = engine.client else { return }
        refreshing = true
        defer { refreshing = false }
        var result = await Self.call(client)
        var action = StatusPoll.next(after: StatusPoll.outcome(of: result), reloadedSinceLastOK: false)
        if action == .reloadLaunchInfo {
            let oldCode = engine.info?.pairCode
            let reloaded = await engine.reloadLaunchInfo()
            if reloaded, engine.info?.pairCode != oldCode, let fresh = engine.client {
                log.info("Pairing code changed on disk; using the new one")
                result = await Self.call(fresh)
                action = StatusPoll.next(after: StatusPoll.outcome(of: result), reloadedSinceLastOK: true)
            } else {
                // Same code (or unreadable): it would only be refused again, so send nothing.
                action = .stopPolling
            }
        }
        switch (action, result) {
        case (.stopPolling, _), (.reloadLaunchInfo, _):
            log.error("The engine refuses the pairing code; status checks stopped")
            pollBlocked = true
            status = nil
        case (.keepPolling, .success(let s)):
            status = s
            engine.noteStatus(answered: true)
        case (.keepPolling, .failure):
            status = nil
            engine.noteStatus(answered: false)
        }
    }

    private static func call(_ client: StatusClient) async -> Result<EngineStatus, Error> {
        do { return .success(try await client.status()) } catch { return .failure(error) }
    }

    private var engineStopped: Bool {
        if case .stopped = engine.state { return true }
        return false
    }

    var statusLine: String {
        if pollBlocked, !engineStopped { return "Pairing code changed: restart VideoMentor" }
        switch engine.state {
        case .starting:
            return StatusLine.text(running: false, status: nil, now: Date(), starting: true)
        case .running:
            return StatusLine.text(running: true, status: status, now: Date())
        case .restarting(let seconds):
            return "Restarting in \(seconds) s · see log"
        case .stopped(let reason):
            return StatusLine.stopped(reason: reason)
        }
    }

    var isRunning: Bool {
        if case .running = engine.state { return true }
        return false
    }

    var aboutLine: String {
        guard let info = engine.info else { return "VideoMentor" }
        return "VideoMentor v\(info.version) · Build \(info.build)"
    }

    private func url(_ path: String) -> URL? {
        guard let info = engine.info else { return nil }
        return URL(string: "http://\(Engine.reachableHost(info.host)):\(info.port)\(path)")
    }

    func openWindow() {
        guard let info = engine.info else { return }
        windows.showWeb(model: web)
        web.ensureLoaded(host: Engine.reachableHost(info.host), port: info.port, pairCode: info.pairCode)
    }

    func openInBrowser() {
        if let url = url("/") { NSWorkspace.shared.open(url) }
    }

    func pairPhone() {
        guard let info = engine.info else { return }
        windows.showPair(PairView(info: info))
    }

    func syncNow() {
        guard let client = engine.client else { return }
        note = "Sync started"
        Task {
            do {
                try await client.syncNow()
                await refresh()
            } catch {
                log.error("Sync now failed: \(error.localizedDescription, privacy: .public)")
                note = "Sync failed: \(error.localizedDescription)"
            }
        }
    }

    func showLog() {
        guard let path = engine.info?.log else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    /// Stores the "Show in" choice and applies it. Runs on the next turn of the main loop, so a
    /// menu bar menu that chose "Dock" has closed before its item is removed.
    func setShowIn(_ mode: ShowIn) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            UserDefaults.standard.set(mode.rawValue, forKey: ShowIn.defaultsKey)
            showIn = mode
            DockPresence.apply(mode, activate: true)
        }
    }
}

struct MenuContent: View {
    @ObservedObject var model: AppModel
    @ObservedObject var engine: Engine
    @ObservedObject var login: LoginItem

    var body: some View {
        Text(model.statusLine)
        if case .running(external: true) = engine.state {
            Text("Using the engine that was already running")
        }
        if let note = model.note {
            Text(note)
        }
        if case .stopped = engine.state {
            Button("Start Engine") { engine.start() }
        }
        Divider()
        Button("Open VideoMentor") { model.openWindow() }
            .disabled(!model.isRunning)
        Button("Open in Browser") { model.openInBrowser() }
            .disabled(!model.isRunning)
        Button("Pair a Phone…") { model.pairPhone() }
            .disabled(engine.info == nil)
        Button("Sync Now") { model.syncNow() }
            .disabled(!model.isRunning || model.pollBlocked)
        Divider()
        Toggle("Start at Login", isOn: Binding(get: { login.enabled }, set: { login.set($0) }))
        if let error = login.error {
            Text(error)
        }
        Button("Show Log") { model.showLog() }
            .disabled(engine.info == nil)
        Menu("Show in") {
            ForEach(ShowIn.allCases, id: \.self) { mode in
                Toggle(mode.title, isOn: Binding(
                    get: { model.showIn == mode },
                    set: { on in if on { model.setShowIn(mode) } }))
            }
        }
        Divider()
        Text(model.aboutLine)
        Button("Quit VideoMentor") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}

/// The menu bar mark, drawn from docs/brand/videomentor-mark.svg: the V and the progress ring.
/// A template image, so macOS tints it for light and dark menu bars.
enum MenuIcon {
    @MainActor static let image: NSImage = {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: true, drawingHandler: draw)
        image.isTemplate = true
        image.accessibilityDescription = "VideoMentor"
        return image
    }()

    /// The SVG's 512-unit box, cropped to the ring (64...448), scaled to 18 pt.
    private static func draw(_ rect: NSRect) -> Bool {
        let s = rect.width / 384
        func p(_ x: CGFloat, _ y: CGFloat) -> NSPoint { NSPoint(x: (x - 64) * s, y: (y - 64) * s) }
        let center = p(256, 256)
        let radius = 176 * s

        let ring = NSBezierPath()
        ring.appendArc(withCenter: center, radius: radius, startAngle: 0, endAngle: 360)
        ring.lineWidth = 1.3
        NSColor.black.withAlphaComponent(0.35).setStroke()
        ring.stroke()

        // The gold arc: 760 of 1106 units, from 12 o'clock going clockwise (y points down here).
        let arc = NSBezierPath()
        arc.appendArc(withCenter: center, radius: radius, startAngle: -90, endAngle: -90 + 247, clockwise: false)
        arc.lineWidth = 1.3
        arc.lineCapStyle = .round
        NSColor.black.setStroke()
        arc.stroke()

        let v = NSBezierPath()
        v.move(to: p(168, 168))
        v.line(to: p(256, 350))
        v.line(to: p(344, 168))
        v.lineWidth = 50 * s
        v.lineCapStyle = .round
        v.lineJoinStyle = .round
        v.stroke()
        return true
    }
}
