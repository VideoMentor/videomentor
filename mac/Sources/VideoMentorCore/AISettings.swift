import Foundation

/// The saved AI choice, in picker order.
public enum AIChoice: String, CaseIterable, Sendable, Equatable {
    case auto
    case claudeCode = "claude_code"
    case api
    case off

    public var title: String {
        switch self {
        case .auto: "Auto"
        case .claudeCode: "Claude Code"
        case .api: "API key"
        case .off: "Off"
        }
    }

    /// The monthly cap only matters when the API key may be used.
    public var showsCap: Bool { self == .api || self == .auto }
}

/// `GET`/`PUT /api/ai`. `backend` is what `choice` resolves to right now.
public struct AISettings: Decodable, Sendable, Equatable {
    public let backend: String
    public let choice: AIChoice
    public let capUSD: Double
    public let monthCostUSD: Double
    public let paused: Bool
    public let reason: String?

    enum CodingKeys: String, CodingKey {
        case backend, choice, paused, reason
        case capUSD = "cap_usd"
        case monthCostUSD = "month_cost_usd"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        backend = try c.decode(String.self, forKey: .backend)
        choice = AIChoice(rawValue: try c.decodeIfPresent(String.self, forKey: .choice) ?? "") ?? .auto
        capUSD = try c.decodeIfPresent(Double.self, forKey: .capUSD) ?? 0
        monthCostUSD = try c.decodeIfPresent(Double.self, forKey: .monthCostUSD) ?? 0
        paused = try c.decodeIfPresent(Bool.self, forKey: .paused) ?? false
        reason = try c.decodeIfPresent(String.self, forKey: .reason)
    }

    /// The same one-line summary as the web Status card (`aiLine`).
    public var line: String {
        if backend == "off" {
            let prefix = "AI is off: "
            var why = ""
            if choice != .off, let reason, reason.hasPrefix(prefix) { why = " (\(reason.dropFirst(prefix.count)))" }
            return "AI: off\(why) · cards show without summaries or notes"
        }
        if paused, let reason { return reason }
        if backend == "api" {
            return "AI: API key · \(Self.usd(monthCostUSD)) of \(Self.usd(capUSD)) this month"
        }
        return "AI: Claude Code"
    }

    static func usd(_ n: Double) -> String { String(format: "$%.2f", locale: Locale(identifier: "en_US_POSIX"), n) }
}

/// `POST /api/ai/check`.
public struct AICheck: Decodable, Sendable, Equatable {
    public let ok: Bool
    public let backend: String
    public let message: String
}

/// What an AI settings call's failure means. Each user action sends one request; nothing retries.
public enum AIRequest {
    public enum Outcome: Sendable, Equatable {
        /// 401: the pairing code was refused. The caller re-reads launch info once, never resends.
        case refused
        /// 429: the engine's lockout for wrong codes is on.
        case rateLimited
        case failed(String)
    }

    public static let rateLimitedText =
        "VideoMentor is refusing requests for a while after too many wrong pairing codes. Try again in 15 minutes."

    public static func outcome(of error: Error) -> Outcome {
        switch error {
        case let http as StatusClient.HTTPError:
            switch http.status {
            case 401: return .refused
            case 429: return .rateLimited
            case 422: return .failed("VideoMentor didn't accept that value.")
            default: return .failed("VideoMentor answered with an error (HTTP \(http.status)).")
            }
        case is URLError:
            return .failed("VideoMentor isn't answering. Try again in a moment.")
        default:
            return .failed("Something went wrong: \(error.localizedDescription)")
        }
    }
}
