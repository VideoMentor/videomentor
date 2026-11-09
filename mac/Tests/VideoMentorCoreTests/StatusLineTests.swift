import XCTest
@testable import VideoMentorCore

final class StatusLineTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    private let us = Locale(identifier: "en_US")

    private func status(finished: String?) -> EngineStatus {
        let sync = finished.map { #","last_sync":{"started_at":"2026-11-09T14:00:00+00:00","finished_at":"\#($0)"}"# } ?? ""
        let json = #"{"counts":{"total":2239,"inbox":1207,"music_inbox":110,"ready":5},"youtube_api":{"state":"ok"}\#(sync)}"#
        return try! JSONDecoder().decode(EngineStatus.self, from: Data(json.utf8))
    }

    func testRunningLine() {
        let s = status(finished: "2026-11-09T14:14:00+00:00")
        XCTAssertEqual(s.toTriage, 1207)
        let text = StatusLine.text(running: true, status: s, now: Date(), locale: us, timeZone: utc)
        XCTAssertEqual(text, "Running · last sync 2:14 PM · 1,207 to triage")
    }

    func testRunningWithoutSyncOrStatus() {
        XCTAssertEqual(StatusLine.text(running: true, status: nil, now: Date(), locale: us, timeZone: utc), "Running")
        let s = status(finished: nil)
        XCTAssertEqual(StatusLine.text(running: true, status: s, now: Date(), locale: us, timeZone: utc),
                       "Running · 1,207 to triage")
    }

    func testStartingAndStoppedLines() {
        XCTAssertEqual(StatusLine.text(running: false, status: nil, now: Date(), starting: true), "Starting…")
        XCTAssertEqual(StatusLine.text(running: false, status: nil, now: Date()), "Stopped")
    }

    func testStoppedLine() {
        XCTAssertEqual(StatusLine.text(running: false, status: status(finished: nil), now: Date()), "Stopped")
    }
}
