import XCTest
@testable import VideoMentorCore

final class StubProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var handler: (@Sendable (URLRequest) -> (Int, Data))?
    nonisolated(unsafe) static var seen: [URLRequest] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    /// Request bodies, in order (URLSession hands them over as a stream).
    nonisolated(unsafe) static var bodies: [Data] = []
    override func startLoading() {
        Self.seen.append(request)
        Self.bodies.append(Self.body(of: request))
        let (code, data) = Self.handler?(request) ?? (500, Data())
        let resp = HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}

    private static func body(of request: URLRequest) -> Data {
        if let data = request.httpBody { return data }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let n = stream.read(&buffer, maxLength: buffer.count)
            if n <= 0 { break }
            data.append(buffer, count: n)
        }
        return data
    }
}

final class StatusClientTests: XCTestCase {
    private func client() -> StatusClient {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [StubProtocol.self]
        StubProtocol.seen = []
        StubProtocol.bodies = []
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

    static let aiJSON = #"{"backend":"api","choice":"auto","cap_usd":5.0,"month_cost_usd":1.2,"paused":false,"reason":null}"#

    func testGetAISettings() async throws {
        StubProtocol.handler = { _ in (200, Data(Self.aiJSON.utf8)) }
        let ai = try await client().aiSettings()
        XCTAssertEqual(ai.backend, "api")
        XCTAssertEqual(ai.choice, .auto)
        XCTAssertEqual(ai.capUSD, 5.0)
        XCTAssertEqual(ai.monthCostUSD, 1.2)
        XCTAssertFalse(ai.paused)
        XCTAssertNil(ai.reason)
        let req = try XCTUnwrap(StubProtocol.seen.first)
        XCTAssertEqual(req.httpMethod, "GET")
        XCTAssertEqual(req.url?.path, "/api/ai")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer 1234-5678-9012")
    }

    func testPutAISendsOnlyWhatChanged() async throws {
        StubProtocol.handler = { _ in (200, Data(Self.aiJSON.utf8)) }
        let c = client()
        _ = try await c.setAI(choice: .api)
        _ = try await c.setAI(capUSD: 7.5)
        XCTAssertEqual(StubProtocol.seen.map(\.httpMethod), ["PUT", "PUT"])
        XCTAssertEqual(StubProtocol.seen.first?.url?.path, "/api/ai")
        XCTAssertEqual(StubProtocol.seen.first?.value(forHTTPHeaderField: "Content-Type"), "application/json")
        let first = try JSONSerialization.jsonObject(with: StubProtocol.bodies[0]) as? [String: Any]
        XCTAssertEqual(first?["backend"] as? String, "api")
        XCTAssertNil(first?["cap_usd"])
        let second = try JSONSerialization.jsonObject(with: StubProtocol.bodies[1]) as? [String: Any]
        XCTAssertEqual(second?["cap_usd"] as? Double, 7.5)
        XCTAssertNil(second?["backend"])
    }

    func testCheckAIPostsOnceAndReturnsTheMessage() async throws {
        StubProtocol.handler = { _ in
            (200, Data(#"{"ok":false,"backend":"off","message":"AI is off: no API key is set"}"#.utf8))
        }
        let check = try await client().checkAI()
        XCTAssertFalse(check.ok)
        XCTAssertEqual(check.message, "AI is off: no API key is set")
        XCTAssertEqual(StubProtocol.seen.count, 1)
        XCTAssertEqual(StubProtocol.seen.first?.httpMethod, "POST")
        XCTAssertEqual(StubProtocol.seen.first?.url?.path, "/api/ai/check")
        // The check makes one real model call, so it waits longer than a status call.
        XCTAssertGreaterThanOrEqual(StubProtocol.seen.first?.timeoutInterval ?? 0, 60)
    }

    func testRefusedAICallThrowsOnceWithoutRetrying() async {
        StubProtocol.handler = { _ in (401, Data()) }
        do { _ = try await client().setAI(choice: .off); XCTFail("expected throw") } catch {
            XCTAssertEqual((error as? StatusClient.HTTPError)?.status, 401)
        }
        XCTAssertEqual(StubProtocol.seen.count, 1)
    }

    func testHTTPErrorThrows() async {
        StubProtocol.handler = { _ in (401, Data()) }
        do { _ = try await client().status(); XCTFail("expected throw") } catch {}
    }
}
