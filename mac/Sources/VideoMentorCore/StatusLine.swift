import Foundation

public enum StatusLine {
    /// The one-line summary at the top of the menu.
    /// `locale` and `timeZone` are parameters so tests can pin them.
    public static func text(
        running: Bool,
        status: EngineStatus?,
        now: Date,
        starting: Bool = false,
        locale: Locale = .current,
        timeZone: TimeZone = .current
    ) -> String {
        guard running else { return starting ? "Starting…" : "Stopped" }
        var parts = ["Running"]
        if let finished = status?.lastSync?.finishedAt {
            let f = DateFormatter()
            f.locale = locale
            f.timeZone = timeZone
            f.dateStyle = .none
            f.timeStyle = .short
            // Newer systems put a narrow no-break space before AM/PM; use a plain space.
            let time = f.string(from: finished)
                .replacingOccurrences(of: "\u{202F}", with: " ")
                .replacingOccurrences(of: "\u{00A0}", with: " ")
            parts.append("last sync \(time)")
        }
        if let status {
            parts.append("\(grouped(status.toTriage)) to triage")
        }
        return parts.joined(separator: " · ")
    }

    /// The status line when the engine is not running; it always points to the log.
    public static func stopped(reason: String) -> String {
        var r = reason.trimmingCharacters(in: .whitespaces)
        while r.hasSuffix(".") { r.removeLast() }
        return "Stopped: \(r). See log"
    }

    /// Thousands separators that do not depend on the user's locale: 1207 becomes "1,207".
    static func grouped(_ n: Int) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.numberStyle = .decimal
        f.usesGroupingSeparator = true
        f.groupingSeparator = ","
        f.groupingSize = 3
        return f.string(from: NSNumber(value: n)) ?? String(n)
    }
}
