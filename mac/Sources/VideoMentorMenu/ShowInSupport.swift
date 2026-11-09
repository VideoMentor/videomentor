import AppKit
import VideoMentorCore

/// Applies the "Show in" choice: a Dock icon (`.regular`) or none (`.accessory`).
/// Info.plist keeps LSUIElement, so the app never flashes a Dock icon before this runs.
@MainActor
enum DockPresence {
    static func apply(_ mode: ShowIn, activate: Bool) {
        let policy: NSApplication.ActivationPolicy = mode.showsDockIcon ? .regular : .accessory
        if NSApp.activationPolicy() != policy {
            NSApp.setActivationPolicy(policy)
        }
        if mode.showsDockIcon {
            // The bundle's AppIcon.icns (CFBundleIconFile); absent when run outside the bundle.
            if let icon = NSImage(named: "AppIcon") { NSApp.applicationIconImage = icon }
            MainMenu.ensure()
        }
        // Keeps open windows in front after a switch, and shows the app menu in Dock modes.
        if activate { NSApp.activate() }
    }
}

/// The app menu bar shown while a window is key in a Dock mode: Quit, Close, Edit and Window.
/// SwiftUI may already provide one; this only installs a menu when Cmd-Q, Cmd-W, Cmd-C or
/// Cmd-V is missing.
@MainActor
enum MainMenu {
    static func ensure() {
        if let menu = NSApp.mainMenu, ["q", "w", "c", "v"].allSatisfy({ has(menu, key: $0) }) { return }
        NSApp.mainMenu = build()
    }

    private static func has(_ menu: NSMenu, key: String) -> Bool {
        menu.items.contains { item in
            (item.keyEquivalent == key && item.keyEquivalentModifierMask == .command)
                || (item.submenu.map { has($0, key: key) } ?? false)
        }
    }

    private static func build() -> NSMenu {
        let main = NSMenu()

        let app = submenu(in: main, title: "VideoMentor")
        app.addItem(withTitle: "About VideoMentor",
                    action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Hide VideoMentor", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let others = app.addItem(withTitle: "Hide Others",
                                 action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        others.keyEquivalentModifierMask = [.command, .option]
        app.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        app.addItem(.separator())
        // Goes through applicationShouldTerminate, which stops the engine this app started.
        app.addItem(withTitle: "Quit VideoMentor", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        let file = submenu(in: main, title: "File")
        file.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")

        let edit = submenu(in: main, title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        let window = submenu(in: main, title: "Window")
        window.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        window.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        NSApp.windowsMenu = window

        return main
    }

    private static func submenu(in main: NSMenu, title: String) -> NSMenu {
        let item = main.addItem(withTitle: title, action: nil, keyEquivalent: "")
        let menu = NSMenu(title: title)
        item.submenu = menu
        return menu
    }
}

/// A menu item that runs a closure; used for the Dock menu.
@MainActor
final class ActionMenuItem: NSMenuItem {
    private let handler: @MainActor () -> Void

    init(_ title: String, enabled: Bool = true, checked: Bool = false, handler: @escaping @MainActor () -> Void) {
        self.handler = handler
        super.init(title: title, action: #selector(fire), keyEquivalent: "")
        target = self
        isEnabled = enabled
        state = checked ? .on : .off
    }

    @available(*, unavailable)
    required init(coder: NSCoder) { fatalError("not used") }

    @objc private func fire() { handler() }
}

/// The Dock icon's right-click menu: the same actions as the menu bar menu.
/// The Dock adds Quit itself, which goes through applicationShouldTerminate.
@MainActor
enum DockMenu {
    static func build(model: AppModel) -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false
        let engine = model.engine

        let status = NSMenuItem(title: model.statusLine, action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)
        if case .stopped = engine.state {
            menu.addItem(ActionMenuItem("Start Engine") { engine.start() })
        }
        menu.addItem(.separator())
        menu.addItem(ActionMenuItem("Open VideoMentor", enabled: model.isRunning) { model.openWindow() })
        menu.addItem(ActionMenuItem("Open in Browser", enabled: model.isRunning) { model.openInBrowser() })
        menu.addItem(ActionMenuItem("Pair a Phone…", enabled: engine.info != nil) { model.pairPhone() })
        menu.addItem(ActionMenuItem("Sync Now", enabled: model.isRunning && !model.pollBlocked) { model.syncNow() })
        menu.addItem(ActionMenuItem("Show Log", enabled: engine.info != nil) { model.showLog() })
        menu.addItem(ActionMenuItem("AI Settings…") { model.openAISettings() })
        menu.addItem(.separator())

        let showIn = NSMenuItem(title: "Show in", action: nil, keyEquivalent: "")
        let choices = NSMenu(title: "Show in")
        choices.autoenablesItems = false
        for mode in ShowIn.allCases {
            choices.addItem(ActionMenuItem(mode.title, checked: model.showIn == mode) { model.setShowIn(mode) })
        }
        showIn.submenu = choices
        menu.addItem(showIn)
        return menu
    }
}
