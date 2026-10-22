// Inside the installed app only (Chrome's app view or the app's own WebView), remember this page
// so the next launch reopens it.
const goodmorningInApp = matchMedia('(display-mode: standalone)').matches || navigator.userAgent.includes('GoodMorningApp/');
if (goodmorningInApp) {
  document.cookie = 'GoodMorningAppPage=' + encodeURIComponent(location.pathname) + '; Path=/; Secure; SameSite=Strict; Max-Age=31536000';
}

// Notifications belong to each device: a browser through Web Push, a phone without it through the
// linked GoodMorning app. The service worker is registered only while this browser has them on.
let goodmorningBeforeSignOut;
(() => {
  const form = document.querySelector('#notification-form');
  const others = document.querySelector('#notification-devices');
  if (!form) return;
  const t = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
  const pushable = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  // The app's own WebView has no Web Push; once linked, the app posts notifications itself and names its link.
  const inApp = navigator.userAgent.includes('GoodMorningApp/');
  const ownLink = (navigator.userAgent.match(/GoodMorningLink\/([a-f0-9]{16})/) || [])[1];
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;
  const status = form.querySelector('#notification-status');
  const device = form.querySelector('#notification-device');
  const choices = form.querySelector('#notification-choices');
  const feedback = form.querySelector('#notification-feedback');
  const lead = form.querySelector('#notification-lead');
  const kinds = ['briefing', 'waiting', 'chat', 'events'];
  let state = {devices: [], links: []};
  let here = null;  // {device: id} or {link: id} while this device gets notifications.

  const post = async (path, body) => {
    const response = await fetch(path, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': csrf}, body: JSON.stringify(body)});
    const value = await goodmorningJSON(response);
    if (!response.ok) throw new Error(value.error || t('Notification settings could not be saved. Try again.'));
    return value;
  };
  const load = async () => {
    const response = await fetch('/api/push', {credentials: 'same-origin', cache: 'no-store'});
    const value = await goodmorningJSON(response);
    if (!response.ok) throw new Error(value.error);
    state = value;
  };
  const current = async () => {
    const registration = await navigator.serviceWorker.getRegistration('/');
    return registration && await registration.pushManager.getSubscription();
  };
  const key = () => Uint8Array.from(atob(state.publicKey.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
  // The server names a subscription by the start of its endpoint's SHA-256, so the endpoint stays private.
  const deviceName = async endpoint => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint)))]
    .map(byte => byte.toString(16).padStart(2, '0')).join('').slice(0, 16);
  const browserName = () => {
    const agent = navigator.userAgent;
    const browser = /Edg\//.test(agent) ? 'Edge' : /Firefox\//.test(agent) ? 'Firefox' : /Chrome\//.test(agent) ? 'Chrome' : /Safari\//.test(agent) ? 'Safari' : 'Browser';
    const system = /Android/.test(agent) ? 'Android' : /iPhone|iPad/.test(agent) ? 'iOS' : /Windows/.test(agent) ? 'Windows'
      : /Mac OS/.test(agent) ? 'macOS' : /CrOS/.test(agent) ? 'ChromeOS' : /Linux/.test(agent) ? 'Linux' : '';
    const name = matchMedia('(display-mode: standalone)').matches ? 'GoodMorning app' : browser;
    return system ? t('{name} on {system}', {name, system}) : name;
  };
  const settingsOf = place => (place.device ? state.devices.find(item => item.id === place.device)
    : state.links.find(item => item.id === place.link)).settings;

  async function locate() {
    if (!pushable) return ownLink && state.links.some(item => item.id === ownLink) ? {link: ownLink} : null;
    const subscription = await current();
    if (!subscription) return null;
    const name = await deviceName(subscription.endpoint);
    return state.devices.some(item => item.id === name) ? {device: name} : null;
  }

  async function show() {
    here = await locate();
    choices.hidden = !here;
    if (here) {
      const chosen = settingsOf(here);
      kinds.forEach(name => { form.elements[name].checked = chosen[name]; });
      lead.value = String(chosen.lead);
    }
    if (!pushable) {
      device.hidden = true;
      status.textContent = here ? t('This phone gets notifications from the GoodMorning app, up to about 15 minutes late.')
        : t('Link this phone in Account → Linked phones to get notifications here.');
    } else {
      device.hidden = Notification.permission === 'denied';
      if (Notification.permission === 'denied') status.textContent = t('Notifications are blocked for this site. Allow them in your browser or app settings, then reload.');
      else status.textContent = t(here ? 'Notifications are on for this device.' : 'Notifications are off for this device.');
      device.textContent = t(here ? 'Turn off for this device' : 'Turn on for this device');
    }
    showOthers();
  }

  // Account lists every device that gets notifications, so a lost or unused one can be stopped.
  function showOthers() {
    if (!others) return;
    const list = others.querySelector('#notification-device-list');
    const items = [
      ...state.devices.map(item => ({...item, place: {device: item.id}})),
      ...state.links.filter(item => item.notifies && kinds.some(name => item.settings[name])).map(item => ({...item, place: {link: item.id}}))];
    list.replaceChildren(...items.map(item => {
      const row = document.createElement('li');
      const name = document.createElement('span');
      const mine = here && (here.device || here.link) === item.id;
      name.textContent = mine ? t('{name} (this device)', {name: item.label}) : item.label;
      if (item.created) {
        const when = document.createElement('small');
        when.textContent = t('Added {date}', {date: new Date(item.created * 1000).toLocaleDateString()});
        name.append(when);
      }
      const off = document.createElement('button');
      off.type = 'button';
      off.textContent = t('Turn off');
      off.addEventListener('click', async () => {
        off.disabled = true;
        try {
          if (mine && item.place.device) await turnOff();
          else if (item.place.device) await post('/api/push/unsubscribe', item.place);
          else await post('/api/push/settings', {...item.place, settings: {...item.settings, ...Object.fromEntries(kinds.map(kind => [kind, false]))}});
          await load(); await show();
          others.querySelector('#notification-devices-feedback').textContent = t('Notifications turned off for {name}.', {name: item.label});
        } catch (error) { others.querySelector('#notification-devices-feedback').textContent = error.message; off.disabled = false; }
      });
      row.append(name, off);
      return row;
    }));
    others.hidden = !items.length;
  }

  async function turnOn() {
    if (await Notification.requestPermission() !== 'granted') return;
    const registration = await navigator.serviceWorker.register('/sw.js');
    try {
      await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key()});
      await post('/api/push/subscribe', {subscription: subscription.toJSON(), label: browserName()});
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
    const on = Boolean(here);
    try { await (on ? turnOff() : turnOn()); }
    catch { feedback.textContent = t(on ? 'Notifications could not be turned off. Try again.' : 'Notifications could not be turned on for this device. Try again later.'); }
    finally { device.disabled = false; await load().catch(() => {}); await show(); }
  });

  form.addEventListener('change', async () => {
    if (!here) return;
    const settings = Object.fromEntries(kinds.map(name => [name, form.elements[name].checked]));
    settings.lead = Number(lead.value);
    feedback.textContent = '';
    try { await post('/api/push/settings', {...here, settings}); feedback.textContent = t('Notification settings saved.'); await load(); showOthers(); }
    catch (error) { feedback.textContent = error.message; }
  });

  goodmorningBeforeSignOut = async () => {
    if (!pushable) return;
    try { await turnOff(); } catch { /* Signing out must still work offline. */ }
  };

  // Linking or unlinking a phone changes which phones can get notifications.
  document.addEventListener('goodmorning:phones', async () => { try { await load(); await show(); } catch { /* Keep what is shown. */ } });

  (async () => {
    try {
      await load();
      await show();
      // Notifications show only where they can work.
      if (pushable || inApp) form.hidden = false;
    } catch { /* Without the server's answer the sections stay hidden. */ }
  })();
})();

// Linked phones: the owner types (or pastes) the code the Android app shows, or the app opens this
// page with it filled in; linked phones can be removed.
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
  // ABCD-2345: letters and digits only, the dash added after the first four.
  const format = (value, typing) => {
    const raw = value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8);
    return raw.length > 4 || (raw.length === 4 && typing) ? raw.slice(0, 4) + '-' + raw.slice(4) : raw;
  };
  code.addEventListener('input', event => { code.value = format(code.value, !event.inputType?.startsWith('delete')); });
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
        try {
          show((await post('/api/app/unlink', {id: link.id})).links);
          feedback.textContent = t('Phone unlinked. Its widgets stop updating.');
          document.dispatchEvent(new Event('goodmorning:phones'));
        } catch (error) { feedback.textContent = error.message; remove.disabled = false; }
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
      // The phone collects its token a few seconds later; then it appears in the list.
      for (let attempt = 0; attempt < 10; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 3000));
        const response = await fetch('/api/app/links', {credentials: 'same-origin', cache: 'no-store'});
        const links = response.ok ? (await goodmorningJSON(response)).links : [];
        if (links.length > value.links.length) { show(links); document.dispatchEvent(new Event('goodmorning:phones')); break; }
      }
    } catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
  (async () => {
    try {
      const response = await fetch('/api/app/links', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      show((await goodmorningJSON(response)).links);
      form.hidden = false;
      // The app's "Link in GoodMorning" opens a page with ?link=CODE: fill it in for the owner to confirm.
      const address = new URL(location.href);
      const offered = address.searchParams.get('link');
      if (offered) {
        address.searchParams.delete('link');
        history.replaceState(history.state, '', address.pathname + address.search + address.hash);
        code.value = format(offered, false);
        const menu = form.closest('details.menu');
        if (menu) menu.open = true;
        form.scrollIntoView({block: 'center'});
        form.querySelector('button[type="submit"]').focus({preventScroll: true});
        feedback.textContent = t('Check that this code matches the app, then tap Link phone.');
      }
    } catch { /* Without the server's answer the section stays hidden. */ }
  })();
})();
