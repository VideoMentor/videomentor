import Foundation

/// Builds the links that pair a phone or this Mac with the engine.
public enum PairLink {
    /// Reads `Self.DNSName` from `tailscale status --json`, without the trailing dot.
    public static func tailscaleName(fromStatusJSON data: Data) -> String? {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let me = root["Self"] as? [String: Any],
              var name = me["DNSName"] as? String else { return nil }
        while name.hasSuffix(".") { name.removeLast() }
        return name.isEmpty ? nil : name
    }

    public static func links(port: Int, code: String, tailscaleName: String?) -> (phone: URL?, mac: URL) {
        let mac = URL(string: "http://127.0.0.1:\(port)/pair?code=\(code)")!
        let phone = tailscaleName.flatMap { URL(string: "https://\($0)/pair?code=\(code)") }
        return (phone, mac)
    }
}
