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

    /// The saved key, or nil when there is none (or the keychain can't be read).
    /// Blocks briefly; call it off the main thread.
    public static func read(service: String = defaultService) -> String? {
        var q = query(service)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data,
              let key = String(data: data, encoding: .utf8), !key.isEmpty
        else { return nil }
        return key
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
