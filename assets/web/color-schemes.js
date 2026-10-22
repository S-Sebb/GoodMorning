// This device's colors change in place: never reload, rewrite content, or lose drafts.
(() => {
  const config = JSON.parse(document.querySelector('#color-scheme-config').dataset.config);
  const form = document.querySelector('#color-scheme-form');
  const feedback = document.querySelector('#color-scheme-feedback');
  const root = document.documentElement;
  const t = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  let saved = config.schemes, saving = false, syncing = false, revision = 0;
  const radios = theme => Array.from(form.querySelectorAll(`input[name="${theme}"]`));
  const chosen = theme => radios(theme).find(radio => radio.checked)?.value;
  const check = (theme, value) => radios(theme).forEach(radio => { radio.checked = radio.value === value; });
  const choices = ['style', 'day', 'night'];
  const valid = value => value && choices.every(key => radios(key).some(radio => radio.value === value[key]));
  const same = value => choices.every(key => value[key] === saved[key]);
  function show(value) { choices.forEach(key => check(key, value[key])); }
  function apply(value) {
    if (!valid(value)) throw new Error(t('Color schemes could not be saved. Try again.'));
    saved = Object.fromEntries(choices.map(key => [key, value[key]]));
    show(saved);
    root.dataset.style = saved.style;
    root.dataset.dayScheme = saved.day;
    root.dataset.nightScheme = saved.night;
    document.dispatchEvent(new CustomEvent('website:color-schemes', {detail: saved}));
  }
  const controls = () => form.querySelectorAll('input[type="radio"]');
  async function save(event) {
    event?.preventDefault();
    if (saving) return;
    saving = true; revision++;
    const body = Object.fromEntries(choices.map(key => [key, chosen(key)]));
    controls().forEach(control => { control.disabled = true; });
    try {
      const response = await fetch('/api/color-schemes', {method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': config.csrf}, body: JSON.stringify(body)});
      const value = await goodmorningJSON(response);
      if (!response.ok) throw new Error(value.error || t('Color schemes could not be saved. Try again.'));
      apply(value); feedback.textContent = t('Color schemes saved.');
    } catch (error) {
      show(saved);
      feedback.textContent = error.message;
    } finally { saving = false; controls().forEach(control => { control.disabled = false; }); }
  }
  async function sync() {
    if (document.hidden || saving || syncing) return;
    syncing = true;
    const version = revision;
    try {
      const response = await fetch('/api/color-schemes', {credentials: 'same-origin', cache: 'no-store'});
      if (response.ok) {
        const value = await goodmorningJSON(response);
        if (version === revision && valid(value) && !same(value)) apply(value);
      }
    } catch { /* Preserve the last confirmed palette and all drafts during an outage. */ }
    finally { syncing = false; }
  }
  form.addEventListener('submit', save);
  form.addEventListener('change', save);
  window.addEventListener('focus', sync); document.addEventListener('visibilitychange', sync);
  document.addEventListener('website:before-refresh', event => { if (saving) event.preventDefault(); });
  setInterval(sync, 15000);
})();
