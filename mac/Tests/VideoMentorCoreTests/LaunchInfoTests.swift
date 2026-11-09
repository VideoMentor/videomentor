import XCTest
@testable import VideoMentorCore

final class LaunchInfoTests: XCTestCase {
    static let json = """
    {
      "program": "/Users/chris/.local/bin/vm",
      "args": ["serve"],
      "env": {
        "PATH": "/Users/chris/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "VM_HOME": "/Users/chris/VideoMentor",
        "VM_WEB_DIST": "/Users/chris/VideoMentor/web",
        "PYTHONUNBUFFERED": "1"
      },
      "log": "/Users/chris/VideoMentor/logs/serve.log",
      "port": 8791,
      "host": "127.0.0.1",
      "pair_code": "1234-5678-9012",
      "version": "0.14.0",
      "build": "9BA1F24E.007"
    }
    """

    func testDecodesEngineJSON() throws {
        let info = try JSONDecoder().decode(LaunchInfo.self, from: Data(Self.json.utf8))
        XCTAssertEqual(info.program, "/Users/chris/.local/bin/vm")
        XCTAssertEqual(info.args, ["serve"])
        XCTAssertEqual(info.env["VM_HOME"], "/Users/chris/VideoMentor")
        XCTAssertEqual(info.env.count, 4)
        XCTAssertEqual(info.log, "/Users/chris/VideoMentor/logs/serve.log")
        XCTAssertEqual(info.port, 8791)
        XCTAssertEqual(info.host, "127.0.0.1")
        XCTAssertEqual(info.pairCode, "1234-5678-9012")
        XCTAssertEqual(info.version, "0.14.0")
        XCTAssertEqual(info.build, "9BA1F24E.007")
    }
}
