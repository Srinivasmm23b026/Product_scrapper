const CACHE = "procurement-v1";
const SHELL = ["/static/app.css", "/static/app.js", "/static/manifest.webmanifest"];
self.addEventListener("install", event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener("fetch", event => {
  if (event.request.method === "GET" && new URL(event.request.url).pathname.startsWith("/static/")) {
    event.respondWith(caches.match(event.request).then(hit => hit || fetch(event.request)));
  }
});
