import Foundation

/// What `vm launch-info --json` prints: how to start the engine and how to reach it.
public struct LaunchInfo: Decodable, Sendable, Equatable {
    public let program: String
    public let args: [String]
    public let env: [String: String]
    public let log: String
    public let port: Int
    public let host: String
    public let pairCode: String
    public let version: String
    public let build: String

    enum CodingKeys: String, CodingKey {
        case program, args, env, log, port, host, version, build
        case pairCode = "pair_code"
    }

    public struct LoadError: Error, LocalizedError {
        public let message: String
        public var errorDescription: String? { message }
    }

    /// Runs `<vm> launch-info --json` and decodes its output.
    public static func load(vm: URL) throws -> LaunchInfo {
        let process = Process()
        process.executableURL = vm
        process.arguments = ["launch-info", "--json"]
        let out = Pipe()
        process.standardOutput = out
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = out.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw LoadError(message: "vm launch-info failed (exit \(process.terminationStatus))")
        }
        return try JSONDecoder().decode(LaunchInfo.self, from: data)
    }
}
