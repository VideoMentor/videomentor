import XCTest
@testable import VideoMentorCore

/// Uses a test-only service so the real `org.videomentor.mac` item is never touched.
final class KeychainKeyTests: XCTestCase {
    private let service = "org.videomentor.mac.tests.\(UUID().uuidString)"

    override func tearDown() {
        try? KeychainKey.delete(service: service)
        super.tearDown()
    }

    func testRealServiceAndAccount() {
        XCTAssertEqual(KeychainKey.defaultService, "org.videomentor.mac")
        XCTAssertEqual(KeychainKey.account, "anthropic-api-key")
    }

    func testSaveReadDeleteRoundTrip() throws {
        XCTAssertNil(KeychainKey.read(service: service))
        try KeychainKey.save("sk-ant-test-one", service: service)
        XCTAssertEqual(KeychainKey.read(service: service), "sk-ant-test-one")
        // Saving again replaces the key.
        try KeychainKey.save("  sk-ant-test-two\n", service: service)
        XCTAssertEqual(KeychainKey.read(service: service), "sk-ant-test-two")
        try KeychainKey.delete(service: service)
        XCTAssertNil(KeychainKey.read(service: service))
    }

    func testDeleteWithNothingSavedIsFine() throws {
        try KeychainKey.delete(service: service)
    }

    func testEmptyKeyIsRefused() {
        XCTAssertThrowsError(try KeychainKey.save("   ", service: service))
        XCTAssertNil(KeychainKey.read(service: service))
    }
}
