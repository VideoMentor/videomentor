import Foundation

/// Where the app shows itself: a Dock icon, a menu bar item, or both.
/// Every value shows at least one of the two, so no choice can leave the app unreachable.
public enum ShowIn: String, CaseIterable, Sendable {
    case dock
    case menuBar
    case both

    /// The UserDefaults key that stores the raw value.
    public static let defaultsKey = "showIn"
    public static let defaultValue: ShowIn = .both

    /// A stored value; anything missing or unknown falls back to `both`.
    public init(stored: String?) {
        self = stored.flatMap(ShowIn.init(rawValue:)) ?? ShowIn.defaultValue
    }

    public var showsDockIcon: Bool { self != .menuBar }
    public var showsMenuBarItem: Bool { self != .dock }

    /// The menu item's name.
    public var title: String {
        switch self {
        case .dock: return "Dock"
        case .menuBar: return "Menu Bar"
        case .both: return "Both"
        }
    }
}
