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
      : part === 'weekday' ? {weekday: 'short'} : part === 'weekday-date' ? {weekday: 'short', day: 'numeric', month: 'short'} : part === 'range-day' ? {day: 'numeric'}
      : part === 'dated' ? {day: 'numeric', month: 'short', year: 'numeric'} : {day: 'numeric', month: 'short'};
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

// Phones always open on Day; wider screens reopen the view used last (schedule-mode.js).
function rememberScheduleView(mode) {
  if (!schedulePhone) try { localStorage.setItem(scheduleViewKey, mode); } catch {}
}

async function refreshSchedule(query = scheduleQuery, navigate = false) {
  if (!scheduleConfig.ready || document.hidden) return;
  // While an Undo notice is up, the rows stay where they are; it refreshes when the notice ends.
  if (scheduleHold && !navigate) return;
  if (navigate) { scheduleHold = false; scheduleEarlierOpen = scheduleDoneOpen = false; }
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
      const moved = navigate ? new Map() : new Map([...scheduleView.querySelectorAll('.tl-row[id]')].map(row => [row.id, row.getBoundingClientRect().top]));
      scheduleView.replaceChildren(fragment.content);
      enableTicks();
      scheduleDay();
      // Ticked rows slide down under "Done", reopened ones slide back up.
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches) moved.forEach((top, id) => {
        const row = document.getElementById(id);
        const shift = row && top - row.getBoundingClientRect().top;
        if (Math.abs(shift) > 1) row.animate([{transform: `translateY(${shift}px)`}, {transform: 'none'}], {duration: 420, easing: 'cubic-bezier(.22,1,.36,1)'});
      });
      expanded.forEach(id => { const node = document.getElementById(id); if (node) node.open = true; });
      if (focused) document.getElementById(focused)?.focus({preventScroll: true});
      scheduleRevision = result.revision;
      scheduleApplying = true;
      applyWebsiteLanguage(goodmorningLanguage);
      scheduleApplying = false;
    }
    scheduleQuery = query;
    rememberScheduleView(result.mode);
    document.documentElement.dataset.edition = result.theme;
    if (navigate) history.pushState({}, '', '/schedule' + query);
    scheduleChecked = result.checked;
    scheduleStatus();
    scheduleClock();
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

// Interface text that a later language switch can translate again.
function scheduleText(node, key, values = {}) {
  node.textContent = goodmorningT(key, values);
  node.dataset.uiText = key.replace(/\{([a-z]+)\}/g, (token, name) => values[name] ?? token);
}

// Day view chrome that lives in the browser: the checklist's count, the jump chip, the folds and the clock.
let scheduleEarlierOpen = false;
let scheduleDoneOpen = false;
function scheduleDay() {
  const earlier = scheduleView.querySelector('.day-earlier');
  if (earlier) { earlier.closest('.day-schedule').classList.toggle('show-earlier', scheduleEarlierOpen); earlier.setAttribute('aria-expanded', scheduleEarlierOpen); }
  const fold = scheduleView.querySelector('button.tl-done-head');
  if (fold) { fold.setAttribute('aria-expanded', scheduleDoneOpen); scheduleView.querySelector('.tl-done').hidden = !scheduleDoneOpen; }
  scheduleClock();
  const list = scheduleView.querySelector('.tl');
  const counted = [...(list?.querySelectorAll('.tl-item:not(.is-optional)') || [])];
  const jump = scheduleView.querySelector('.day-jump');
  const head = list?.querySelector('.tl-head');
  if (!jump || !counted.length) return;
  const done = counted.filter(row => row.classList.contains('is-done')).length;
  const total = counted.length;
  // Future days are read-only and show no progress.
  if (counted[0].classList.contains('is-ro') && !head) return;
  jump.hidden = false;
  scheduleText(jump, 'To-dos · {done} of {total} ↓', {done, total});
  if (!head) return;
  head.classList.toggle('is-all', done === total);
  scheduleText(head.querySelector('.tl-progress'), done === total ? (list.classList.contains('is-today') ? 'All done for today' : 'All done') : '{done} of {total} done', {done, total});
  const bar = head.querySelector('.tl-bar');
  bar.setAttribute('aria-valuenow', done);
  bar.dataset.uiAriaLabel = `${done} of ${total} done`;
  bar.setAttribute('aria-label', goodmorningT('{done} of {total} done', {done, total}));
  if (bar.classList.contains('is-continuous')) bar.firstElementChild.style.width = `${100 * done / total}%`;
  else [...bar.children].forEach((segment, index) => segment.classList.toggle('is-on', index < done));
}

function scheduleClock() {
  const time = scheduleView.querySelector('.day-now-time');
  if (time && scheduleChecked) time.textContent = scheduleChecked;
}

// Rows never move under the finger: a tap flips its row in place, and the list settles into its new
// order only when the Undo notice ends. Until then checks leave the view alone.
let scheduleHold = false;
function settleSchedule() {
  scheduleHold = false;
  refreshSchedule();
}

function markTick(button, done, revision) {
  const row = button.closest('.schedule-task, .tl-item');
  const title = row.querySelector('.task-title').textContent;
  button.dataset.tickDone = String(done);
  if (revision !== undefined) button.dataset.tickRevision = revision;
  const label = done ? 'Mark “{task}” not done' : 'Mark “{task}” done';
  button.dataset.uiAriaLabel = label.replace('{task}', title);
  button.setAttribute('aria-label', goodmorningT(label, {task: title}));
  if (row.classList.contains('tl-item')) row.classList.toggle('is-done', done);
  else {
    // A week row keeps its saved state (Partial, Blocked) to show again when unticked.
    row.dataset.saved ??= row.className;
    row.className = done ? 'schedule-task is-done' : row.dataset.saved.includes('is-done') ? 'schedule-task is-open' : row.dataset.saved;
    button.textContent = done ? '✓' : '○';
  }
  scheduleDay();
  return title;
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

function tickNotice(title, saved, button) {
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
    if (!reverted) { settleSchedule(); return; }
    if (button.isConnected) markTick(button, reverted.done, reverted.revision);
    clearTimeout(scheduleNoticeTimer);
    notice.replaceChildren();
    settleSchedule();
  });
  clearTimeout(scheduleNoticeTimer);
  notice.replaceChildren(message, undo);
  scheduleHold = true;
  // Stay while the Undo button has keyboard focus.
  const hide = () => {
    if (notice.contains(document.activeElement)) { scheduleNoticeTimer = setTimeout(hide, 2000); return; }
    notice.replaceChildren();
    settleSchedule();
  };
  scheduleNoticeTimer = setTimeout(hide, 5000);
  keepClear(button, notice);
}

// Phones: if the tapped row would sit behind the notice, scroll just enough to keep it in view.
function keepClear(button, notice) {
  const over = button.getBoundingClientRect().bottom - (notice.getBoundingClientRect().top - 12);
  if (over > 0 && notice.getBoundingClientRect().top > 0) scrollBy({top: over, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
}

async function tickRow(button) {
  if (button.dataset.pending) return;
  button.dataset.pending = 'true';
  const before = button.dataset.tickDone === 'true';
  // The mark flips at once; a refused save puts it back.
  markTick(button, !before);
  const saved = await saveTick({id: button.dataset.tickId, date: button.dataset.tickDate, revision: Number(button.dataset.tickRevision), done: !before});
  delete button.dataset.pending;
  if (!saved) { markTick(button, before); return; }
  scheduleError('');
  tickNotice(markTick(button, saved.done, saved.revision), saved, button);
}

scheduleView.addEventListener('click', event => {
  if (event.target.closest('#schedule-refresh')) { refreshSchedule(); return; }
  const tick = event.target.closest('button.task-tick');
  if (tick) { tickRow(tick); return; }
  if (event.target.closest('.day-earlier')) { scheduleEarlierOpen = !scheduleEarlierOpen; scheduleDay(); return; }
  if (event.target.closest('button.tl-done-head')) { scheduleDoneOpen = !scheduleDoneOpen; scheduleDay(); return; }
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
// Server-worded labels (dates in rows, repeat rules) come back in the new language.
let scheduleApplying = false;
document.addEventListener('website:language', () => { scheduleStatus(); if (!scheduleApplying) refreshSchedule(); });
if (scheduleConfig.ready) rememberScheduleView(scheduleConfig.mode);
enableTicks();
scheduleDay();
scheduleStatus();
refreshSchedule();
