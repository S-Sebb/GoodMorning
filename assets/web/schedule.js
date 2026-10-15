// Refresh saved records only. Never dispatch AI, import providers, or mutate plans.
const scheduleConfig = JSON.parse(document.querySelector('#schedule-config').dataset.config);
const scheduleView = document.querySelector('#schedule-view');
let scheduleQuery = location.search;
let scheduleRevision = scheduleConfig.revision;
let scheduleController = null;
let scheduleTimer = null;
let scheduleChecked = scheduleConfig.checked;

function scheduleStatus() {
  const status = document.querySelector('#schedule-status');
  if (status) status.textContent = scheduleChecked ? goodmorningT('Checked at {time}', {time: scheduleChecked}) : '';
  document.querySelectorAll('[data-schedule-date]').forEach(node => {
    const day = new Date(node.dataset.scheduleDate + 'T12:00:00Z');
    const part = node.dataset.schedulePart;
    const options = part === 'month' ? {month: 'long', year: 'numeric'}
      : part === 'full' ? {weekday: 'long', day: 'numeric', month: 'long'}
      : part === 'weekday' ? {weekday: 'short'} : {day: 'numeric', month: 'short'};
    node.textContent = part === 'day' ? String(day.getUTCDate())
      : new Intl.DateTimeFormat(goodmorningLanguage, {...options, timeZone: 'UTC'}).format(day);
  });
}

function rememberScheduleView(mode) {
  try { localStorage.setItem('goodmorning-schedule-view', mode); } catch {}
}

async function refreshSchedule(query = scheduleQuery, navigate = false) {
  if (!scheduleConfig.ready || document.hidden) return;
  clearTimeout(scheduleTimer);
  scheduleController?.abort();
  const controller = new AbortController();
  scheduleController = controller;
  const refresh = document.querySelector('#schedule-refresh');
  refresh.disabled = true;
  try {
    const response = await fetch('/api/schedule' + (query || '?week=0'), {signal: controller.signal, credentials: 'same-origin', cache: 'no-store'});
    const result = await goodmorningJSON(response);
    if (!response.ok) throw new Error(result.error || goodmorningT('Saved plans could not be refreshed. Your last view is kept.'));
    if (controller !== scheduleController) return;
    if (result.revision !== scheduleRevision) {
      const expanded = new Set([...scheduleView.querySelectorAll('details[open]')].map(node => node.id));
      const focused = scheduleView.contains(document.activeElement) ? document.activeElement.id : null;
      const fragment = document.createElement('template');
      // This is escaped, typed server markup, not agent-authored HTML.
      fragment.innerHTML = result.view;
      scheduleView.replaceChildren(fragment.content);
      expanded.forEach(id => { const node = document.getElementById(id); if (node) node.open = true; });
      if (focused) document.getElementById(focused)?.focus({preventScroll: true});
      scheduleRevision = result.revision;
      applyWebsiteLanguage(goodmorningLanguage);
    }
    scheduleQuery = query;
    rememberScheduleView(result.mode);
    document.documentElement.dataset.edition = result.theme;
    if (navigate) history.pushState({}, '', '/schedule' + query);
    scheduleChecked = result.checked;
    scheduleStatus();
    document.querySelector('#schedule-error').textContent = '';
  } catch (error) {
    if (error.name !== 'AbortError') document.querySelector('#schedule-error').textContent = goodmorningT('Saved plans could not be refreshed. Your last view is kept.');
  } finally {
    if (controller === scheduleController) {
      scheduleController = null;
      document.querySelector('#schedule-refresh').disabled = false;
      if (!document.hidden) scheduleTimer = setTimeout(refreshSchedule, 60000);
    }
  }
}

scheduleView.addEventListener('click', event => {
  if (event.target.closest('#schedule-refresh')) { refreshSchedule(); return; }
  const link = event.target.closest('a[data-schedule-nav]');
  if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  refreshSchedule(new URL(link.href).search, true);
});
document.addEventListener('pointerdown', event => {
  const info = document.querySelector('#schedule-info');
  if (info?.open && !info.contains(event.target)) info.open = false;
});
document.addEventListener('keydown', event => {
  const info = document.querySelector('#schedule-info');
  if (event.key === 'Escape' && info?.open) { info.open = false; info.querySelector('summary').focus(); }
});
window.addEventListener('popstate', () => refreshSchedule(location.search));
window.addEventListener('focus', () => refreshSchedule());
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { clearTimeout(scheduleTimer); scheduleController?.abort(); }
  else refreshSchedule();
});
document.addEventListener('website:language', scheduleStatus);
if (scheduleConfig.ready) rememberScheduleView(scheduleConfig.mode);
scheduleStatus();
refreshSchedule();
