import XCTest
@testable import VideoMentorCore

final class QRCodeTests: XCTestCase {
    func testMakesASquareImage() throws {
        let img = try XCTUnwrap(QRCode.image(for: URL(string: "https://example.com/pair?code=1234")!, size: 200))
        XCTAssertEqual(img.size.width, 200)
        XCTAssertEqual(img.size.height, 200)
    }
}
