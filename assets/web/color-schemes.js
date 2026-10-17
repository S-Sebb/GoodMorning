// Account-wide colors change in place: never reload, rewrite content, or lose drafts.
(() => {
  const config = JSON.parse(document.querySelector('#color-scheme-config').dataset.config);
  const form = document.querySelector('#color-scheme-form');
  const pixel = document.querySelector('#pixel-style');
  const feedback = document.querySelector('#color-scheme-feedback');
  const root = document.documentElement;
  const t = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  let saved = config.schemes, saving = false, syncing = false, revision = 0;
  const radios = theme => Array.from(form.querySelectorAll(`input[name="${theme}"]`));
  const chosen = theme => radios(theme).find(radio => radio.checked)?.value;
  const check = (theme, value) => radios(theme).forEach(radio => { radio.checked = radio.value === value; });
  const valid = value => value && radios('day').some(radio => radio.value === value.day)
    && radios('night').some(radio => radio.value === value.night) && typeof value.pixel === 'boolean';
  const same = value => value.day === saved.day && value.night === saved.night && value.pixel === saved.pixel;
  function paint() { if (saved.pixel) root.dataset.pixel = 'on'; else delete root.dataset.pixel; }
  function show(value) { check('day', value.day); check('night', value.night); pixel.checked = value.pixel; }
  function apply(value) {
    if (!valid(value)) throw new Error(t('Color schemes could not be saved. Try again.'));
    saved = {day: value.day, night: value.night, pixel: value.pixel};
    show(saved);
    root.dataset.dayScheme = saved.day;
    root.dataset.nightScheme = saved.night;
    paint();
    document.dispatchEvent(new CustomEvent('website:color-schemes', {detail: saved}));
  }
  const controls = () => [...form.querySelectorAll('input[type="radio"]'), pixel];
  async function save(event) {
    event?.preventDefault();
    if (saving) return;
    saving = true; revision++;
    const body = {day: chosen('day'), night: chosen('night'), pixel: pixel.checked};
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
