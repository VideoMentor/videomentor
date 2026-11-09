import XCTest
@testable import VideoMentorCore

final class StatusPollTests: XCTestCase {
    private let ok: Result<EngineStatus, Error> = .success(
        try! JSONDecoder().decode(EngineStatus.self, from: Data(#"{"counts":{"total":1}}"#.utf8)))

    func testOutcomeOfStatusResults() {
        XCTAssertEqual(StatusPoll.outcome(of: ok), .ok)
        XCTAssertEqual(StatusPoll.outcome(of: .failure(StatusClient.HTTPError(status: 401))), .unauthorized)
        XCTAssertEqual(StatusPoll.outcome(of: .failure(StatusClient.HTTPError(status: 429))), .rateLimited)
        XCTAssertEqual(StatusPoll.outcome(of: .failure(StatusClient.HTTPError(status: 500))), .otherError)
        XCTAssertEqual(StatusPoll.outcome(of: .failure(URLError(.cannotConnectToHost))), .networkError)
    }

    func testNextAction() {
        // Answers keep the timer going.
        XCTAssertEqual(StatusPoll.next(after: .ok, reloadedSinceLastOK: false), .keepPolling)
        XCTAssertEqual(StatusPoll.next(after: .ok, reloadedSinceLastOK: true), .keepPolling)
        XCTAssertEqual(StatusPoll.next(after: .networkError, reloadedSinceLastOK: false), .keepPolling)
        XCTAssertEqual(StatusPoll.next(after: .otherError, reloadedSinceLastOK: true), .keepPolling)
        // A refused code: re-read launch info once, then give up (never a second failing request).
        XCTAssertEqual(StatusPoll.next(after: .unauthorized, reloadedSinceLastOK: false), .reloadLaunchInfo)
        XCTAssertEqual(StatusPoll.next(after: .rateLimited, reloadedSinceLastOK: false), .reloadLaunchInfo)
        XCTAssertEqual(StatusPoll.next(after: .unauthorized, reloadedSinceLastOK: true), .stopPolling)
        XCTAssertEqual(StatusPoll.next(after: .rateLimited, reloadedSinceLastOK: true), .stopPolling)
    }

    func testShouldPoll() {
        XCTAssertTrue(StatusPoll.shouldPoll(engineStopped: false, blocked: false))
        XCTAssertFalse(StatusPoll.shouldPoll(engineStopped: true, blocked: false))
        XCTAssertFalse(StatusPoll.shouldPoll(engineStopped: false, blocked: true))
    }

    func testStoppedLinePointsToTheLog() {
        XCTAssertEqual(StatusLine.stopped(reason: "Port 8791 is used by another app"),
                       "Stopped: Port 8791 is used by another app. See log")
        XCTAssertEqual(StatusLine.stopped(reason: "Can't find the engine. Run vm install."),
                       "Stopped: Can't find the engine. Run vm install. See log")
    }
}
