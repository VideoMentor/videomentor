import AppKit
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
    @Published private(set) var settings: AISettings?
    @Published var capText = ""
    @Published private(set) var keyNote: String?
    @Published private(set) var engineNote: String?
    @Published private(set) var busy = false

    init(app: AppModel) {
        self.app = app
    }

    /// Engine calls are off while the engine isn't running or after the code was refused.
    var canCallEngine: Bool { app.isRunning && !app.pollBlocked && !busy }

    /// Reads whether a key is saved (off the main thread) and the current settings (one call).
    func load() async {
        hasKey = await Task.detached { KeychainKey.read() != nil }.value
        guard canCallEngine else {
            engineNote = app.pollBlocked ? "Pairing code changed: restart VideoMentor" : "VideoMentor isn't running."
            return
        }
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
            keyNote = "Key saved. " + restartNote()
        } catch {
            keyNote = "Couldn't save the key: \(error.localizedDescription)"
        }
    }

    func removeKey() async {
        do {
            try await Task.detached { try KeychainKey.delete() }.value
            hasKey = false
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
        guard let cap = Double(capText.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "$", with: "")),
              cap >= 0, cap <= 1000 else {
            engineNote = "The monthly limit must be between $0 and $1000."
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
        guard canCallEngine, let client = app.engine.client else { return }
        busy = true
        engineNote = nil
        defer { busy = false }
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
                Text(model.hasKey ? "A key is saved" : "No key is saved")
                    .foregroundStyle(.secondary)
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
                if let note = model.engineNote {
                    Text(note).font(.callout).textSelection(.enabled)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
        .task { await model.load() }
    }
}
