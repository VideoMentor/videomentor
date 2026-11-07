// VideoMentor service worker. Hand-written, no build step.
// - HTML (navigations): network first, falls back to the cached shell.
// - Hashed build assets (/assets/*): cache first. They are immutable.
// - YouTube thumbnails (i.ytimg.com): cache first, trimmed to MAX_THUMBS.
// - /api and /pair: never touched; they always go to the network.
// Bump VERSION to drop old shell and asset caches.
const VERSION = 'v1';
const SHELL = `vm-shell-${VERSION}`;
const ASSETS = `vm-assets-${VERSION}`;
const THUMBS = 'vm-thumbs';
const MAX_THUMBS = 400;
const NAV_TIMEOUT_MS = 4000;
const SHELL_URLS = ['/', '/manifest.webmanifest', '/icons/icon-180.png', '/icons/icon-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const shell = await caches.open(SHELL);
      await shell.addAll(SHELL_URLS);
      // Pre-cache the hashed bundles the current index.html points at, so the
      // app opens offline even if the first visit happened before the worker
      // was controlling the page.
      const html = await (await shell.match('/')).text();
      const assetUrls = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
      if (assetUrls.length) await (await caches.open(ASSETS)).addAll(assetUrls);
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL, ASSETS, THUMBS]);
      for (const key of await caches.keys()) {
        if (key.startsWith('vm-') && !keep.has(key)) await caches.delete(key);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith('/api') || url.pathname.startsWith('/pair')) return;
    if (req.mode === 'navigate') {
      event.respondWith(networkFirstShell(req));
      return;
    }
    if (url.pathname.startsWith('/assets/')) {
      event.respondWith(cacheFirst(req, ASSETS));
      return;
    }
    event.respondWith(networkFirst(req, SHELL));
    return;
  }

  if (url.hostname === 'i.ytimg.com') {
    event.respondWith(cacheFirst(req, THUMBS, MAX_THUMBS));
  }
});

function timeout(ms) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), ms));
}

async function networkFirstShell(req) {
  const cache = await caches.open(SHELL);
  try {
    const res = await Promise.race([fetch(req), timeout(NAV_TIMEOUT_MS)]);
    if (res.ok) {
      cache.put('/', res.clone());
      return res;
    }
    // A redirect or error page from the server: pass it through.
    return res;
  } catch (err) {
    const cached = (await cache.match('/')) || (await cache.match(req));
    if (cached) return cached;
    throw err;
  }
}

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const cached = await cache.match(req);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirst(req, cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) return cached;
  const res = await fetch(req);
  // Thumbnails load as no-cors images, so their responses are opaque.
  if (res.ok || res.type === 'opaque') {
    await cache.put(req, res.clone());
    if (maxEntries) trim(cache, maxEntries);
  }
  return res;
}

async function trim(cache, maxEntries) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - maxEntries; i++) await cache.delete(keys[i]);
}
