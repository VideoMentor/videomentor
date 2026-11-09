import AppKit
import Combine
import SwiftUI
import VideoMentorCore

/// The AI Settings window: the API key in the keychain, the backend choice, the monthly cap,
/// and a one-call test. Every engine call is one request per click; a refused code (401) or the
/// lockout (429) is shown and never retried (see `StatusPoll`).
@MainActor
final class AISettingsModel: ObservableObject {
    static let keysPage = URL(string: "https://console.anthropic.com/settings/keys")!

    private let app: AppModel

    @Published var keyField = ""
    @Published private(set) var hasKey = false
    /// Set when the keychain refused the read, so "No key is saved" isn't shown wrongly.
    @Published private(set) var keyUnreadable: String?
    @Published private(set) var settings: AISettings?
    @Published var capText = ""
    @Published private(set) var keyNote: String?
    @Published private(set) var engineNote: String?
    @Published private(set) var busy = false

    static let waitingText = "Waiting for the engine…"
    static let stoppedText = "VideoMentor's engine is stopped."
    static let blockedText = "Pairing code changed: restart VideoMentor"

    private var watches: Set<AnyCancellable> = []
    /// The engine became running while a call was in flight: load once that call ends.
    private var loadPending = false

    init(app: AppModel) {
        self.app = app
        // Redraw when the engine state or the poll block changes, so the controls follow them.
        app.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &watches)
        app.engine.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &watches)
        // Load the settings each time the engine becomes running: when the window opens on a
        // running engine, when a starting engine comes up, and after a key restart. @Published
        // sends before the value is stored, so the load runs on the next turn of the main loop.
        app.engine.$state
            .map { if case .running = $0 { true } else { false } }
            .removeDuplicates()
            .sink { [weak self] running in
                Task { @MainActor in
                    guard let self else { return }
                    if running { await self.loadSettings() } else { self.engineNote = self.notRunningText }
                }
            }
            .store(in: &watches)
    }

    /// Engine calls are off while the engine isn't running or after the code was refused.
    var canCallEngine: Bool { app.isRunning && !app.pollBlocked && !busy }

    /// Stopped is final until someone restarts it; starting and restarting are brief waits.
    private var notRunningText: String {
        if case .stopped = app.engine.state { return Self.stoppedText }
        return Self.waitingText
    }

    /// Why engine controls are off, or nil when they're on (or a call is in flight).
    var engineUnavailableText: String? {
        if app.pollBlocked { return Self.blockedText }
        if !app.isRunning { return notRunningText }
        return nil
    }

    /// Reads whether a key is saved, off the main thread. The key itself is not kept.
    func readKey() async {
        let lookup = await Task.detached { KeychainKey.lookUp() }.value
        hasKey = lookup.key != nil
        keyUnreadable = lookup.unreadableText
    }

    /// One GET of the current settings.
    private func loadSettings() async {
        if busy { loadPending = true; return }
        await call { client in
            let s = try await client.aiSettings()
            self.apply(s)
        }
    }

    func saveKey() async {
        let key = keyField.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { keyNote = "Paste a key first."; return }
        keyField = ""
        do {
            try await Task.detached { try KeychainKey.save(key) }.value
            hasKey = true
            keyUnreadable = nil
            keyNote = "Key saved. " + restartNote()
        } catch {
            keyNote = "Couldn't save the key: \(error.localizedDescription)"
        }
    }

    func removeKey() async {
        do {
            try await Task.detached { try KeychainKey.delete() }.value
            hasKey = false
            keyUnreadable = nil
            keyNote = "Key removed. " + restartNote()
        } catch {
            keyNote = "Couldn't remove the key: \(error.localizedDescription)"
        }
    }

    private func restartNote() -> String {
        switch app.engine.restartForKeyChange() {
        case .restarting: return "Restarting the engine to use it."
        case .external: return "Restart VideoMentor to use the key."
        case .notRunning: return "The engine uses it the next time it starts."
        }
    }

    func choose(_ choice: AIChoice) async {
        guard choice != settings?.choice else { return }
        await call { client in self.apply(try await client.setAI(choice: choice)) }
    }

    func saveCap() async {
        let text = capText.trimmingCharacters(in: .whitespaces)
        guard let cap = Double(text.replacingOccurrences(of: "$", with: "")), cap >= 0, cap <= 1000 else {
            // Never save a blank or bad value: put the saved one back.
            if let settings { apply(settings) }
            if !text.isEmpty { engineNote = "The monthly limit must be between $0 and $1000." }
            return
        }
        guard cap != settings?.capUSD else { return }
        await call { client in self.apply(try await client.setAI(capUSD: cap)) }
    }

    func test() async {
        await call { client in
            let check = try await client.checkAI()
            self.engineNote = check.message
        }
    }

    private func apply(_ s: AISettings) {
        settings = s
        capText = String(format: "%.2f", locale: Locale(identifier: "en_US_POSIX"), s.capUSD)
    }

    /// One request. A refused code re-reads launch info (no network); if the code didn't change,
    /// the app stops all engine calls until it restarts.
    private func call(_ body: @escaping (StatusClient) async throws -> Void) async {
        guard canCallEngine, let client = app.engine.client else {
            // Never fail silently: say why nothing was sent.
            if let why = engineUnavailableText { engineNote = why }
            return
        }
        busy = true
        engineNote = nil
        defer {
            busy = false
            if loadPending {
                loadPending = false
                Task { await self.loadSettings() }
            }
        }
        do {
            try await body(client)
        } catch {
            switch AIRequest.outcome(of: error) {
            case .refused:
                engineNote = await app.noteRefusedCode()
                    ? "The pairing code changed. Try again."
                    : "Pairing code changed: restart VideoMentor"
            case .rateLimited:
                engineNote = AIRequest.rateLimitedText
            case .failed(let text):
                engineNote = text
            }
        }
    }
}

struct AISettingsView: View {
    @ObservedObject var model: AISettingsModel

    var body: some View {
        Form {
            Section("API key") {
                if let unreadable = model.keyUnreadable {
                    Text(unreadable).foregroundStyle(.red)
                } else {
                    Text(model.hasKey ? "A key is saved" : "No key is saved")
                        .foregroundStyle(.secondary)
                }
                SecureField("Paste an Anthropic API key", text: $model.keyField)
                    .onSubmit { Task { await model.saveKey() } }
                HStack {
                    Button("Save") { Task { await model.saveKey() } }
                        .disabled(model.keyField.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    Button("Remove key") { Task { await model.removeKey() } }
                        .disabled(!model.hasKey)
                    Spacer()
                    Button("Get a key") { NSWorkspace.shared.open(AISettingsModel.keysPage) }
                }
                if let note = model.keyNote {
                    Text(note).font(.callout)
                }
                Text("The key stays in this Mac's keychain. VideoMentor only uses it when AI runs through the API key.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section("AI") {
                if let s = model.settings {
                    Text(s.line)
                    Picker("Use", selection: Binding(
                        get: { s.choice },
                        set: { choice in Task { await model.choose(choice) } })
                    ) {
                        ForEach(AIChoice.allCases, id: \.self) { Text($0.title).tag($0) }
                    }
                    .disabled(!model.canCallEngine)
                    if s.choice.showsCap {
                        HStack {
                            TextField("Monthly limit for the API key ($)", text: $model.capText)
                                .onSubmit { Task { await model.saveCap() } }
                            Button("Set") { Task { await model.saveCap() } }
                        }
                        .disabled(!model.canCallEngine)
                    }
                    if s.backend == "off" {
                        Text("Turning AI on adds card summaries, tags, scores, notes, actions and training.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                HStack {
                    Button("Test") { Task { await model.test() } }
                        .disabled(!model.canCallEngine)
                    if model.busy { ProgressView().controlSize(.small) }
                }
                if let note = model.engineNote ?? model.engineUnavailableText {
                    Text(note).font(.callout).textSelection(.enabled)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
        .task { await model.readKey() }
    }
}
