// Inside the installed app only, remember this page so the next launch reopens it.
if (matchMedia('(display-mode: standalone)').matches) {
  document.cookie = 'GoodMorningAppPage=' + encodeURIComponent(location.pathname) + '; Path=/; Secure; SameSite=Strict; Max-Age=31536000';
}

// Notifications: the service worker is registered only while this device has them turned on.
let goodmorningBeforeSignOut;
(() => {
  const form = document.querySelector('#notification-form');
  if (!form || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return;
  const t = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;
  const status = form.querySelector('#notification-status');
  const device = form.querySelector('#notification-device');
  const feedback = form.querySelector('#notification-feedback');
  const lead = form.querySelector('#notification-lead');
  const kinds = ['briefing', 'waiting', 'chat', 'events'];
  let publicKey;

  const post = async (path, body) => {
    const response = await fetch(path, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': csrf}, body: JSON.stringify(body)});
    const value = await goodmorningJSON(response);
    if (!response.ok) throw new Error(value.error || t('Notification settings could not be saved. Try again.'));
    return value;
  };
  const current = async () => {
    const registration = await navigator.serviceWorker.getRegistration('/');
    return registration && await registration.pushManager.getSubscription();
  };
  const key = () => Uint8Array.from(atob(publicKey.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));

  async function show() {
    const subscription = await current();
    device.hidden = Notification.permission === 'denied';
    if (Notification.permission === 'denied') status.textContent = t('Notifications are blocked for this site. Allow them in your browser or app settings, then reload.');
    else if (subscription) status.textContent = t('Notifications are on for this device.');
    else status.textContent = t('Notifications are off for this device.');
    device.textContent = t(subscription ? 'Turn off for this device' : 'Turn on for this device');
    device.dataset.on = subscription ? 'true' : '';
  }

  async function turnOn() {
    if (await Notification.requestPermission() !== 'granted') return;
    const registration = await navigator.serviceWorker.register('/sw.js');
    try {
      await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key()});
      await post('/api/push/subscribe', {subscription: subscription.toJSON()});
    } catch (error) {
      await turnOff().catch(() => {});  // Leave nothing half set up.
      throw error;
    }
  }

  async function turnOff() {
    const subscription = await current();
    if (subscription) {
      await post('/api/push/unsubscribe', {endpoint: subscription.endpoint});
      await subscription.unsubscribe();
    }
    const registration = await navigator.serviceWorker.getRegistration('/');
    if (registration) await registration.unregister();
  }

  device.addEventListener('click', async () => {
    device.disabled = true; feedback.textContent = '';
    const on = device.dataset.on;
    try { await (on ? turnOff() : turnOn()); }
    catch { feedback.textContent = t(on ? 'Notifications could not be turned off. Try again.' : 'Notifications could not be turned on for this device. Try again later.'); }
    finally { device.disabled = false; await show(); }
  });

  form.addEventListener('change', async () => {
    const settings = Object.fromEntries(kinds.map(name => [name, form.elements[name].checked]));
    settings.lead = Number(lead.value);
    feedback.textContent = '';
    try { await post('/api/push/settings', {settings}); feedback.textContent = t('Notification settings saved.'); }
    catch (error) { feedback.textContent = error.message; }
  });

  goodmorningBeforeSignOut = async () => {
    try { await turnOff(); } catch { /* Signing out must still work offline. */ }
  };

  (async () => {
    try {
      const response = await fetch('/api/push', {credentials: 'same-origin', cache: 'no-store'});
      const value = await goodmorningJSON(response);
      if (!response.ok) return;
      publicKey = value.publicKey;
      kinds.forEach(name => { form.elements[name].checked = value.settings[name]; });
      lead.value = String(value.settings.lead);
      await show();
      form.hidden = false;
    } catch { /* Without the server's answer the section stays hidden. */ }
  })();
})();

// Phone & widgets: the owner types the code the Android app shows; linked phones can be removed.
(() => {
  const form = document.querySelector('#app-link-form');
  if (!form) return;
  const t = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;
  const list = form.querySelector('#app-links');
  const feedback = form.querySelector('#app-link-feedback');
  const code = form.querySelector('#app-link-code');
  const post = async (path, body) => {
    const response = await fetch(path, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': csrf}, body: JSON.stringify(body)});
    const value = await goodmorningJSON(response);
    if (!response.ok) throw new Error(value.error || t('Phone request could not be read. Update the app or try again.'));
    return value;
  };
  function show(links) {
    list.replaceChildren(...links.map(link => {
      const item = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = link.label;
      const when = document.createElement('small');
      when.textContent = t('Linked {date}', {date: new Date(link.created * 1000).toLocaleDateString()});
      name.append(when);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = t('Unlink');
      remove.addEventListener('click', async () => {
        remove.disabled = true;
        try { show((await post('/api/app/unlink', {id: link.id})).links); feedback.textContent = t('Phone unlinked. Its widgets stop updating.'); }
        catch (error) { feedback.textContent = error.message; remove.disabled = false; }
      });
      item.append(name, remove);
      return item;
    }));
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true; feedback.textContent = '';
    try {
      const value = await post('/api/app/link', {code: code.value});
      show(value.links); code.value = '';
      feedback.textContent = t('{name} is linked. Its widgets update within a minute.', {name: value.label});
    } catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
  (async () => {
    try {
      const response = await fetch('/api/app/links', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      show((await goodmorningJSON(response)).links);
      form.hidden = false;
    } catch { /* Without the server's answer the section stays hidden. */ }
  })();
})();
