// Only a public release fingerprint and its patch note are read. Never reload automatically.
(() => {
  const marker = document.querySelector('#site-release');
  const initial = marker ? marker.getAttribute('data-version') : null;
  let notice = document.querySelector('#site-update');
  if (!notice) {
    notice = document.createElement('aside');
    notice.id = 'site-update';
    notice.className = 'site-update';
    notice.setAttribute('aria-label', 'Website update');
    notice.hidden = true;
    notice.innerHTML = '<p role="status" aria-live="polite">A website update is available.</p>'
      + '<p id="update-note" role="status" hidden></p>'
      + '<button id="update-refresh" type="button">Update</button>'
      + '<button id="update-later" type="button">Later</button>'
      + '<p id="update-feedback" role="status"></p>';
    document.body.appendChild(notice);
  }
  let patch = document.querySelector('#site-patch-note');
  if (!patch) {
    patch = document.createElement('aside');
    patch.id = 'site-patch-note';
    patch.className = 'site-update';
    patch.setAttribute('aria-label', "What's new in this update");
    patch.hidden = true;
    patch.innerHTML = '<p role="status" aria-live="polite">Update complete. What\'s new in this update:</p>'
      + '<p id="patch-note-text" role="status"></p>'
      + '<button id="patch-note-dismiss" type="button">Got it</button>';
    document.body.appendChild(patch);
  }
  const noteLine = document.querySelector('#update-note');
  const feedback = document.querySelector('#update-feedback');
  const refreshButton = document.querySelector('#update-refresh');
  const laterButton = document.querySelector('#update-later');
  const patchText = document.querySelector('#patch-note-text');
  const patchDismiss = document.querySelector('#patch-note-dismiss');
  const t = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  const noteText = note => {
    if (!note || typeof note.en !== 'string' || typeof note.zh !== 'string') return '';
    return document.documentElement.lang === 'zh-CN' ? note.zh : note.en;
  };
  const renderNotes = () => {
    if (latestNote && !notice.hidden && noteLine) {
      const text = noteText(latestNote);
      noteLine.textContent = text; noteLine.hidden = !text;
    } else if (noteLine) { noteLine.textContent = ''; noteLine.hidden = true; }
  };
  document.addEventListener('website:language', renderNotes);
  let justUpdated = null;
  try { justUpdated = sessionStorage.getItem('gm-just-updated'); sessionStorage.removeItem('gm-just-updated'); } catch { justUpdated = null; }
  if (patchDismiss) patchDismiss.addEventListener('click', () => { patch.hidden = true; });
  let checking = false, latest = initial, latestNote = null, dismissed = null, checkedAt = 0, patchShown = false;
  async function check(force = false) {
    if (document.hidden || checking || (!force && Date.now() - checkedAt < 10000)) return;
    checking = true; checkedAt = Date.now();
    try {
      const response = await fetch('/api/release', {cache:'no-cache',credentials:'omit'});
      if (!response.ok) return;
      const result = await response.json();
      if (!/^[a-f0-9]{64}$/.test(result.version)) return;
      latest = result.version;
      const note = result.note;
      latestNote = (note && typeof note === 'object' && typeof note.en === 'string' && typeof note.zh === 'string'
        && note.en.length <= 2000 && note.zh.length <= 2000) ? note : null;
      // Pages that predate the marker have no baseline: any valid release means they are stale.
      notice.hidden = (initial !== null && latest === initial) || latest === dismissed;
      renderNotes();
      if (!patchShown && justUpdated !== null && initial !== null && latest === initial && latest !== justUpdated && latestNote) {
        patchShown = true;
        patchText.textContent = noteText(latestNote);
        patch.hidden = false;
      }
    } catch { /* Quietly keep the readable page during a deployment or outage. */ }
    finally { checking = false; }
  }
  if (laterButton) laterButton.addEventListener('click', () => {
    dismissed = latest; notice.hidden = true; renderNotes();
  });
  if (refreshButton) refreshButton.addEventListener('click', () => {
    if (!document.dispatchEvent(new Event('website:before-refresh', {cancelable:true}))) {
      if (feedback) feedback.textContent = t('Wait for your message to finish sending before refreshing.');
      return;
    }
    const dirty = [...document.querySelectorAll('input,textarea,select')].some(field => {
      if (field.closest('#language-form') || field.closest('#model-form') || field.type === 'hidden') return false;
      if (['checkbox','radio'].includes(field.type)) return field.checked !== field.defaultChecked;
      if (field.tagName === 'SELECT') return [...field.options].some(option => option.selected !== option.defaultSelected);
      return field.value !== field.defaultValue;
    });
    const event = new Event('website:refresh-drafts', {cancelable:true});
    if ((dirty || !document.dispatchEvent(event)) && !window.confirm(t('Refreshing will discard unsent text. Refresh anyway?'))) return;
    try { sessionStorage.setItem('gm-just-updated', initial || 'unknown'); } catch { /* Storage is optional; the update still applies. */ }
    location.reload();
  });
  window.addEventListener('focus', () => { check(); });
  window.addEventListener('pageshow', () => { check(); });
  document.addEventListener('visibilitychange', () => { check(); });
  setInterval(check, 60000);
  check();
})();
