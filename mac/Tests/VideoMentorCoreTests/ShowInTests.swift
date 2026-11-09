import XCTest
@testable import VideoMentorCore

final class ShowInTests: XCTestCase {
    func testRawValuesAreStable() {
        // These strings are stored in UserDefaults; changing them would reset everyone's choice.
        XCTAssertEqual(ShowIn.dock.rawValue, "dock")
        XCTAssertEqual(ShowIn.menuBar.rawValue, "menuBar")
        XCTAssertEqual(ShowIn.both.rawValue, "both")
        XCTAssertEqual(ShowIn.allCases, [.dock, .menuBar, .both])
    }

    func testDefaultIsBoth() {
        XCTAssertEqual(ShowIn.defaultValue, .both)
        XCTAssertEqual(ShowIn.defaultsKey, "showIn")
    }

    func testParsesStoredValues() {
        XCTAssertEqual(ShowIn(stored: "dock"), .dock)
        XCTAssertEqual(ShowIn(stored: "menuBar"), .menuBar)
        XCTAssertEqual(ShowIn(stored: "both"), .both)
    }

    func testUnknownOrMissingFallsBackToBoth() {
        XCTAssertEqual(ShowIn(stored: nil), .both)
        XCTAssertEqual(ShowIn(stored: ""), .both)
        XCTAssertEqual(ShowIn(stored: "Dock"), .both)
        XCTAssertEqual(ShowIn(stored: "menubar"), .both)
        XCTAssertEqual(ShowIn(stored: "neither"), .both)
    }

    func testDerivedFlags() {
        XCTAssertTrue(ShowIn.dock.showsDockIcon)
        XCTAssertFalse(ShowIn.dock.showsMenuBarItem)
        XCTAssertFalse(ShowIn.menuBar.showsDockIcon)
        XCTAssertTrue(ShowIn.menuBar.showsMenuBarItem)
        XCTAssertTrue(ShowIn.both.showsDockIcon)
        XCTAssertTrue(ShowIn.both.showsMenuBarItem)
    }

    func testEveryModeShowsAtLeastOne() {
        for mode in ShowIn.allCases {
            XCTAssertTrue(mode.showsDockIcon || mode.showsMenuBarItem, "\(mode) would hide the app")
        }
    }

    func testTitles() {
        XCTAssertEqual(ShowIn.allCases.map(\.title), ["Dock", "Menu Bar", "Both"])
    }
}
