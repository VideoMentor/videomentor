import AppKit
import SwiftUI
import WebKit

/// One WKWebView for the app's lifetime, with the default (persistent) data store, so the
/// `vm_session` cookie survives both closing the window and quitting the app.
/// Pairs at most once: `/pair?code=…` loads only when the store has no session cookie.
@MainActor
final class WebModel: NSObject, WKNavigationDelegate, WKUIDelegate {
    static let cookieName = "vm_session"

    private(set) lazy var webView: WKWebView = {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = self
        view.uiDelegate = self
        view.allowsBackForwardNavigationGestures = true
        return view
    }()

    private var host = "127.0.0.1"
    private var loaded = false
    private var loading = false

    /// Loads the app the first time the window opens, and again only if that load failed.
    func ensureLoaded(host: String, port: Int, pairCode: String) {
        guard !loaded, !loading else { return }
        self.host = host
        loading = true
        let store = webView.configuration.websiteDataStore.httpCookieStore
        Task {
            let cookies = await store.allCookies()
            let paired = cookies.contains { Self.isSession($0, host: host) }
            let path = paired ? "/" : "/pair?code=\(pairCode)"
            guard let url = URL(string: "http://\(host):\(port)\(path)") else { loading = false; return }
            webView.load(URLRequest(url: url))
        }
    }

    static func isSession(_ cookie: HTTPCookie, host: String) -> Bool {
        guard cookie.name == cookieName else { return false }
        let domain = cookie.domain.hasPrefix(".") ? String(cookie.domain.dropFirst()) : cookie.domain
        guard domain == host else { return false }
        if let expires = cookie.expiresDate, expires < Date() { return false }
        return true
    }

    // MARK: WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loading = false
        // The "not answering" note is about:blank; only a page from the engine counts.
        if webView.url?.host == host { loaded = true }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        loading = false
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        loading = false
        // The engine isn't answering yet: show a short note; the next open tries again.
        webView.loadHTMLString(
            "<body style='font:15px -apple-system;padding:2em;color:#555'>"
                + "VideoMentor isn't answering yet. Close this window and open it again in a moment.</body>",
            baseURL: nil)
    }

    /// Links to other sites (YouTube and the like) open in the default browser.
    func webView(
        _ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        // Main frame only: embedded players (YouTube iframes) stay in the page.
        if action.targetFrame?.isMainFrame == true, let url = action.request.url,
           let scheme = url.scheme, scheme.hasPrefix("http"), url.host != host {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    // MARK: WKUIDelegate

    /// `target=_blank` and `window.open` go to the default browser.
    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for action: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }
}

struct WebView: NSViewRepresentable {
    let model: WebModel
    func makeNSView(context: Context) -> WKWebView { model.webView }
    func updateNSView(_ nsView: WKWebView, context: Context) {}
}

/// Keeps the app's two windows around so reopening them is instant and keeps their state.
@MainActor
final class Windows {
    private var web: NSWindow?
    private var pair: NSWindow?

    func showWeb(model: WebModel) {
        if web == nil {
            web = Self.make(title: "VideoMentor", size: NSSize(width: 1100, height: 800),
                            content: NSHostingController(rootView: WebView(model: model)), autosave: "VideoMentorWeb")
        }
        Self.present(web!)
    }

    func showPair<V: View>(_ view: V) {
        if pair == nil {
            pair = Self.make(title: "Pair a Phone", size: NSSize(width: 420, height: 560),
                             content: NSHostingController(rootView: AnyView(view)), autosave: "VideoMentorPair")
        } else {
            // Fresh content each time, so the Tailscale check runs again.
            pair!.contentViewController = NSHostingController(rootView: AnyView(view))
        }
        Self.present(pair!)
    }

    private static func make(title: String, size: NSSize, content: NSViewController, autosave: String) -> NSWindow {
        let window = NSWindow(contentViewController: content)
        window.title = title
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        window.setContentSize(size)
        window.isReleasedWhenClosed = false
        window.center()
        window.setFrameAutosaveName(autosave)
        return window
    }

    private static func present(_ window: NSWindow) {
        if NSApp.activationPolicy() == .regular { MainMenu.ensure() }
        NSApp.activate()
        window.makeKeyAndOrderFront(nil)
    }
}
