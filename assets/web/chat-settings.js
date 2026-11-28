// Website settings the secretary prepared in chat (website_settings.py), shared by the Secretary page
// and Quick Chat. A change runs only on the page that sent its turn: the server gives it only to that
// page's token, once, after the reply ends. It runs through the header pop-ups' own controls, so it
// passes the same checks as a tap. Linking a phone, unlinking one and signing out run only when the
// user taps the card's button.
const goodmorningSettings = (() => {
  const t = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
  const $ = selector => document.querySelector(selector);
  const csrf = () => JSON.parse($('#language-config').dataset.config).csrf;
  const TAP = ['link_phone', 'unlink_phone', 'sign_out'];
  const LOCAL = ['style', 'day_scheme', 'night_scheme', 'widget_theme', 'notifications', 'notifications_here'];
  const NAMES = {style: 'Style', day_scheme: 'Day color scheme', night_scheme: 'Night color scheme', language: 'Website language',
    widget_theme: 'Widget theme', notifications: 'Notification choices', notifications_here: 'Notifications on this device',
    device_notifications_off: 'Turn off notifications', link_phone: 'Link a phone', unlink_phone: 'Unlink a phone',
    sign_out: 'Sign out', open: 'Open', avatar: 'Secretary avatar', avatar_upload: 'Secretary avatar'};
  const VALUES = {soft: 'Soft', pixel: 'Pixel', classic: 'Classic', warm: 'Warm', 'morning-sky': 'Morning Sky', 'first-light': 'First Light',
    'grass-block': 'Grass Block', picnic: 'Picnic', starry: 'Starry', 'city-lights': 'City Lights', 'midnight-violet': 'Midnight Violet',
    clock: 'Day and night by the clock', phone: 'Follow the phone’s dark mode', day: 'Always the day scheme', night: 'Always the night scheme',
    appearance: 'Appearance', notifications: 'Notifications', phones: 'Phones', account: 'Account', password: 'Change password',
    avatar: 'Secretary avatar', download: 'Download the Android app', off: 'Off', custom: 'Your upload'};
  const NOT_CHANGED = 'Not changed. Ask again here, or use the pop-up.';
  const MISSING = 'This setting isn’t available on this page.';

  // This page's own token, sent with its messages and answers. It lives only in memory, so a reload
  // or a duplicated tab is another page and never applies this one's changes.
  const page = [...crypto.getRandomValues(new Uint8Array(16))].map(byte => byte.toString(16).padStart(2, '0')).join('');
  const turns = new Set();
  const states = new Map();
  const owned = action => turns.has(action.from_turn);
  // Only a finished reply: one paused on a question or permission may still change its mind.
  const finished = chat => states.get(chat) === 'idle';

  const resultsKey = chat => 'gm-settings-results:' + chat;
  const results = chat => { try { return JSON.parse(sessionStorage.getItem(resultsKey(chat))) || {}; } catch { return {}; } };
  function keep(chat, seq, text) {
    const all = results(chat); all[seq] = text;
    try { sessionStorage.setItem(resultsKey(chat), JSON.stringify(all)); } catch { /* Shown until reload. */ }
  }
  function forget(chat, seq) {
    const all = results(chat); delete all[seq];
    try { sessionStorage.setItem(resultsKey(chat), JSON.stringify(all)); } catch { /* Shown until reload. */ }
  }

  const label = text => text.normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, '');
  function valueText(setting, value) {
    if (setting === 'language') return {en: 'English', 'zh-CN': '简体中文'}[value] || value;
    if (setting === 'avatar') return /^[fm][12]$/.test(value) ? t('Avatar {number}', {number: ['f1', 'f2', 'm1', 'm2'].indexOf(value) + 1}) : t(VALUES[value] || value);
    if (setting === 'avatar_upload') return t({day: 'Scene · day', night: 'Scene · night', profile: 'Profile'}[value.variant]);
    if (setting === 'notifications') return '';
    if (setting === 'sign_out') return t('This browser');
    return typeof value === 'string' ? t(VALUES[value] || value) : '';
  }
  const title = action => {
    const value = valueText(action.setting, action.value);
    return t(NAMES[action.setting] || 'Website setting') + (value ? ' → ' + value : '');
  };
  const done = setting => t(LOCAL.includes(setting) ? 'Done on this device.' : 'Done.');
  const working = setting => t(LOCAL.includes(setting) ? 'Changing it on this device…' : 'Applying this change…');

  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function until(test, limit = 10000) {
    for (let waited = 0; waited < limit; waited += 150) { if (test()) return true; await pause(150); }
    return Boolean(test());
  }
  const shown = node => node && !node.closest('[hidden]');
  const usable = node => shown(node) && !node.disabled;
  function reveal(node) {
    const menu = node?.closest('details.menu');
    if (!menu) return false;
    menu.open = true;
    node.scrollIntoView?.({block: 'nearest'});
    node.focus?.({preventScroll: true});
    return true;
  }
  // Rows list a device by name, perhaps followed by " (this device)" and a date.
  function rows(list) {
    const mine = t('{name} (this device)', {name: '\u0000'}).split('\u0000');
    return [...document.querySelectorAll(list + ' > li')].map(row => {
      let name = row.querySelector('span')?.firstChild?.textContent.trim() || '';
      const here = mine.length === 2 && name.startsWith(mine[0]) && name.endsWith(mine[1]) && name.length > mine[0].length + mine[1].length;
      if (here) name = name.slice(mine[0].length, name.length - mine[1].length);
      return {row, name, here};
    });
  }
  // Ignoring case and spacing; a unique partial match is enough.
  function find(list, wanted) {
    const all = rows(list);
    const exact = all.filter(item => label(item.name) === label(wanted));
    const partial = all.filter(item => label(item.name).includes(label(wanted)));
    const matches = exact.length ? exact : partial;
    if (matches.length === 1) return matches[0];
    reveal($(list));
    const names = all.map(item => item.name).join(', ');
    throw new Error(matches.length ? t('More than one is called {name}: {names}. Choose it in the pop-up.', {name: wanted, names})
      : all.length ? t('Nothing is called {name}. Listed here: {names}.', {name: wanted, names}) : t('Nothing is listed here yet.'));
  }
  // Acts, then waits for the page to confirm the change or show the pop-up's own error.
  async function act(perform, ok, feedback) {
    const status = feedback && $(feedback);
    const before = status?.textContent;
    if (status) status.textContent = '';
    perform();
    await until(() => ok() || (status && status.textContent.trim() && status.textContent !== before && !ok()), 30000);
    if (ok()) return true;
    throw new Error(status?.textContent.trim() || t('Try again from the pop-up.'));
  }

  async function apply({setting, value}) {
    if (['style', 'day_scheme', 'night_scheme'].includes(setting)) {
      const name = setting.replace('_scheme', '');
      const radio = $(`#color-scheme-form input[name="${name}"][value="${CSS.escape(value)}"]`);
      if (!radio) throw new Error(t(MISSING));
      const key = {style: 'style', day: 'dayScheme', night: 'nightScheme'}[name];
      if (document.documentElement.dataset[key] === value) return;
      // color-schemes.js disables the radios while it saves the previous change.
      await until(() => !radio.disabled);
      await act(() => { radio.checked = true; radio.dispatchEvent(new Event('change', {bubbles: true})); },
        () => document.documentElement.dataset[key] === value && !radio.disabled, '#color-scheme-feedback');
      return;
    }
    if (setting === 'language') {
      const select = $('#website-language');
      if (!select) throw new Error(t(MISSING));
      if (goodmorningLanguage === value) return;
      await until(() => !select.disabled);
      await act(() => { select.value = value; select.dispatchEvent(new Event('change')); },
        () => goodmorningLanguage === value && !select.disabled, '#language-feedback');
      return;
    }
    if (setting === 'widget_theme') {
      const select = $('#widget-theme');
      if (!select || !await until(() => usable(select), 5000)) throw new Error(t('The widget theme can only be changed inside the linked GoodMorning app.'));
      if (select.value === value) return;
      await act(() => { select.value = value; select.dispatchEvent(new Event('change')); }, () => select.value === value && !select.disabled, '#widget-theme-feedback');
      return;
    }
    if (setting === 'notifications') {
      const form = $('#notification-form');
      // app.js reveals the form once it knows this device can get notifications.
      if (!form || !await until(() => shown(form))) throw new Error(t(MISSING));
      const choices = $('#notification-choices');
      if (!shown(choices) || $('#notification-kinds')?.disabled) {
        reveal($('#notification-device:not([hidden])') || form);
        throw new Error(t('Notifications are off on this device. Turn them on in the pop-up first.'));
      }
      const field = name => name === 'lead' ? $('#notification-lead') : form.elements[name];
      const matches = () => Object.entries(value).every(([name, wanted]) =>
        typeof wanted === 'boolean' ? field(name).checked === wanted : field(name).value === String(wanted));
      if (matches()) return;
      await act(() => {
        Object.entries(value).forEach(([name, wanted]) => { if (typeof wanted === 'boolean') field(name).checked = wanted; else field(name).value = String(wanted); });
        form.dispatchEvent(new Event('change'));
      }, () => matches() && $('#notification-feedback').textContent === t('Notification settings saved.'), '#notification-feedback');
      return;
    }
    if (setting === 'notifications_here') {
      const form = $('#notification-form');
      if (!form || !await until(() => shown(form))) throw new Error(t(MISSING));
      const choices = $('#notification-choices');
      if (!shown(choices)) return;  // Already off here.
      const button = $('#notification-device');
      if (usable(button)) {
        await act(() => button.click(), () => !shown(choices) && !button.disabled, '#notification-feedback');
        return;
      }
      // The app's WebView has no Web Push button; its own row in the device list turns it off.
      const own = rows('#notification-device-list').find(item => item.here);
      if (!own) throw new Error(t(MISSING));
      await act(() => own.row.querySelector('button').click(), () => !shown(choices), '#notification-devices-feedback');
      return;
    }
    if (setting === 'device_notifications_off') {
      if (!shown($('#notification-device-list')) && !await until(() => shown($('#notification-device-list')), 5000)) throw new Error(t(MISSING));
      const target = find('#notification-device-list', value);
      await act(() => target.row.querySelector('button').click(), () => !target.row.isConnected, '#notification-devices-feedback');
      return;
    }
    if (setting === 'link_phone') {
      const form = $('#app-link-form'), code = $('#app-link-code');
      if (!form || !await until(() => shown(form))) throw new Error(t(MISSING));
      const feedback = $('#app-link-feedback');
      // A linked code clears its field and app.js says so; a refused one stays, with the reason.
      await act(() => { code.value = value; form.requestSubmit(); }, () => code.value === '' && feedback.textContent.trim() !== '', '#app-link-feedback');
      return;
    }
    if (setting === 'unlink_phone') {
      if (!$('#app-links') || !await until(() => shown($('#app-links')))) throw new Error(t(MISSING));
      const target = find('#app-links', value);
      await act(() => target.row.querySelector('button').click(), () => !target.row.isConnected, '#app-link-feedback');
      return;
    }
    if (setting === 'sign_out') {
      const button = $('#sign-out');
      if (!button) throw new Error(t(MISSING));
      button.click();
      return;
    }
    if (setting === 'open') {
      const targets = {appearance: '#color-scheme-form', notifications: '#notification-form', phones: '#app-link-form', account: '#language-form',
        password: 'a[href="/password"]', avatar: '#avatar-settings', download: 'a.app-download'};
      const target = $(targets[value]);
      if (!shown(target) || !reveal(target)) throw new Error(t(MISSING));
      return;
    }
    throw new Error(t(MISSING));
  }

  // Each change waits for the one before it, so controls that save asynchronously never drop one.
  let queue = Promise.resolve();
  const running = new Set();
  const cards = new Map();
  function run(chat, action, tap) {
    const id = chat + ':' + action.seq;
    if (running.has(id)) return;
    running.add(id);
    keep(chat, action.seq, working(action.setting));
    refresh(chat, action);
    queue = queue.then(async () => {
      let text;
      try {
        const response = await fetch(`/api/chats/${chat}/settings/${action.seq}/claim`, {method: 'POST', credentials: 'same-origin',
          cache: 'no-store', headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': csrf()},
          body: JSON.stringify({setting: action.setting, page, tap})});
        const claim = await response.json();
        if (!response.ok) throw new Error(claim.error || t('Try again from the pop-up.'));
        if (claim.state === 'running') {  // The reply is still going: try again once it ends.
          running.delete(id); forget(chat, action.seq); refresh(chat, action); return;
        }
        if (!claim.claimed) text = t(claim.state === 'used' ? 'Handled on the page it was asked from.' : NOT_CHANGED);
        // Apply only the exact request on the card, and a tap action only from a tap.
        else if (claim.seq !== action.seq || claim.setting !== action.setting || (TAP.includes(claim.setting) && !tap)) throw new Error(t(NOT_CHANGED));
        else { await apply(claim); text = done(action.setting); }
      } catch (error) {
        text = t('Couldn’t change it: {reason}', {reason: error.message});
      }
      keep(chat, action.seq, text);
      refresh(chat, action);
    });
  }

  function refresh(chat, action) {
    const node = cards.get(chat + ':' + action.seq);
    if (!node) return;
    node.querySelector('.chat-setting-title').textContent = title(action);
    const status = node.querySelector('.chat-setting-result');
    const button = node.querySelector('.chat-setting-confirm');
    const local = results(chat)[action.seq];
    let text = '';
    button.hidden = true;
    if (action.state === 'saved') text = t('Done.');
    else if (local) text = local;
    else if (action.state === 'used') text = t('Handled on the page it was asked from.');
    else if (action.state === 'stale' || !owned(action)) text = t(NOT_CHANGED);
    // Only the asking page shows the button, and only once the reply has ended.
    else if (TAP.includes(action.setting) && finished(chat)) {
      button.hidden = false;
      button.textContent = action.setting === 'link_phone' ? t('Link this phone ({code})', {code: action.value})
        : action.setting === 'unlink_phone' ? t('Unlink {name}', {name: action.value}) : t('Sign out of this browser');
    }
    status.textContent = text;
    status.hidden = !text;
  }

  function card(chat, item) {
    const action = item.action;
    const id = chat + ':' + action.seq;
    let node = cards.get(id);
    if (!node) {
      node = document.createElement('span');
      node.className = 'chat-setting';
      const heading = document.createElement('span'); heading.className = 'chat-setting-title';
      const status = document.createElement('small'); status.className = 'chat-setting-result';
      const button = document.createElement('button'); button.type = 'button'; button.className = 'chat-setting-confirm';
      // The user's own tap is the confirmation; a script's click is not.
      button.addEventListener('click', event => {
        if (event.isTrusted && owned(node.action) && finished(chat)) { button.hidden = true; run(chat, node.action, true); }
      });
      node.append(heading, status, button);
      cards.set(id, node);
    }
    node.action = {...action, from_turn: item.from_turn};
    refresh(chat, node.action);
    return node;
  }

  // Called on every transcript update; `state` is the conversation's, so changes wait for the reply.
  function update(chat, messages, state) {
    if (!chat) return;
    states.set(chat, state);
    for (const item of messages) if (item.action?.target === 'setting') card(chat, item);
    if (!finished(chat)) return;
    for (const item of messages) {
      const action = item.action;
      if (action?.target !== 'setting' || action.state !== 'open' || TAP.includes(action.setting)) continue;
      if (!turns.has(item.from_turn) || Object.hasOwn(results(chat), action.seq)) continue;
      run(chat, {...action, from_turn: item.from_turn}, false);
    }
  }

  function remember(turn) {
    if (typeof turn === 'string' && turn) turns.add(turn);
  }

  document.addEventListener('website:language', () => cards.forEach((node, id) => refresh(id.split(':')[0], node.action)));
  return {page, remember, update, card};
})();
