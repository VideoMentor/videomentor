import XCTest
@testable import VideoMentorCore

final class PairLinkTests: XCTestCase {
    func testReadsDNSNameAndDropsTrailingDot() {
        let json = #"{"Version":"1.2","Self":{"DNSName":"my-mac.tail0000.ts.net.","HostName":"my-mac"}}"#
        XCTAssertEqual(PairLink.tailscaleName(fromStatusJSON: Data(json.utf8)), "my-mac.tail0000.ts.net")
    }

    func testBadJSONGivesNil() {
        XCTAssertNil(PairLink.tailscaleName(fromStatusJSON: Data("nope".utf8)))
        XCTAssertNil(PairLink.tailscaleName(fromStatusJSON: Data(#"{"Self":{}}"#.utf8)))
    }

    func testLinksUseTailscaleNameForPhone() {
        let l = PairLink.links(port: 8791, code: "1234-5678-9012", tailscaleName: "my-mac.tail0000.ts.net")
        XCTAssertEqual(l.phone?.absoluteString, "https://my-mac.tail0000.ts.net/pair?code=1234-5678-9012")
        XCTAssertEqual(l.mac.absoluteString, "http://127.0.0.1:8791/pair?code=1234-5678-9012")
    }

    func testLinksFallBackToMacOnlyWithoutTailscale() {
        let l = PairLink.links(port: 8791, code: "1234-5678-9012", tailscaleName: nil)
        XCTAssertNil(l.phone)
        XCTAssertEqual(l.mac.absoluteString, "http://127.0.0.1:8791/pair?code=1234-5678-9012")
    }
}
