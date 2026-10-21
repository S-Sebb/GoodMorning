// Public release history; dismissals live with the account, never with browser drafts.
(() => {
  const initial = document.querySelector('#site-release')?.dataset.version ?? null;
  const t = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
  // Inside the Android app the website still updates by refreshing; the app itself updates separately,
  // and the app's launch tells the site which build it is.
  const appBuild = Number((document.cookie.match(/(?:^|; )GoodMorningApp=(\d+)/) || [])[1] || 0);
  const inApp = appBuild > 0 || matchMedia('(display-mode: standalone)').matches || navigator.userAgent.includes('GoodMorningApp/');
  let appRelease = null;  // A newer app build, {code, name}, once the server reports one.
  const localized = (note, prefix = '') => note[prefix + (document.documentElement.lang === 'zh-CN' ? 'zh' : 'en')];
  const toggle = document.createElement('button');
  toggle.id = 'site-update-toggle';
  toggle.type = 'button';
  toggle.hidden = true;
  toggle.setAttribute('aria-haspopup', 'dialog');
  toggle.setAttribute('aria-controls', 'site-patch-note');
  toggle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
    + '<path class="update-arrow" d="M12 19V5m-6 6 6-6 6 6"/>'
    + '<path class="update-check" d="M12 4c.6 4.2 2.8 6.4 7 7-4.2.6-6.4 2.8-7 7-.6-4.2-2.8-6.4-7-7 4.2-.6 6.4-2.8 7-7Z"/></svg><span></span>';
  const patch = document.createElement('dialog');
  patch.id = 'site-patch-note';
  patch.setAttribute('aria-labelledby', 'patch-note-heading');
  patch.innerHTML = '<div class="patch-layout">'
    + '<header class="patch-header"><h2 id="patch-note-heading"></h2><span id="patch-beta"></span></header>'
    + '<nav id="patch-note-versions"></nav>'
    + '<section class="patch-content" tabindex="0" aria-labelledby="patch-note-version">'
    + '<p id="patch-note-version"></p><h3 id="patch-note-title"></h3><p id="patch-note-date"></p>'
    + '<div id="patch-note-text"></div><p id="patch-note-source"></p></section>'
    + '<footer class="patch-footer"><p id="app-update-status" role="status" hidden></p><p id="update-status" role="status"></p>'
    + '<p id="update-feedback" role="status" aria-live="polite"></p>'
    + '<div><button id="patch-note-dismiss" type="button"></button><button id="app-update" type="button" hidden></button>'
    + '<button id="update-refresh" type="button"></button></div></footer></div>';
  document.body.append(patch);
  // The toggle lives in the top utility row's fixed slot; without it (older
  // cached pages) it falls back to a body-level button as before.
  const slot = document.querySelector('#update-slot');
  if (slot) slot.append(toggle); else document.body.append(toggle);
  const versions = patch.querySelector('#patch-note-versions');
  const feedback = patch.querySelector('#update-feedback');
  const refreshButton = patch.querySelector('#update-refresh');
  const dismissButton = patch.querySelector('#patch-note-dismiss');
  const appButton = patch.querySelector('#app-update');
  let latest = initial, release = null, notes = [], selected = null;
  let checking = false, checkedAt = 0, shown = null, seen = null, accountEnabled = false;
  let returnFocus = null;
  let renderedChanges = null;
  const stale = () => initial === null || latest !== initial;
  const unseen = () => {
    if (typeof seen !== 'string') return true;
    const [, minor, patchNumber] = release.split('.').map(Number);
    const [, seenMinor, seenPatch] = seen.split('.').map(Number);
    return minor > seenMinor || (minor === seenMinor && patchNumber > seenPatch);
  };

  function render() {
    toggle.hidden = notes.length === 0;
    toggle.dataset.state = stale() || appRelease ? 'available' : 'current';
    // An app update comes first; in the app a website update is only a refresh.
    const label = t(appRelease ? 'App update available. View details'
      : stale() ? (inApp ? 'New features available. View patch notes' : 'Update available. View patch notes') : 'What’s new: view patch notes');
    toggle.setAttribute('aria-label', label);
    toggle.title = label;
    toggle.querySelector('span').textContent = t(appRelease ? 'App update' : stale() ? (inApp ? 'Refresh' : 'Update') : 'What’s new');
    const appStatus = patch.querySelector('#app-update-status');
    appStatus.hidden = appButton.hidden = !appRelease;
    if (appRelease) appStatus.textContent = t('GoodMorning app {version} is ready.', {version: appRelease.name});
    appButton.textContent = t('Update app');
    patch.querySelector('#patch-note-heading').textContent = t('Patch notes');
    patch.querySelector('#patch-beta').textContent = t('Beta');
    versions.setAttribute('aria-label', t('Patch note versions'));
    refreshButton.textContent = t(inApp ? 'Refresh' : 'Update');
    refreshButton.hidden = !stale();
    dismissButton.textContent = t('Dismiss');
    patch.querySelector('#update-status').textContent = t(inApp
        ? (stale() ? "GoodMorning has new features. Refresh to use them; the app itself doesn't need updating." : 'You have the newest GoodMorning features.')
        : (stale() ? 'A website update is available.' : "You're up to date."))
      + (release ? ' · v' + release : '');
    // Polling must not replace a focused history button or reset reading position.
    if ([...versions.children].map(button => button.dataset.version).join(',') !== notes.map(note => note.version).join(',')) {
      versions.replaceChildren();
      for (const note of notes) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.version = note.version;
        button.textContent = 'v' + note.version;
        const day = document.createElement('span');
        day.textContent = note.date;
        button.appendChild(day);
        button.addEventListener('click', () => {
          selected = note.version;
          renderSelection();
          patch.querySelector('.patch-content').scrollTop = 0;
        });
        versions.appendChild(button);
      }
    }
    renderSelection();
  }

  function renderSelection() {
    const note = notes.find(entry => entry.version === selected) || notes[0];
    if (!note) return;
    selected = note.version;
    for (const button of versions.children) button.setAttribute('aria-current', String(button.dataset.version === selected));
    patch.querySelector('#patch-note-version').textContent = 'v' + note.version;
    patch.querySelector('#patch-note-title').textContent = localized(note, 'title_');
    patch.querySelector('#patch-note-date').textContent = note.date + ' · ' + note.author;
    const contentKey = JSON.stringify([note.version, document.documentElement.lang, note.changes]);
    if (renderedChanges !== contentKey) {
      const content = document.createDocumentFragment();
      for (const group of note.changes) {
        const section = document.createElement('section');
        section.className = 'patch-category';
        section.dataset.category = group.category;
        const heading = document.createElement('h4');
        heading.textContent = t(group.category);
        const list = document.createElement('ul');
        for (const item of localized(group)) {
          const bullet = document.createElement('li');
          bullet.textContent = item;
          list.appendChild(bullet);
        }
        section.append(heading, list);
        content.appendChild(section);
      }
      patch.querySelector('#patch-note-text').replaceChildren(content);
      renderedChanges = contentKey;
    }
    patch.querySelector('#patch-note-source').textContent = note.commits?.length
      ? t('Reconstructed from Git commits:') + ' ' + note.commits.join(', ') : '';
  }

  function open() {
    if (!notes.length || patch.open) return;
    returnFocus = document.activeElement;
    selected = release;
    feedback.textContent = '';
    render();
    patch.querySelector('.patch-content').scrollTop = 0;
    patch.showModal();
    dismissButton.focus();
  }

  async function acknowledge() {
    if (!accountEnabled || !release) return;
    const version = release;
    try {
      const config = JSON.parse(document.querySelector('#language-config').dataset.config);
      const response = await fetch('/api/release/seen', {method:'POST', credentials:'same-origin', cache:'no-store',
        headers:{'Content-Type':'application/json', 'X-Briefing-CSRF':config.csrf}, body:JSON.stringify({version})});
      if (!response.ok) throw new Error();
      seen = (await goodmorningJSON(response)).version;
    } catch {
      // Dismiss this visit even offline, but never pretend the account save succeeded.
      toggle.title = t('Dismissal could not be saved. Patch notes may appear again.');
    }
  }

  async function dismiss() {
    dismissButton.disabled = true;
    await acknowledge();
    patch.close();
    dismissButton.disabled = false;
  }
  patch.addEventListener('cancel', event => { event.preventDefault(); dismiss(); });
  patch.addEventListener('close', () => {
    if (returnFocus?.isConnected && !returnFocus.closest('dialog')) returnFocus.focus();
    else toggle.focus();
  });
  toggle.addEventListener('click', open);
  // The app's own update screen downloads the new build and hands it to Android's installer.
  appButton.addEventListener('click', () => { location.href = 'goodmorning://update'; });
  dismissButton.addEventListener('click', dismiss);
  document.addEventListener('website:language', render);

  async function check(force = false) {
    if (document.hidden || checking || (!force && Date.now() - checkedAt < 10000)) return;
    checking = true; checkedAt = Date.now();
    try {
      const [response, state] = await Promise.all([
        fetch('/api/release', {cache:'no-cache', credentials:'omit'}),
        fetch('/api/release/seen', {cache:'no-store', credentials:'same-origin'})
      ]);
      if (!response.ok) return;
      const result = await goodmorningJSON(response);
      if (!/^[a-f0-9]{64}$/.test(result.version)) return;
      latest = result.version;
      if (!Array.isArray(result.notes) || !result.notes.length) return;
      if (!result.notes.every(note => /^0\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(note.version)
        && ['title_en','title_zh'].every(key => typeof note[key] === 'string' && note[key].length <= 2000)
        && Array.isArray(note.changes) && note.changes.length && note.changes.every(group => typeof group.category === 'string'
          && ['en','zh'].every(lang => Array.isArray(group[lang]) && group[lang].length
            && group[lang].every(item => typeof item === 'string' && item.length > 0 && item.length <= 2000))
          && group.en.length === group.zh.length))) return;
      notes = result.notes;
      release = notes[0].version;
      selected = selected && notes.some(note => note.version === selected) ? selected : release;
      if (state.ok) {
        const status = await goodmorningJSON(state);
        accountEnabled = status.enabled === true;
        seen = status.version;
      }
      if (appBuild) {
        const app = await fetch('/api/app/release', {cache: 'no-cache', credentials: 'omit'}).then(answer => answer.ok ? answer.json() : {}).catch(() => ({}));
        appRelease = Number.isInteger(app.code) && app.code > appBuild && typeof app.name === 'string' ? app : null;
      }
      render();
      if (accountEnabled && unseen() && shown !== release) {
        shown = release;
        open();
      } else if (appRelease && localStorage.getItem('goodmorningAppUpdateShown') !== String(appRelease.code)) {
        // Each new app build is announced once on this phone; afterwards the pill keeps offering it.
        localStorage.setItem('goodmorningAppUpdateShown', String(appRelease.code));
        open();
      }
    } catch { /* Preserve readable pages and drafts during outages. */ }
    finally { checking = false; }
  }

  refreshButton.addEventListener('click', async () => {
    if (!document.dispatchEvent(new Event('website:before-refresh', {cancelable:true}))) {
      feedback.textContent = t('Wait for your message to finish sending before refreshing.');
      return;
    }
    // Typed text and changed answers to a secretary's questions count. Settings controls save at once,
    // and pages fill them in after loading, so their state is never a draft.
    const dirty = [...document.querySelectorAll('textarea, input:is(:not([type]), [type=text], [type=search], [type=email], [type=url], [type=tel], [type=number])')]
      .some(field => field.value !== field.defaultValue)
      || [...document.querySelectorAll('.agent-form input:is([type=checkbox], [type=radio])')].some(field => field.checked !== field.defaultChecked);
    const event = new Event('website:refresh-drafts', {cancelable:true});
    if ((dirty || !document.dispatchEvent(event)) && !window.confirm(t('Refreshing will discard unsent text. Refresh anyway?'))) return;
    refreshButton.disabled = true;
    await acknowledge();
    location.reload();
  });
  window.addEventListener('focus', () => { check(); });
  window.addEventListener('pageshow', () => { check(); });
  document.addEventListener('visibilitychange', () => { check(); });
  setInterval(check, 60000);
  check();
})();
