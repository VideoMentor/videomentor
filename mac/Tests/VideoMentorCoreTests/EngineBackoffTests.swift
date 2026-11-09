import XCTest
@testable import VideoMentorCore

final class EngineBackoffTests: XCTestCase {
    func testBackoffSequenceAndReset() {
        var backoff = Backoff()
        XCTAssertEqual((0..<8).map { _ in backoff.next() }, [1, 2, 4, 8, 16, 32, 60, 60])
        backoff.reset()
        XCTAssertEqual((0..<3).map { _ in backoff.next() }, [1, 2, 4])
    }

    func testPortProbeClassification() {
        let ok = try! JSONDecoder().decode(EngineStatus.self, from: Data(#"{"counts":{"total":1}}"#.utf8))
        XCTAssertEqual(PortProbe.classify(.success(ok)), .ours)
        // The port answers but refuses this pairing code, or answers with something else.
        XCTAssertEqual(PortProbe.classify(.failure(StatusClient.HTTPError(status: 401))), .otherApp)
        XCTAssertEqual(PortProbe.classify(.failure(StatusClient.HTTPError(status: 404))), .otherApp)
        XCTAssertEqual(PortProbe.classify(.failure(DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "html")))), .otherApp)
        // Nothing listening.
        XCTAssertEqual(PortProbe.classify(.failure(URLError(.cannotConnectToHost))), .free)
        XCTAssertEqual(PortProbe.classify(.failure(URLError(.networkConnectionLost))), .free)
        // Something listening that never answers.
        XCTAssertEqual(PortProbe.classify(.failure(URLError(.timedOut))), .otherApp)
    }
}
