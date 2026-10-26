// Notifications only: no fetch handler, so this worker never runs for page loads.
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
