// Account-wide colors change in place: never reload, rewrite content, or lose drafts.
(() => {
  const config = JSON.parse(document.querySelector('#color-scheme-config').dataset.config);
  const form = document.querySelector('#color-scheme-form');
  const day = document.querySelector('#day-color-scheme');
  const night = document.querySelector('#night-color-scheme');
  const feedback = document.querySelector('#color-scheme-feedback');
  const t = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  let saved = config.schemes, saving = false, syncing = false, revision = 0;
  const valid = value => value && ['classic', 'warm'].includes(value.day) && ['classic', 'starry'].includes(value.night);
  function apply(value) {
    if (!valid(value)) throw new Error(t('Color schemes could not be saved. Try again.'));
    saved = {day: value.day, night: value.night};
    day.value = saved.day; night.value = saved.night;
    document.documentElement.dataset.dayScheme = saved.day;
    document.documentElement.dataset.nightScheme = saved.night;
    document.dispatchEvent(new CustomEvent('website:color-schemes', {detail: saved}));
  }
  async function save(event) {
    event?.preventDefault();
    if (saving) return;
    saving = true; revision++; day.disabled = night.disabled = true;
    try {
      const response = await fetch('/api/color-schemes', {method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': config.csrf},
        body: JSON.stringify({day: day.value, night: night.value})});
      const value = await goodmorningJSON(response);
      if (!response.ok) throw new Error(value.error || t('Color schemes could not be saved. Try again.'));
      apply(value); feedback.textContent = t('Color schemes saved.');
    } catch (error) {
      day.value = saved.day; night.value = saved.night;
      feedback.textContent = error.message;
    } finally { saving = false; day.disabled = night.disabled = false; }
  }
  async function sync() {
    if (document.hidden || saving || syncing) return;
    syncing = true;
    const version = revision;
    try {
      const response = await fetch('/api/color-schemes', {credentials: 'same-origin', cache: 'no-store'});
      if (response.ok) {
        const value = await goodmorningJSON(response);
        if (version === revision && valid(value) && (value.day !== saved.day || value.night !== saved.night)) apply(value);
      }
    } catch { /* Preserve the last confirmed palette and all drafts during an outage. */ }
    finally { syncing = false; }
  }
  form.addEventListener('submit', save);
  day.addEventListener('change', save); night.addEventListener('change', save);
  window.addEventListener('focus', sync); document.addEventListener('visibilitychange', sync);
  document.addEventListener('website:before-refresh', event => { if (saving) event.preventDefault(); });
  setInterval(sync, 15000);
})();
