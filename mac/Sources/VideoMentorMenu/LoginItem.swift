import Foundation
import ServiceManagement

/// Start at Login through `SMAppService.mainApp`. Works only from a signed .app bundle;
/// anywhere else the toggle shows the error instead of crashing.
@MainActor
final class LoginItem: ObservableObject {
    @Published private(set) var enabled = false
    @Published private(set) var error: String?

    init() { refresh() }

    func refresh() {
        enabled = SMAppService.mainApp.status == .enabled
    }

    func set(_ on: Bool) {
        do {
            if on {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            error = nil
        } catch {
            log.error("Start at Login: \(error.localizedDescription, privacy: .public)")
            self.error = "Start at Login failed: \(error.localizedDescription)"
        }
        refresh()
        if on, SMAppService.mainApp.status == .requiresApproval {
            error = "Allow VideoMentor in System Settings > General > Login Items."
        }
    }
}
