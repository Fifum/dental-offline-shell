/* The app works without the network: its files are kept here, the data is in IndexedDB (app.js).
   3.19: the same file serves the app through the internet (Vercel, at /) and the app on the clinic's Wi-Fi (the computer of the
   clinic, at /s/) — every path is taken from where this file itself lives. */
const V = "dd-stock-8";
const BASE = self.location.pathname.replace(/sw\.js$/, "");
const SHELL = ["", "index.html", "styles.css", "app.js", "config.js", "manifest.webmanifest", "icons/icon.svg",
  "icons/icon-192.png", "fonts/inter-latin-400-normal.woff2", "fonts/inter-cyrillic-400-normal.woff2",
  "fonts/inter-latin-600-normal.woff2", "fonts/inter-cyrillic-600-normal.woff2", "fonts/inter-latin-700-normal.woff2",
  "fonts/inter-cyrillic-700-normal.woff2"].map((x) => BASE + x);
// the pages that are the app itself (one index.html): its start, /e/<инв. №>, /m/<номер>, /j; others (/s/ca) are pages of their own
const appPage = (p) => p === BASE || p === BASE + "index.html" || /^(e|m)\/[^/]/.test(p.slice(BASE.length)) || /^j\/?$/.test(p.slice(BASE.length));
self.addEventListener("install", (e) => e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys()
  .then((ks) => Promise.all(ks.filter((k) => k !== V).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET") return;
  if (u.origin === location.origin) {
    if (!u.pathname.startsWith(BASE) || u.pathname.startsWith(BASE + "api/")) return;
    if (r.mode === "navigate") {
      // the app's pages are the one index.html: the network first, so a new version arrives at once
      if (appPage(u.pathname)) {
        e.respondWith(fetch(r).then((x) => { const c = x.clone(); if (x.ok) caches.open(V).then((k) => k.put(BASE + "index.html", c)); return x; })
          .catch(() => caches.match(BASE + "index.html")));
      }
      return;  // another page (the certificate's): straight from the network
    }
    // the app's files: the network first (a new version works at the first open), the cache without the network;
    // fonts and icons do not change — from the cache
    const fresh = () => fetch(r).then((x) => { if (x.ok) { const c = x.clone(); caches.open(V).then((k) => k.put(r, c)); } return x; });
    const rel = u.pathname.slice(BASE.length);
    e.respondWith(/^(fonts|icons)\//.test(rel) ? caches.match(r).then((hit) => hit || fresh())
      : fresh().catch(() => caches.match(r)));
  } else if (/(^|\.)jsdelivr\.net$/.test(u.hostname)) {
    // the scanner polyfill and its wasm: versioned URLs, kept forever
    e.respondWith(caches.match(r).then((hit) => hit || fetch(r).then((x) => {
      if (x.ok) { const c = x.clone(); caches.open(V).then((k) => k.put(r, c)); }
      return x;
    })));
  }
});
