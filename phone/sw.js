/* The app works without the network: its files are kept here, the data is in IndexedDB (app.js). */
const V = "dd-stock-5";
const SHELL = ["/", "/index.html", "/styles.css", "/app.js", "/config.js", "/manifest.webmanifest", "/icons/icon.svg",
  "/icons/icon-192.png", "/fonts/inter-latin-400-normal.woff2", "/fonts/inter-cyrillic-400-normal.woff2",
  "/fonts/inter-latin-600-normal.woff2", "/fonts/inter-cyrillic-600-normal.woff2", "/fonts/inter-latin-700-normal.woff2",
  "/fonts/inter-cyrillic-700-normal.woff2"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys()
  .then((ks) => Promise.all(ks.filter((k) => k !== V).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET") return;
  if (u.origin === location.origin) {
    // pages (/, /e/<инв. №>, /j) are the one index.html; the network first, so a new version arrives at once
    if (r.mode === "navigate") {
      e.respondWith(fetch(r).then((x) => { const c = x.clone(); caches.open(V).then((k) => k.put("/index.html", c)); return x; })
        .catch(() => caches.match("/index.html")));
      return;
    }
    // the app's files: the network first (a new version works at the first open), the cache without the network;
    // fonts and icons do not change — from the cache
    const fresh = () => fetch(r).then((x) => { if (x.ok) { const c = x.clone(); caches.open(V).then((k) => k.put(r, c)); } return x; });
    e.respondWith(/^\/(fonts|icons)\//.test(u.pathname) ? caches.match(r).then((hit) => hit || fresh())
      : fresh().catch(() => caches.match(r)));
  } else if (/(^|\.)jsdelivr\.net$/.test(u.hostname)) {
    // the scanner polyfill and its wasm: versioned URLs, kept forever
    e.respondWith(caches.match(r).then((hit) => hit || fetch(r).then((x) => {
      if (x.ok) { const c = x.clone(); caches.open(V).then((k) => k.put(r, c)); }
      return x;
    })));
  }
});
