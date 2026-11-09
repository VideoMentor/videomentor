import Foundation
import Security

/// The Anthropic API key, kept as a generic password in the login keychain.
/// The key is never logged; the app passes it to the engine only through the child's environment.
/// `service` is a parameter so tests can use their own item and never touch the real one.
public enum KeychainKey {
    public static let defaultService = "org.videomentor.mac"
    public static let account = "anthropic-api-key"

    public struct KeychainError: Error, LocalizedError {
        public let status: OSStatus
        public var errorDescription: String? {
            let text = SecCopyErrorMessageString(status, nil) as String? ?? "error \(status)"
            return "The keychain refused: \(text)"
        }
    }

    public struct EmptyKey: Error, LocalizedError {
        public var errorDescription: String? { "The key is empty." }
    }

    private static func query(_ service: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    /// What a keychain read found. `unreadable` means the key may exist but the keychain
    /// refused (locked, no UI allowed, access denied by policy): not the same as no key.
    public enum Lookup: Sendable, Equatable {
        case found(String)
        case missing
        case unreadable(OSStatus)

        public var key: String? {
            if case .found(let k) = self { return k }
            return nil
        }

        /// The text for the AI Settings window, or nil when the read worked.
        public var unreadableText: String? {
            guard case .unreadable(let status) = self else { return nil }
            return "Can't read the keychain (status \(status)). Unlock it or check your Mac's security settings."
        }
    }

    /// Maps a `SecItemCopyMatching` result. Pure, so tests can feed it any status.
    static func result(status: OSStatus, data: Data?) -> Lookup {
        switch status {
        case errSecSuccess:
            guard let data, let key = String(data: data, encoding: .utf8), !key.isEmpty else { return .missing }
            return .found(key)
        case errSecItemNotFound:
            return .missing
        default:
            return .unreadable(status)
        }
    }

    /// Reads the saved key, telling a missing key from an unreadable keychain.
    /// Blocks briefly; call it off the main thread.
    public static func lookUp(service: String = defaultService) -> Lookup {
        var q = query(service)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &out)
        return result(status: status, data: out as? Data)
    }

    /// The saved key, or nil when there is none or the keychain can't be read.
    public static func read(service: String = defaultService) -> String? {
        lookUp(service: service).key
    }

    /// Saves the key (trimmed), replacing any saved one.
    public static func save(_ key: String, service: String = defaultService) throws {
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw EmptyKey() }
        let data = Data(trimmed.utf8)
        let base = query(service)
        let updated = SecItemUpdate(base as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if updated == errSecSuccess { return }
        guard updated == errSecItemNotFound else { throw KeychainError(status: updated) }
        var add = base
        add[kSecValueData as String] = data
        add[kSecAttrLabel as String] = "VideoMentor: Anthropic API key"
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(add as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError(status: status) }
    }

    /// Removes the saved key. Nothing saved is not an error.
    public static func delete(service: String = defaultService) throws {
        let status = SecItemDelete(query(service) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
    }
}

/// The engine child's environment: `base`, plus `ANTHROPIC_API_KEY` when a key is saved.
/// Without a key the environment is left as it is.
public func childEnvironment(base: [String: String], key: String?) -> [String: String] {
    guard let key, !key.isEmpty else { return base }
    var env = base
    env["ANTHROPIC_API_KEY"] = key
    return env
}
