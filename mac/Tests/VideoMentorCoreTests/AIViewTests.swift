import XCTest
@testable import VideoMentorCore

final class AIViewTests: XCTestCase {
    private func settings(_ json: String) throws -> AISettings {
        try JSONDecoder().decode(AISettings.self, from: Data(json.utf8))
    }

    func testChoicesInPickerOrder() {
        XCTAssertEqual(AIChoice.allCases.map(\.title), ["Auto", "Claude Code", "API key", "Off"])
        XCTAssertEqual(AIChoice.allCases.map(\.rawValue), ["auto", "claude_code", "api", "off"])
        XCTAssertEqual(AIChoice.allCases.filter(\.showsCap), [.auto, .api])
    }

    func testSummaryLineMatchesTheWeb() throws {
        XCTAssertEqual(try settings(#"{"backend":"claude_code","choice":"auto","cap_usd":5,"month_cost_usd":0,"paused":false,"reason":null}"#).line,
                       "AI: Claude Code")
        XCTAssertEqual(try settings(#"{"backend":"api","choice":"api","cap_usd":5,"month_cost_usd":1.2,"paused":false,"reason":null}"#).line,
                       "AI: API key · $1.20 of $5.00 this month")
        XCTAssertEqual(try settings(#"{"backend":"off","choice":"off","cap_usd":5,"month_cost_usd":0,"paused":true,"reason":"AI is off"}"#).line,
                       "AI: off · cards show without summaries or notes")
        XCTAssertEqual(try settings(#"{"backend":"off","choice":"api","cap_usd":5,"month_cost_usd":0,"paused":true,"reason":"AI is off: no API key is set"}"#).line,
                       "AI: off (no API key is set) · cards show without summaries or notes")
        XCTAssertEqual(try settings(#"{"backend":"api","choice":"api","cap_usd":5,"month_cost_usd":5.1,"paused":true,"reason":"AI paused: this month's $5.00 limit is used"}"#).line,
                       "AI paused: this month's $5.00 limit is used")
    }

    func testUnknownChoiceFallsBackToAuto() throws {
        let s = try settings(#"{"backend":"off","choice":"something_new","cap_usd":5,"month_cost_usd":0,"paused":true,"reason":"AI is off"}"#)
        XCTAssertEqual(s.choice, .auto)
    }

    func testErrorMessages() {
        XCTAssertEqual(AIRequest.outcome(of: StatusClient.HTTPError(status: 401)), .refused)
        XCTAssertEqual(AIRequest.outcome(of: StatusClient.HTTPError(status: 429)), .rateLimited)
        XCTAssertEqual(AIRequest.outcome(of: StatusClient.HTTPError(status: 422)), .failed("VideoMentor didn't accept that value."))
        XCTAssertEqual(AIRequest.outcome(of: URLError(.cannotConnectToHost)), .failed("VideoMentor isn't answering. Try again in a moment."))
        XCTAssertEqual(AIRequest.rateLimitedText,
                       "VideoMentor is refusing requests for a while after too many wrong pairing codes. Try again in 15 minutes.")
    }
}
