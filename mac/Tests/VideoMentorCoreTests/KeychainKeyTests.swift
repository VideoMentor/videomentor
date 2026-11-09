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

    func testLookUpTellsMissingFromSaved() throws {
        XCTAssertEqual(KeychainKey.lookUp(service: service), .missing)
        try KeychainKey.save("sk-ant-x", service: service)
        XCTAssertEqual(KeychainKey.lookUp(service: service), .found("sk-ant-x"))
    }

    func testStatusMapping() {
        XCTAssertEqual(KeychainKey.result(status: errSecSuccess, data: Data("k".utf8)), .found("k"))
        XCTAssertEqual(KeychainKey.result(status: errSecSuccess, data: Data()), .missing)
        XCTAssertEqual(KeychainKey.result(status: errSecSuccess, data: nil), .missing)
        XCTAssertEqual(KeychainKey.result(status: errSecItemNotFound, data: nil), .missing)
        // Locked keychain, no UI allowed, refused access: the key may exist but can't be read.
        XCTAssertEqual(KeychainKey.result(status: errSecInteractionNotAllowed, data: nil), .unreadable(-25308))
        XCTAssertEqual(KeychainKey.result(status: errSecAuthFailed, data: nil), .unreadable(errSecAuthFailed))
        XCTAssertEqual(KeychainKey.result(status: errSecInteractionNotAllowed, data: Data("k".utf8)), .unreadable(-25308))
    }

    func testUnreadableText() {
        XCTAssertNil(KeychainKey.Lookup.found("k").unreadableText)
        XCTAssertNil(KeychainKey.Lookup.missing.unreadableText)
        XCTAssertEqual(KeychainKey.Lookup.unreadable(-25308).unreadableText,
                       "Can't read the keychain (status -25308). Unlock it or check your Mac's security settings.")
        XCTAssertEqual(KeychainKey.Lookup.found("k").key, "k")
        XCTAssertNil(KeychainKey.Lookup.unreadable(-1).key)
    }
}
