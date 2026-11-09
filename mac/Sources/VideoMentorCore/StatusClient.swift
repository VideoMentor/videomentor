import Foundation

/// The parts of `/api/status` the menu needs. Unknown keys are ignored.
public struct EngineStatus: Decodable, Sendable, Equatable {
    public struct Counts: Decodable, Sendable, Equatable {
        public let total: Int
        public let inbox: Int
        public let musicInbox: Int
        public let ready: Int

        enum CodingKeys: String, CodingKey {
            case total, inbox, ready
            case musicInbox = "music_inbox"
        }

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            total = try c.decodeIfPresent(Int.self, forKey: .total) ?? 0
            inbox = try c.decodeIfPresent(Int.self, forKey: .inbox) ?? 0
            musicInbox = try c.decodeIfPresent(Int.self, forKey: .musicInbox) ?? 0
            ready = try c.decodeIfPresent(Int.self, forKey: .ready) ?? 0
        }
    }

    public struct LastSync: Decodable, Sendable, Equatable {
        public let startedAt: Date?
        public let finishedAt: Date?

        enum CodingKeys: String, CodingKey {
            case startedAt = "started_at"
            case finishedAt = "finished_at"
        }

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            startedAt = Self.date(try c.decodeIfPresent(String.self, forKey: .startedAt))
            finishedAt = Self.date(try c.decodeIfPresent(String.self, forKey: .finishedAt))
        }

        static func date(_ s: String?) -> Date? {
            guard let s else { return nil }
            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            if let d = plain.date(from: s) { return d }
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            return fractional.date(from: s)
        }
    }

    private struct YouTubeAPI: Decodable {
        let state: String?
    }

    public let counts: Counts
    public let lastSync: LastSync?
    public let youtubeState: String?

    /// Videos waiting for a decision: the inbox plus the music inbox.
    public var toTriage: Int { counts.inbox + counts.musicInbox }

    enum CodingKeys: String, CodingKey {
        case counts
        case lastSync = "last_sync"
        case youtubeAPI = "youtube_api"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        counts = try c.decode(Counts.self, forKey: .counts)
        lastSync = try c.decodeIfPresent(LastSync.self, forKey: .lastSync)
        youtubeState = try c.decodeIfPresent(YouTubeAPI.self, forKey: .youtubeAPI)?.state
    }
}

/// Talks to the local engine with the pairing code as a bearer token.
public final class StatusClient: Sendable {
    public struct HTTPError: Error, LocalizedError {
        public let status: Int
        public var errorDescription: String? { "The engine answered with HTTP \(status)." }
    }

    private let base: URL
    private let pairCode: String
    private let session: URLSession

    public init(port: Int, pairCode: String, host: String = "127.0.0.1", session: URLSession = .shared) {
        self.base = URL(string: "http://\(host):\(port)")!
        self.pairCode = pairCode
        self.session = session
    }

    private func send(
        _ path: String, method: String = "GET", json: [String: Any]? = nil, timeout: TimeInterval = 10
    ) async throws -> Data {
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = method
        request.timeoutInterval = timeout
        request.setValue("Bearer \(pairCode)", forHTTPHeaderField: "Authorization")
        if let json {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: json)
        }
        let (data, response) = try await session.data(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw HTTPError(status: http.statusCode)
        }
        return data
    }

    public func status() async throws -> EngineStatus {
        try JSONDecoder().decode(EngineStatus.self, from: try await send("api/status"))
    }

    public func syncNow() async throws {
        _ = try await send("api/sync", method: "POST")
    }

    // AI settings. One call per user action: a refused code (401) or the lockout (429) is
    // thrown to the caller and never retried here.

    public func aiSettings() async throws -> AISettings {
        try JSONDecoder().decode(AISettings.self, from: try await send("api/ai"))
    }

    /// Changes the choice, the monthly cap, or both; only what is passed is sent.
    public func setAI(choice: AIChoice? = nil, capUSD: Double? = nil) async throws -> AISettings {
        var body: [String: Any] = [:]
        if let choice { body["backend"] = choice.rawValue }
        if let capUSD { body["cap_usd"] = capUSD }
        return try JSONDecoder().decode(AISettings.self, from: try await send("api/ai", method: "PUT", json: body))
    }

    /// One small model call on the current backend. It can take a while, so it waits up to 90 s.
    public func checkAI() async throws -> AICheck {
        try JSONDecoder().decode(AICheck.self, from: try await send("api/ai/check", method: "POST", json: [:], timeout: 90))
    }

    public func deviceCount() async throws -> Int {
        struct Devices: Decodable { let devices: [Item]; struct Item: Decodable {} }
        return try JSONDecoder().decode(Devices.self, from: try await send("api/devices")).devices.count
    }
}
