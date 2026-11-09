import AppKit
import Combine
import SwiftUI
import VideoMentorCore

@main
struct VideoMentorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: delegate.model, engine: delegate.model.engine, login: delegate.model.login)
        } label: {
            Image(nsImage: MenuIcon.image)
        }
        .menuBarExtraStyle(.menu)
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // A menu bar app: no Dock icon (Task 4's Info.plist also sets LSUIElement).
        NSApp.setActivationPolicy(.accessory)
        model.launch()
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

    func refresh() async {
        guard !refreshing, let client = engine.client else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            status = try await client.status()
            engine.noteStatus(answered: true)
        } catch {
            status = nil
            engine.noteStatus(answered: false)
        }
    }

    var statusLine: String {
        switch engine.state {
        case .starting:
            return StatusLine.text(running: false, status: nil, now: Date(), starting: true)
        case .running:
            return StatusLine.text(running: true, status: status, now: Date())
        case .restarting(let seconds):
            return "Restarting in \(seconds) s · see log"
        case .stopped(let reason):
            return "Stopped: \(reason)"
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
            .disabled(!model.isRunning)
        Divider()
        Toggle("Start at Login", isOn: Binding(get: { login.enabled }, set: { login.set($0) }))
        if let error = login.error {
            Text(error)
        }
        Button("Show Log") { model.showLog() }
            .disabled(engine.info == nil)
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
