// Shows notifications, and keeps the account's latest morning and evening briefings for reading offline.
// The copies live in one cache named after the account's owner tag (briefing_gateway.py), which is deleted
// as soon as the site answers for nobody, or for another account; auth.js also deletes it at sign-out.
const COPIES = ['/offline/gm.html', '/offline/gn.html'];
const PREFIX = 'offline-';
let refreshing = null;

self.addEventListener('install', () => self.skipWaiting());
// The page that registered this worker already loaded, so the first copies are fetched now.
self.addEventListener('activate', event => event.waitUntil(Promise.all([self.clients.claim(), update()])));

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then(response => {
      event.waitUntil(update());
      return response;
    }, () => offline(request)));
  } else if (['style', 'script', 'font', 'image'].includes(request.destination)) {
    // Online, everything comes from the network as before; offline, the copies' own files come from the cache.
    event.respondWith(fetch(request).catch(async () => await (await kept())?.match(request, {ignoreVary: true}) || Response.error()));
  }
});

function update() {
  refreshing = refreshing || refresh().catch(() => {}).finally(() => { refreshing = null; });
  return refreshing;
}

async function kept() {
  const name = (await caches.keys()).find(key => key.startsWith(PREFIX));
  return name && caches.open(name);
}

async function forget(except) {
  for (const name of await caches.keys()) if (name.startsWith(PREFIX) && name !== except) await caches.delete(name);
}

// Briefing pages open their own edition; any other page opens the morning before 17:00, then the evening.
async function offline(request) {
  const cache = await kept();
  const wanted = (new URL(request.url).pathname.match(/(gm|gn)\.html$/) || [])[1] || (new Date().getHours() < 17 ? 'gm' : 'gn');
  for (const path of wanted === 'gm' ? COPIES : [...COPIES].reverse()) {
    const copy = cache && await cache.match(path, {ignoreVary: true});
    if (copy) return copy;
  }
  return Response.error();
}

async function refresh() {
  let cache = await kept();
  for (const path of COPIES) {
    const copy = cache && await cache.match(path, {ignoreVary: true});
    const response = await fetch(path, {cache: 'no-store', redirect: 'manual', headers: copy ? {'If-None-Match': copy.headers.get('ETag')} : {}});
    // A redirect to sign-in or the password page, or a refusal: nobody this device may keep a copy for.
    if (response.type === 'opaqueredirect' || response.status === 401 || response.status === 403) return forget();
    const owner = response.headers.get('X-GoodMorning-Owner');
    if (!owner) return;  // Maintenance or an outage: keep what this device has.
    await forget(PREFIX + owner);
    cache = await caches.open(PREFIX + owner);
    if (response.status === 200) await cache.put(path, response);
    else if (response.status === 404) await cache.delete(path);  // No saved edition this week.
  }
  if (cache) await keepFiles(cache);
}

// Keeps exactly the stylesheets, scripts, icons and images the copies name.
async function keepFiles(cache) {
  const files = new Set();
  for (const path of COPIES) {
    const copy = await cache.match(path, {ignoreVary: true});
    if (copy) for (const [, file] of (await copy.text()).matchAll(/<(?:link|script|img)\b[^>]*?\s(?:href|src)="(\/[^"/][^"]*)"/g)) files.add(file);
  }
  for (const request of await cache.keys()) {
    const url = new URL(request.url);
    if (!COPIES.includes(url.pathname) && !files.has(url.pathname + url.search)) await cache.delete(request);
  }
  for (const file of files) if (!await cache.match(file, {ignoreVary: true})) await cache.add(file).catch(() => {});
}

self.addEventListener('push', event => {
  const message = event.data.json();
  event.waitUntil((async () => {
    // Status updates are already on screen while GoodMorning is in front; reminders always show.
    if (!['events', 'gm', 'gn'].includes(message.kind)) {
      const windows = await clients.matchAll({type: 'window', includeUncontrolled: true});
      if (windows.some(window => window.focused && window.visibilityState === 'visible')) return;
    }
    await self.registration.showNotification(message.title, {
      body: message.body, tag: message.tag, data: {url: message.url}, icon: '/icons/app-192.png'
    });
  })());
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.location.origin);
  if (url.origin !== self.location.origin) return;
  event.waitUntil((async () => {
    // navigate() works only on pages this worker controls, and a click allows a single
    // focus() or openWindow(), so navigate first and spend the click on focus last.
    const open = (await clients.matchAll({type: 'window'})).find(window => 'navigate' in window);
    if (!open) return clients.openWindow(url.href);
    const navigated = await open.navigate(url.href);
    return (navigated || open).focus();
  })());
});
