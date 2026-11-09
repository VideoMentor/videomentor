import Foundation

/// Seconds to wait before restarting the engine: 1, 2, 4, 8, 16, 32, then 60 for every later try.
public struct Backoff: Sendable, Equatable {
    public static let delays = [1, 2, 4, 8, 16, 32, 60]
    private var index = 0

    public init() {}

    public mutating func next() -> Int {
        let delay = Self.delays[min(index, Self.delays.count - 1)]
        if index < Self.delays.count { index += 1 }
        return delay
    }

    /// Start over from 1 s (after the engine has stayed up long enough).
    public mutating func reset() { index = 0 }
}

/// What answered on the engine's port before the app starts its own engine.
public enum PortProbe: Sendable, Equatable {
    /// A VideoMentor engine that accepts this pairing code: use it, start nothing.
    case ours
    /// Something answers but refuses the code, answers with something else, or hangs.
    case otherApp
    /// Nothing is listening: the app may start its own engine.
    case free

    public static func classify(_ result: Result<EngineStatus, Error>) -> PortProbe {
        switch result {
        case .success:
            return .ours
        case .failure(let error as URLError):
            switch error.code {
            case .cannotConnectToHost, .cannotFindHost, .networkConnectionLost, .notConnectedToInternet:
                return .free
            default:
                return .otherApp
            }
        case .failure:
            return .otherApp
        }
    }
}
