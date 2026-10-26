// Refresh saved records. The one write is ticking a to-do done or back; never dispatch AI,
// import providers, or change calendar events.
const scheduleConfig = JSON.parse(document.querySelector('#schedule-config').dataset.config);
const scheduleView = document.querySelector('#schedule-view');
let scheduleQuery = location.search;
let scheduleRevision = scheduleConfig.revision;
let scheduleController = null;
let scheduleTimer = null;
let scheduleChecked = scheduleConfig.checked;
let scheduleNoticeTimer = null;

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

// A failed tap floats where the Undo notice appears, since the inline spot can be off-screen.
function scheduleError(message, floating = false) {
  const error = document.querySelector('#schedule-error');
  error.textContent = message ? goodmorningT(message) : '';
  error.classList.toggle('is-floating', floating);
}

function rememberScheduleView(mode) {
  try { localStorage.setItem(scheduleViewKey, mode); } catch {}
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
      enableTicks();
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
    scheduleError('');
  } catch (error) {
    if (error.name !== 'AbortError') scheduleError('Saved plans could not be refreshed. Your last view is kept.');
  } finally {
    if (controller === scheduleController) {
      scheduleController = null;
      document.querySelector('#schedule-refresh').disabled = false;
      if (!document.hidden) scheduleTimer = setTimeout(refreshSchedule, 60000);
    }
  }
}

function enableTicks() {
  scheduleView.querySelectorAll('button.task-tick').forEach(button => { button.disabled = false; });
}

async function saveTick(tick) {
  try {
    const response = await fetch('/api/schedule/tick', {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': languageConfig.csrf},
      body: JSON.stringify({...tick, key: crypto.randomUUID()})});
    const result = await goodmorningJSON(response);
    if (response.ok) return result;
    scheduleError(response.status === 409
      ? 'Couldn’t save — this task changed since the page loaded. Refresh and try again.'
      : 'Couldn’t save. Check your connection and try again.', true);
  } catch {
    scheduleError('Couldn’t save. Check your connection and try again.', true);
  }
  // An older Undo would sit next to this failure; the error alone says what happened.
  clearTimeout(scheduleNoticeTimer);
  document.querySelector('#schedule-notice').replaceChildren();
  return null;
}

function tickNotice(title, saved) {
  const notice = document.querySelector('#schedule-notice');
  const message = document.createElement('span');
  message.textContent = goodmorningT(saved.done ? 'Marked “{task}” done.' : 'Marked “{task}” not done.', {task: title});
  const undo = document.createElement('button');
  undo.type = 'button';
  undo.textContent = goodmorningT('Undo');
  undo.addEventListener('click', async () => {
    if (undo.dataset.pending) return;
    undo.dataset.pending = 'true';
    const reverted = await saveTick({id: saved.id, date: saved.date, revision: saved.revision, done: !saved.done});
    if (reverted) { tickNotice(title, reverted); refreshSchedule(); }
  });
  clearTimeout(scheduleNoticeTimer);
  notice.replaceChildren(message, undo);
  // Stay while the Undo button has keyboard focus.
  const hide = () => notice.contains(document.activeElement) ? scheduleNoticeTimer = setTimeout(hide, 2000) : notice.replaceChildren();
  scheduleNoticeTimer = setTimeout(hide, 6000);
}

async function tickRow(button) {
  if (button.dataset.pending) return;
  button.dataset.pending = 'true';
  const row = button.closest('.schedule-task');
  const before = {className: row.className, mark: button.textContent};
  const done = button.dataset.tickDone !== 'true';
  row.className = 'schedule-task is-' + (done ? 'done' : 'open');
  button.textContent = done ? '✓' : '○';
  const saved = await saveTick({id: button.dataset.tickId, date: button.dataset.tickDate, revision: Number(button.dataset.tickRevision), done});
  delete button.dataset.pending;
  if (!saved) { row.className = before.className; button.textContent = before.mark; return; }
  scheduleError('');
  tickNotice(row.querySelector('.task-title').textContent, saved);
  refreshSchedule();
}

scheduleView.addEventListener('click', event => {
  if (event.target.closest('#schedule-refresh')) { refreshSchedule(); return; }
  const tick = event.target.closest('button.task-tick');
  if (tick) { tickRow(tick); return; }
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
enableTicks();
scheduleStatus();
refreshSchedule();
