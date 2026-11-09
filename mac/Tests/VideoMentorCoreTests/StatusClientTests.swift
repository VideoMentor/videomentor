import XCTest
@testable import VideoMentorCore

final class StubProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var handler: (@Sendable (URLRequest) -> (Int, Data))?
    nonisolated(unsafe) static var seen: [URLRequest] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.seen.append(request)
        let (code, data) = Self.handler?(request) ?? (500, Data())
        let resp = HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

final class StatusClientTests: XCTestCase {
    private func client() -> StatusClient {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [StubProtocol.self]
        StubProtocol.seen = []
        return StatusClient(port: 8791, pairCode: "1234-5678-9012", session: URLSession(configuration: cfg))
    }

    func testSendsBearerCode() async throws {
        StubProtocol.handler = { _ in
            (200, Data(#"{"counts":{"total":3,"inbox":2,"music_inbox":1},"last_sync":null,"youtube_api":{"state":"ok"}}"#.utf8))
        }
        let s = try await client().status()
        XCTAssertEqual(s.counts.total, 3)
        XCTAssertNil(s.lastSync)
        XCTAssertEqual(s.youtubeState, "ok")
        let req = try XCTUnwrap(StubProtocol.seen.first)
        XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer 1234-5678-9012")
        XCTAssertEqual(req.url?.path, "/api/status")
        XCTAssertEqual(req.url?.host, "127.0.0.1")
        XCTAssertEqual(req.url?.port, 8791)
    }

    func testSyncNowPostsAndDeviceCount() async throws {
        StubProtocol.handler = { r in
            r.url?.path == "/api/devices" ? (200, Data(#"{"devices":[{"id":"a"},{"id":"b"}],"expire_days":30}"#.utf8))
                                          : (200, Data(#"{"started":true}"#.utf8))
        }
        let c = client()
        try await c.syncNow()
        XCTAssertEqual(StubProtocol.seen.last?.httpMethod, "POST")
        XCTAssertEqual(StubProtocol.seen.last?.url?.path, "/api/sync")
        let n = try await c.deviceCount()
        XCTAssertEqual(n, 2)
    }

    func testHTTPErrorThrows() async {
        StubProtocol.handler = { _ in (401, Data()) }
        do { _ = try await client().status(); XCTFail("expected throw") } catch {}
    }
}
