import XCTest
@testable import VideoMentorCore

final class EngineEnvTests: XCTestCase {
    private let base = ["PATH": "/usr/bin", "VM_HOME": "/Users/me/VideoMentor"]

    func testAddsTheKeyWhenOneExists() {
        let env = childEnvironment(base: base, key: "sk-ant-x")
        XCTAssertEqual(env["ANTHROPIC_API_KEY"], "sk-ant-x")
        XCTAssertEqual(env["PATH"], "/usr/bin")
        XCTAssertEqual(env.count, 3)
    }

    func testLeavesTheEnvironmentAloneWithoutAKey() {
        XCTAssertEqual(childEnvironment(base: base, key: nil), base)
        XCTAssertEqual(childEnvironment(base: base, key: ""), base)
    }

    func testTheSavedKeyWinsOverAnInheritedOne() {
        let env = childEnvironment(base: base.merging(["ANTHROPIC_API_KEY": "old"]) { a, _ in a }, key: "new")
        XCTAssertEqual(env["ANTHROPIC_API_KEY"], "new")
    }
}
