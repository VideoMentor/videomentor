import AppKit
import SwiftUI
import VideoMentorCore

/// This Mac's Tailscale name, or nil when Tailscale is missing, stopped or signed out.
enum Tailscale {
    static let candidates = [
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
        "/opt/homebrew/bin/tailscale",
        "/usr/local/bin/tailscale",
    ]

    static func name() async -> String? {
        await Task.detached { lookUp() }.value
    }

    private static func lookUp() -> String? {
        guard let path = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            return nil
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = ["status", "--json"]
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch { return nil }
        // A hung CLI must not hold the window: stop it after 5 s.
        DispatchQueue.global().asyncAfter(deadline: .now() + 5) { if p.isRunning { p.terminate() } }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        guard p.terminationStatus == 0 else { return nil }
        // Signed out or stopped: the JSON may still carry an old name, so check the state too.
        if let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let state = root["BackendState"] as? String, state != "Running" {
            return nil
        }
        return PairLink.tailscaleName(fromStatusJSON: data)
    }
}

/// The QR code, the pairing code and the Mac link.
struct PairView: View {
    let info: LaunchInfo
    @State private var checked = false
    @State private var tailscaleName: String?

    var body: some View {
        let links = PairLink.links(port: info.port, code: info.pairCode, tailscaleName: tailscaleName)
        VStack(spacing: 16) {
            if !checked {
                ProgressView("Checking Tailscale…").frame(width: 280, height: 280)
            } else if let image = QRCode.image(for: links.phone ?? links.mac, size: 280) {
                Image(nsImage: image).interpolation(.none).frame(width: 280, height: 280)
            }
            if checked {
                Text(links.phone != nil
                     ? "Scan this with your iPhone camera to open VideoMentor and pair the phone."
                     : "Tailscale isn't running on this Mac, so this code only works on this Mac. Phones need Tailscale to reach VideoMentor.")
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(spacing: 4) {
                Text("Pairing code").font(.caption).foregroundStyle(.secondary)
                Text(info.pairCode).font(.system(.title2, design: .monospaced)).textSelection(.enabled)
            }
            VStack(spacing: 4) {
                Text("On this Mac").font(.caption).foregroundStyle(.secondary)
                Link(links.mac.absoluteString, destination: links.mac).font(.callout)
            }
        }
        .padding(24)
        .frame(width: 420)
        .task {
            tailscaleName = await Tailscale.name()
            checked = true
        }
    }
}
