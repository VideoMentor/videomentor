import Foundation

/// Decides what the status timer does after each call. The engine counts refused Bearer codes
/// in the same lockout as /pair (10 per 15 minutes, for every device), so a stale code must
/// never be sent over and over.
public enum StatusPoll {
    public enum Outcome: Sendable, Equatable {
        case ok, unauthorized, rateLimited, networkError, otherError
    }

    public enum Action: Sendable, Equatable {
        /// Carry on with the 30 s timer.
        case keepPolling
        /// The code was refused: read `vm launch-info` again (the code may have changed).
        case reloadLaunchInfo
        /// Refused again after a reload: send nothing more until the app restarts.
        case stopPolling
    }

    public static func outcome(of result: Result<EngineStatus, Error>) -> Outcome {
        switch result {
        case .success:
            return .ok
        case .failure(let error as StatusClient.HTTPError):
            switch error.status {
            case 401: return .unauthorized
            case 429: return .rateLimited
            default: return .otherError
            }
        case .failure(is URLError):
            return .networkError
        case .failure:
            return .otherError
        }
    }

    /// `reloadedSinceLastOK`: launch info was already re-read since the last good answer.
    public static func next(after outcome: Outcome, reloadedSinceLastOK: Bool) -> Action {
        switch outcome {
        case .ok, .networkError, .otherError, .rateLimited:
            // A 429 is someone else's lockout; the engine only counts failed codes, so a
            // correct code is harmless. Keep polling without reloading.
            return .keepPolling
        case .unauthorized:
            return reloadedSinceLastOK ? .stopPolling : .reloadLaunchInfo
        }
    }

    /// No calls while the engine is stopped or after polling was stopped.
    public static func shouldPoll(engineStopped: Bool, blocked: Bool) -> Bool {
        !engineStopped && !blocked
    }
}
