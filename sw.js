/* MomSakhi service worker: makes the app installable and opens the shell fast.
 *
 * WHAT IT DOES (and deliberately does NOT do):
 * - Caches ONLY the same-origin app shell (index.html, the ?v= versioned
 *   scripts/CSS, manifest, icons) so the home-screen app starts quickly.
 * - NEVER touches cross-origin requests: Firebase/Firestore, Google sign-in,
 *   gstatic SDK bundles, Google Fonts all go straight to the network. The live
 *   Firestore feed (long-lived streaming channels) must stay live and
 *   uncached, and sign-in must never be served from a cache.
 * - HTML (navigations) is network-first: a new deploy is picked up on the very
 *   next open; the cached copy is only an offline fallback.
 * - ?v= assets are cache-first: their URL changes on every cache bump, so a
 *   cached copy can never be stale.
 *
 * UPDATES: VERSION must equal the ?v= string in index.html (a unit test
 * enforces it). Bumping it changes this file's bytes, so the browser installs
 * the new worker; skipWaiting + clients.claim make it take over immediately
 * and old shell caches are deleted on activate.
 */
var VERSION = "d2bf852";
var CACHE = "momsakhi-shell-" + VERSION;
var SHELL = [
  "./",
  "index.html",
  "styles.css?v=" + VERSION,
  "data.js?v=" + VERSION,
  "firebase-config.js?v=" + VERSION,
  "backend.js?v=" + VERSION,
  "app.js?v=" + VERSION,
  "privacy/",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/apple-touch-icon.png"
];
// Belt and braces: even if one of these were ever served same-origin (a proxy,
// an emulator on the same host), the worker must not intercept it.
var NEVER = /firestore|firebase|googleapis|gstatic|google\.com|identitytoolkit|securetoken|__\/auth/i;
// SEO files are for crawlers and link previews (which never run this worker);
// a browser fetching them always gets the deployed bytes, never a cached copy.
var SEO_FILES = /\/(robots\.txt|sitemap\.xml|icons\/og-image\.png)$/;

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) { return cache.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k.indexOf("momsakhi-shell-") === 0 && k !== CACHE) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

function networkFirst(request) {
  return fetch(request).then(function (res) {
    if (res && res.ok) {
      var copy = res.clone();
      caches.open(CACHE).then(function (c) { c.put(request, copy); });
    }
    return res;
  }).catch(function () {
    return caches.match(request, { ignoreSearch: request.mode === "navigate" })
      .then(function (hit) { return hit || caches.match("index.html"); });
  });
}

function cacheFirst(request) {
  return caches.match(request).then(function (hit) {
    return hit || fetch(request).then(function (res) {
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(request, copy); });
      }
      return res;
    });
  });
}

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;  // cross-origin: hands off
  if (NEVER.test(url.pathname + url.search)) return;
  if (SEO_FILES.test(url.pathname)) return;
  var isHtml = req.mode === "navigate" || (req.headers.get("accept") || "").indexOf("text/html") >= 0;
  if (isHtml) { event.respondWith(networkFirst(req)); return; }
  if (url.search.indexOf("v=") >= 0) { event.respondWith(cacheFirst(req)); return; }
  event.respondWith(networkFirst(req));
});
