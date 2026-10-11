// Only a public release fingerprint is read. Never persist drafts or reload automatically.
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
      + '<button id="update-refresh" type="button">Refresh</button>'
      + '<button id="update-later" type="button">Later</button>'
      + '<p id="update-feedback" role="status"></p>';
    document.body.appendChild(notice);
  }
  const feedback = document.querySelector('#update-feedback');
  const refreshButton = document.querySelector('#update-refresh');
  const laterButton = document.querySelector('#update-later');
  const t = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  let checking = false, latest = initial, dismissed = null, checkedAt = 0;
  async function check(force = false) {
    if (document.hidden || checking || (!force && Date.now() - checkedAt < 10000)) return;
    checking = true; checkedAt = Date.now();
    try {
      const response = await fetch('/api/release', {cache:'no-cache',credentials:'omit'});
      if (!response.ok) return;
      const result = await response.json();
      if (!/^[a-f0-9]{64}$/.test(result.version)) return;
      latest = result.version;
      // Pages that predate the marker have no baseline: any valid release means they are stale.
      notice.hidden = (initial !== null && latest === initial) || latest === dismissed;
    } catch { /* Quietly keep the readable page during a deployment or outage. */ }
    finally { checking = false; }
  }
  if (laterButton) laterButton.addEventListener('click', () => {
    dismissed = latest; notice.hidden = true;
  });
  if (refreshButton) refreshButton.addEventListener('click', () => {
    if (!document.dispatchEvent(new Event('website:before-refresh', {cancelable:true}))) {
      if (feedback) feedback.textContent = t('Wait for your message to finish sending before refreshing.');
      return;
    }
    const dirty = [...document.querySelectorAll('input,textarea,select')].some(field => {
      if (field.closest('#language-form') || field.type === 'hidden') return false;
      if (['checkbox','radio'].includes(field.type)) return field.checked !== field.defaultChecked;
      if (field.tagName === 'SELECT') return [...field.options].some(option => option.selected !== option.defaultSelected);
      return field.value !== field.defaultValue;
    });
    const event = new Event('website:refresh-drafts', {cancelable:true});
    if ((dirty || !document.dispatchEvent(event)) && !window.confirm(t('Refreshing will discard unsent text. Refresh anyway?'))) return;
    location.reload();
  });
  window.addEventListener('focus', () => { check(); });
  window.addEventListener('pageshow', () => { check(); });
  document.addEventListener('visibilitychange', () => { check(); });
  setInterval(check, 60000);
  check();
})();
