// Only a public release fingerprint is read. Never persist drafts or reload automatically.
(() => {
  const initial = document.querySelector('#site-release').dataset.version;
  const notice = document.querySelector('#site-update');
  const feedback = document.querySelector('#update-feedback');
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
      notice.hidden = latest === initial || latest === dismissed;
    } catch { /* Quietly keep the readable page during a deployment or outage. */ }
    finally { checking = false; }
  }
  document.querySelector('#update-later').addEventListener('click', () => {
    dismissed = latest; notice.hidden = true;
  });
  document.querySelector('#update-refresh').addEventListener('click', () => {
    if (!document.dispatchEvent(new Event('website:before-refresh', {cancelable:true}))) {
      feedback.textContent = t('Wait for your message to finish sending before refreshing.');
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
  document.addEventListener('visibilitychange', () => { check(); });
  setInterval(check, 60000);
  check();
})();
