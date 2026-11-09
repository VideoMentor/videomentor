// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "VideoMentorMac",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "VideoMentorCore"),
        .executableTarget(name: "VideoMentorMenu", dependencies: ["VideoMentorCore"]),
        .testTarget(name: "VideoMentorCoreTests", dependencies: ["VideoMentorCore"]),
    ]
)
