// Live features are separate from the lightweight saved-briefing reader.
const config = JSON.parse(document.querySelector('#browser-config').dataset.config);
const browserT = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
const errorBox = document.querySelector('#generation-error');
let job = null;
let pollTimer = null;
let formSignature = '';
let polling = false;
let previewRevision = null;
let imageRevision = null;
let resolvedSections = -1;
let briefingRequestLanguage = null;
let pendingBriefingMutations = 0;
let queuedBriefing = null;
let queuedRecovery = null;
let queuedRegeneration = null;
let regenerationRequest = null;
document.addEventListener('website:before-refresh', event => { if (pendingBriefingMutations) event.preventDefault(); });

function queueLabel(position, depth) {
  const place = browserT('You are #{position} in line', {position});
  const line = depth > 1 ? `${browserT('In queue')} · ${place} · ${browserT('{depth} waiting', {depth})}` : `${browserT('In queue')} · ${place}`;
  return line;
}

function showBriefingQueued(position, depth) {
  document.querySelector('#generation').hidden = false;
  showMeter({state: 'queued', progress: 2});
  const status = document.querySelector('#generation-status');
  status.textContent = queueLabel(position, depth);
  status.classList.add('is-queued');
  document.querySelector('.desk-animation')?.classList.add('is-paused');
}

function clearBriefingQueued() {
  document.querySelector('#generation-status').classList.remove('is-queued');
}

async function pollBriefingQueue() {
  clearTimeout(pollTimer);
  if (document.hidden || polling) return;
  polling = true;
  try {
    const waiting = await api('/api/queue');
    // An edition may already exist even if an older duplicate remains queued.
    if (queuedBriefing) {
      const current = await api(`/api/edition/${queuedBriefing.date}/${queuedBriefing.kind}`);
      if (current.job) {
        job = current.job; queuedBriefing = null; clearBriefingQueued();
        if (generate) generate.hidden = true;
        pollTimer = setTimeout(poll, 0);
        return;
      }
    }
    const mine = (waiting.queue || []).find(item =>
      (queuedBriefing && item.work === 'generate' && item.date === queuedBriefing.date && item.edition === queuedBriefing.kind) ||
      (queuedRecovery && ['recover', 'reply'].includes(item.work) && item.job === queuedRecovery));
    if (mine) {
      showBriefingQueued(mine.position, waiting.depth);
      if (queuedBriefing && generate) generate.hidden = true;
    } else if (queuedBriefing) {
      queuedBriefing = null; clearBriefingQueued();
      document.querySelector('#generation').hidden = true;
      if (generate) { generate.hidden = false; generate.disabled = false; }
      errorBox.textContent = browserT('Your queued request expired. Please try again.');
      return;
    } else if (queuedRecovery) {
      queuedRecovery = null; clearBriefingQueued();
      pollTimer = setTimeout(poll, 0);
      return;
    } else return;
  } catch (error) {
    errorBox.textContent = error.message;
  } finally { polling = false; }
  pollTimer = setTimeout(pollBriefingQueue, 2500);
}

function fragment(markup) {
  // Only escaped, typed server components arrive here, never agent-authored HTML.
  const template = document.createElement('template');
  template.innerHTML = markup;
  return template.content;
}

async function updatePreview(state) {
  if (!state.preview_revision || state.preview_revision === previewRevision) return;
  const refreshImages = state.image_revision !== imageRevision;
  const preview = await api(`/api/jobs/${job}/preview?after=${resolvedSections === -1 ? -1 : refreshImages ? 0 : resolvedSections}`);
  if (!preview.revision) return;
  const article = document.querySelector('article');
  if (!article) return;
  if (resolvedSections === -1) {
    article.replaceChildren(fragment(preview.sections));
    document.querySelector('.scroll-track').replaceChildren(fragment(preview.navigation));
    document.querySelector('h1').textContent = preview.greeting;
    document.querySelector('.subtitle').textContent = preview.opening;
    document.querySelector('h1').removeAttribute('data-ui-language');
    document.querySelector('.subtitle').removeAttribute('data-ui-language');
    article.lang = preview.lang;
    document.querySelector('h1').lang = preview.lang;
    document.querySelector('.subtitle').lang = preview.lang;
  }
  for (const change of preview.changes) {
    const section = document.querySelector(`#section-${change.index + 1}`);
    const segment = document.querySelector(`.scroll-chunk[href="#section-${change.index + 1}"]`).parentElement;
    if (change.state === 'skipped') {
      section.hidden = true;
      if (section.parentElement.classList.contains('section-entry')) section.parentElement.hidden = true;
      segment.hidden = true;
    } else {
      const ready = fragment(change.html).firstElementChild;
      section.replaceChildren(...ready.childNodes);
      section.className = ready.className + (change.index >= resolvedSections ? ' arriving' : '');
      section.removeAttribute('data-pending'); section.removeAttribute('aria-busy');
      segment.replaceWith(fragment(change.navigation));
    }
  }
  if (preview.closing && !article.querySelector('.briefing-closing')) {
    const closing = element('p', '', 'briefing-closing');
    closing.append(fragment(preview.closing)); article.append(closing);
  }
  resolvedSections = preview.resolved;
  previewRevision = preview.revision;
  imageRevision = preview.image_revision;
  document.dispatchEvent(new Event('briefing:updated'));
}

// The bar eases to the server's position, then creeps toward the current step's
// ceiling while work runs, so long steps still show movement without overstating.
const meter = {shown: 0, target: 0, cap: 0, running: false, elapsed: null, at: 0, tick: null};
const calm = matchMedia('(prefers-reduced-motion: reduce)');

function showMeter(state) {
  meter.running = ['running', 'starting'].includes(state.state);
  meter.target = state.progress;
  meter.cap = Math.max(state.progress, meter.running && state.progress_cap || 0);
  meter.elapsed = meter.running && Number.isFinite(state.elapsed) ? state.elapsed : null;
  meter.at = performance.now();
  meter.tick ||= setInterval(stepMeter, 250);
  stepMeter();
}

function stepMeter() {
  const bar = document.querySelector('#generation-progress');
  // Never moves backwards: a pause keeps the bar where it was.
  if (calm.matches || meter.shown < meter.target - 30) meter.shown = Math.max(meter.shown, meter.target);
  else if (meter.shown < meter.target) meter.shown = Math.min(meter.target, meter.shown + Math.max(.2, (meter.target - meter.shown) * .25));
  else if (meter.running && meter.shown < meter.cap) meter.shown += (meter.cap - meter.shown) / 120;
  bar.value = meter.shown;
  const clock = document.querySelector('#generation-elapsed');
  if (meter.elapsed === null) { clock.textContent = ''; return; }
  const seconds = meter.elapsed + Math.floor((performance.now() - meter.at) / 1000);
  const time = seconds < 60 ? browserT('{seconds} s', {seconds})
    : browserT('{minutes} min {seconds} s', {minutes: Math.floor(seconds / 60), seconds: String(seconds % 60).padStart(2, '0')});
  clock.textContent = browserT('Working for {time}', {time});
}

function sectionActivity(state) {
  const pending = [...document.querySelectorAll('.briefing-section[data-pending]:not([hidden])')];
  const running = ['running', 'starting'].includes(state.state);
  pending.forEach((section, index) => {
    section.classList.toggle('is-working', index === 0 && running);
    section.classList.toggle('is-waiting', index === 0 && state.state === 'waiting');
    section.classList.toggle('is-stopped', index === 0 && ['stopped', 'uncertain'].includes(state.state));
    const target = section.querySelector('.section-loading-label');
    if (index === 0 && running && state.step_label) {
      // Already in the request's language; keep it out of the page's retranslation.
      delete target.dataset.uiText;
      target.textContent = state.step_label;
      return;
    }
    const label = index > 0 ? 'Waiting its turn'
      : state.state === 'waiting' ? 'Waiting for your answer'
      : ['stopped', 'uncertain'].includes(state.state) ? 'Preparation paused · check the briefing session'
      : resolvedSections === -1 ? 'Getting your plans ready' : 'Preparing this section';
    target.dataset.uiText=label;
    target.textContent=browserT(label);
  });
  const notice = document.querySelector('.preview-notice');
  if (notice) notice.textContent = browserT(state.state === 'stopped'
    ? 'Unfinished preview · preparation stopped. Completed sections remain below; the full briefing is not confirmed complete.'
    : 'Unfinished preview · completed sections are readable below. The full briefing is not finished yet.');
}

async function api(path, body) {
  if (body !== undefined) pendingBriefingMutations++;
  try { return await requestAPI(path, body); }
  finally {
    if (body !== undefined) {
      pendingBriefingMutations--;
      document.dispatchEvent(new Event('activity:refresh'));
    }
  }
}

async function requestAPI(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Briefing-CSRF': config.csrf },
    body: JSON.stringify(body)
  });
  const data = await goodmorningJSON(response);
  if (!response.ok) throw new Error(data.error || browserT('The secretary could not be reached.'));
  return data;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function pollRegenerationQueue() {
  clearTimeout(pollTimer);
  if (document.hidden || !queuedRegeneration) return;
  if (polling) { pollTimer = setTimeout(pollRegenerationQueue, 250); return; }
  polling = true;
  try {
    const waiting = await api('/api/queue');
    const current = await api(`/api/edition/${config.date}/${config.kind}`);
    if (current.job && current.job !== queuedRegeneration.previous) { location.reload(); return; }
    const mine = (waiting.queue || []).find(item => item.work === 'regenerate' && item.date === config.date && item.edition === config.kind);
    if (mine) {
      document.querySelector('#regeneration-status').textContent = queueLabel(mine.position, waiting.depth);
    } else {
      queuedRegeneration = null;
      document.querySelector('#regeneration-status').textContent = '';
      regenerate.disabled = false;
      document.querySelector('#regeneration-error').textContent = browserT('Regeneration did not start. Refresh the briefing before trying again.');
      return;
    }
  } catch (error) { document.querySelector('#regeneration-error').textContent = error.message; }
  finally { polling = false; }
  pollTimer = setTimeout(pollRegenerationQueue, 2500);
}

function questionForm(info) {
  if (info.checkin) return nightCheckin(info);
  return secretaryQuestion(info, replyToAgent, refreshAnswers, briefingRequestLanguage);
}

// The evening check-in asks one plain question per due item, then shows every
// not-yet-due item at once. Answers map onto the unchanged preflight form.
const checkinStates = new Map();
const checkinOpened = new Set();
const checkinDialogs = new Map();
// A refreshed task list or a queued reply replaces the form; its dialog must go too.
function pruneCheckins(keep) {
  for (const [id, dialog] of checkinDialogs) if (!keep.includes(id)) { dialog.remove(); checkinDialogs.delete(id); }
}
function nightCheckin(info) {
  const make = element, t = browserT;
  const field = key => info.fields.find(item => item.key === key);
  const due = field('completed'), early = field('completed_longterm'), details = field('details');
  const dueItems = due ? due.options.filter(option => option.value !== 'none') : [];
  const steps = [dueItems.length && 'due', early && 'early', 'details'].filter(Boolean);
  if (!checkinStates.has(info.id)) checkinStates.set(info.id, { step: 0, index: 0, verdicts: {}, early: new Set(), text: '' });
  const state = checkinStates.get(info.id);

  const launcher = make('section', '', 'agent-form checkin-launcher');
  const open = make('button', '', 'checkin-primary'); open.type = 'button';
  launcher.append(make('h2', t('Your secretary is waiting for you')),
    make('p', t('Answer a few quick questions about today, then your secretary writes your briefing.')), open);
  // The dialog lives outside the polled question area so a refresh cannot remove it mid-answer.
  if (!checkinDialogs.has(info.id)) {
    const created = make('dialog', '', 'checkin'); created.setAttribute('aria-label', info.title);
    document.body.append(created); checkinDialogs.set(info.id, created);
  }
  const dialog = checkinDialogs.get(info.id);
  open.addEventListener('click', () => dialog.showModal());
  dialog.onclose = () => { open.textContent = t('Continue check-in'); };
  dialog.onkeydown = event => {
    if (steps[state.step] !== 'due' || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === 'y') answer(true); else if (event.key === 'n') answer(false);
  };

  function answer(done) {
    state.verdicts[dueItems[state.index].value] = done;
    const next = dueItems.findIndex(option => !(option.value in state.verdicts));
    dialog.querySelector('.checkin-card')?.classList.add(done ? 'is-done' : 'is-not-done');
    setTimeout(() => { if (next < 0) { state.step++; state.index = 0; } else state.index = next; render(); }, 260);
  }
  function wins() {
    const done = dueItems.filter(option => state.verdicts[option.value]);
    const notDone = dueItems.filter(option => state.verdicts[option.value] === false);
    const earlyDone = early ? early.options.filter(option => state.early.has(option.value)) : [];
    return { done, notDone, earlyDone };
  }
  function footer(...buttons) { const row = make('div', '', 'checkin-footer'); row.append(...buttons); return row; }
  function button(text, action, primary) {
    const node = make('button', text, primary ? 'checkin-primary' : 'checkin-secondary'); node.type = 'button';
    node.addEventListener('click', action); return node;
  }
  function back() { return state.step ? button(t('Back'), () => { state.step--; state.index = 0; render(); }) : make('span'); }

  function render() {
    const body = [];
    const head = make('header', '', 'checkin-head');
    const close = make('button', '', 'checkin-close'); close.type = 'button'; close.setAttribute('aria-label', t('Close'));
    close.innerHTML = '<svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true"><path d="m6 6 8 8m0-8-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
    close.addEventListener('click', () => dialog.close());
    const avatar = document.querySelector('img[src*="desk-secretary"][src*="profile"]');
    if (avatar) { const image = avatar.cloneNode(); image.className = 'checkin-avatar'; image.alt = ''; head.append(image); }
    head.append(make('h2', info.title), close);
    const stepper = make('ol', '', 'checkin-steps');
    const names = { due: t('Due today'), early: t('Finished early?'), details: t('Anything else') };
    steps.forEach((name, index) => {
      const item = make('li', names[name]);
      if (index === state.step) item.setAttribute('aria-current', 'step'); else if (index < state.step) item.className = 'is-past';
      stepper.append(item);
    });
    body.push(head);
    if (steps.length > 1) body.push(stepper);
    const step = steps[state.step];
    const { done, notDone, earlyDone } = wins();
    if (step === 'due') {
      const option = dueItems[state.index];
      body.push(make('p', dueItems.length === 1 ? t('One thing was planned for today. Did you get it done?')
        : t('{count} things were planned for today. Did you get each one done?', { count: dueItems.length }), 'checkin-lead'));
      const card = make('div', '', 'checkin-card');
      card.append(make('p', t('{index} of {total}', { index: state.index + 1, total: dueItems.length }), 'checkin-eyebrow'), make('h3', option.label));
      if (option.description) card.append(make('p', option.description, 'checkin-meta'));
      const choices = make('div', '', 'checkin-verdict');
      const no = button(t('Not done'), () => answer(false)), yes = button(t('Done'), () => answer(true), true);
      no.append(make('kbd', 'N')); yes.append(make('kbd', 'Y'));
      if (state.verdicts[option.value] === true) yes.setAttribute('aria-pressed', 'true');
      if (state.verdicts[option.value] === false) no.setAttribute('aria-pressed', 'true');
      choices.append(no, yes); card.append(choices); body.push(card);
      const answered = make('ul', '', 'checkin-answered');
      dueItems.forEach((item, index) => {
        if (!(item.value in state.verdicts) || index === state.index) return;
        const row = make('li', '', state.verdicts[item.value] ? 'is-done' : 'is-not-done');
        const change = button(item.label, () => { state.index = index; render(); });
        change.prepend(make('span', state.verdicts[item.value] ? '✓' : '–', 'checkin-mark'));
        row.append(change); answered.append(row);
      });
      body.push(answered);
      setTimeout(() => dialog.querySelector('.checkin-verdict .checkin-primary')?.focus(), 0);
    } else if (step === 'early') {
      body.push(make('h3', t('Anything finished early?'), 'checkin-title'),
        make('p', t('None of these are due yet. Tick only what is completely done. Everything else simply stays open.'), 'checkin-lead'));
      const board = make('div', '', 'checkin-board');
      const groups = new Map();
      for (const option of early.options) {
        const name = option.group || t('Other tasks');
        if (!groups.has(name)) { const group = make('section', '', 'checkin-group'); group.append(make('h4', name)); groups.set(name, group); board.append(group); }
        const item = make('label', '', 'checkin-item');
        const box = make('input'); box.type = 'checkbox'; box.checked = state.early.has(option.value);
        box.addEventListener('change', () => { box.checked ? state.early.add(option.value) : state.early.delete(option.value); count.textContent = earlyCount(); });
        const text = make('span', option.label); if (option.description) text.append(make('small', option.description));
        item.append(box, text); groups.get(name).append(item);
      }
      const earlyCount = () => state.early.size ? t('{count} finished early', { count: state.early.size }) : t('Nothing finished early. That’s fine.');
      const count = make('span', earlyCount(), 'checkin-count');
      body.push(board, footer(back(), count, button(t('Next'), () => { state.step++; render(); }, true)));
    } else {
      body.push(make('h3', details.title, 'checkin-title'));
      if (details.description) body.push(make('p', details.description, 'checkin-lead'));
      const text = make('textarea'); text.value = state.text; text.placeholder = details.placeholder || '';
      text.setAttribute('aria-label', details.title);
      text.addEventListener('input', () => { state.text = text.value; });
      body.push(text);
      const total = done.length + earlyDone.length;
      if (steps.length > 1) {
        const summary = make('div', '', 'checkin-summary');
        summary.append(make('p', total ? t('{count} done today', { count: total }) : t('A quiet day. Thanks for checking in.'), 'checkin-total'));
        const list = make('ul');
        for (const option of done) list.append(make('li', '✓ ' + option.label, 'is-done'));
        for (const option of earlyDone) list.append(make('li', '★ ' + option.label, 'is-early'));
        for (const option of notDone) list.append(make('li', '– ' + option.label + ' · ' + t('stays open'), 'is-not-done'));
        summary.append(list); body.push(summary);
      }
      const error = make('p', '', 'checkin-error'); error.setAttribute('role', 'alert');
      const save = button(t('Save and write my briefing'), async () => {
        // Forms saved before project progress notes were removed still list them; send them empty.
        const answer = Object.fromEntries(info.fields.map(item => [item.key, '']));
        answer.details = state.text.trim() || details.options[0].value;
        if (due) answer.completed = done.length ? done.map(option => option.value) : ['none'];
        if (early) answer.completed_longterm = earlyDone.map(option => option.value);
        save.disabled = true;
        try {
          const result = await replyToAgent('form', info.id, { answer });
          launcher.remove();
          // A queued reply is not saved yet; the page's queue status says so instead.
          if (result.queued) { pruneCheckins([]); refreshAnswers(); return; }
          checkinDialogs.delete(info.id);  // Let the thank-you stay while the page refreshes.
          dialog.classList.add('is-saved');
          dialog.replaceChildren(make('p', total ? '✨' : '☾', 'checkin-burst'),
            make('h2', total ? t('{count} done today', { count: total }) : t('Thanks for checking in')),
            make('p', t('Your secretary is writing tonight’s briefing now.'), 'checkin-lead'));
          setTimeout(() => { dialog.close(); dialog.remove(); refreshAnswers(); }, 1800);
        } catch (failure) { error.textContent = failure.message; save.disabled = false; }
      }, true);
      body.push(error, footer(back(), save));
    }
    dialog.replaceChildren(...body);
  }
  render();
  open.textContent = checkinOpened.has(info.id) ? t('Continue check-in') : t('Start check-in');
  if (!checkinOpened.has(info.id)) { checkinOpened.add(info.id); setTimeout(() => { if (dialog.isConnected) dialog.showModal(); }, 300); }
  return launcher;
}

function permissionForm(info) {
  return secretaryPermission(info, replyToAgent, refreshAnswers, briefingRequestLanguage);
}

async function replyToAgent(category, id, body) {
  const result = await api(`/api/jobs/${job}/${category}/${id}/reply`, body);
  if (result.queued) {
    queuedRecovery = result.job || job;
    showBriefingQueued(result.position, result.depth);
  }
  return result;
}
function refreshAnswers() { formSignature = ''; if (queuedRecovery) pollBriefingQueue(); else poll(); }

async function poll() {
  clearTimeout(pollTimer);
  if (queuedRegeneration) { pollRegenerationQueue(); return; }
  if (!job || document.hidden || polling) return;
  polling = true;
  try {
    const state = await api(`/api/jobs/${job}`);
    if (regenerate) {
      regenerate.hidden = false;
      regenerate.disabled = !state.regeneratable || !!queuedRegeneration;
      regenerate.title = state.regeneratable ? '' : browserT(state.state === 'uncertain'
        ? 'Inspect uncertain dispatches in OpenChamber before regenerating'
        : 'Finish or stop the existing session and resolve pending inputs before regenerating');
    }
    if (state.reservation_required === false) {
      const waiting = await api('/api/queue');
      const mine = (waiting.queue || []).find(item => item.work === 'reply' && item.job === job);
      if (mine) {
        queuedRecovery = job;
        document.querySelector('#agent-questions').replaceChildren();
        pruneCheckins([]);
        formSignature = '';
        showBriefingQueued(mine.position, waiting.depth);
        pollTimer = setTimeout(pollBriefingQueue, 2500);
        return;
      }
    }
    briefingRequestLanguage = state.language;
    document.querySelector('#generation').hidden = false;
    showMeter(state);
    document.querySelector('#generation-status').textContent = state.label + (state.reservation_required === false
      ? ' ' + browserT('Take your time. Other requests can continue while you decide.') : '');
    document.querySelector('#generation-status').classList.remove('is-queued');
    const languageNote = document.querySelector('#request-language-note');
    if (languageNote) languageNote.textContent = state.language && typeof goodmorningLanguage !== 'undefined' && state.language !== goodmorningLanguage
      ? browserT('This request is finishing in {language}. New requests use your current website language.',{language:browserT(state.language==='zh-CN'?'Simplified Chinese':'English')}) : '';
    document.querySelector('.desk-animation').classList.toggle('is-paused', state.state !== 'running' && state.state !== 'starting');
    if (state.state === 'ready') { location.reload(); return; }
    await updatePreview(state);
    sectionActivity(state);
    const signature = JSON.stringify([state.forms, state.permissions]);
    if (signature !== formSignature) {
      const questions = document.querySelector('#agent-questions');
      questions.replaceChildren(...state.forms.map(questionForm), ...state.permissions.map(permissionForm));
      pruneCheckins(state.forms.map(form => form.id));
      formSignature = signature;
    }
    errorBox.textContent = state.preview_error || '';
    let recover = document.querySelector('#recover');
    if (state.recovery && !recover) {
      recover = element('button', browserT(state.recovery));
      recover.id = 'recover'; recover.type = 'button';
      errorBox.before(recover);
      recover.addEventListener('click', async () => {
        recover.disabled = true; errorBox.textContent = '';
        try {
          const outcome = await api(`/api/jobs/${job}/recover`, { id: crypto.randomUUID().replaceAll('-', '') });
          if (outcome && outcome.queued) {
            queuedRecovery = outcome.job || job;
            showBriefingQueued(outcome.position, outcome.depth);
            pollBriefingQueue();
            return;
          }
          formSignature = ''; poll();
        } catch (error) {
          errorBox.textContent = error.message;
          recover.disabled = false;
        }
      });
    }
    if (recover) {
      recover.hidden = !state.recovery;
      recover.disabled = false;
      if (state.recovery) { recover.dataset.uiText=state.recovery;recover.textContent = browserT(state.recovery); }
    }
    if (['stopped','uncertain'].includes(state.state)) return;
  } catch (error) {
    errorBox.textContent = error.message;
    document.querySelector('.desk-animation')?.classList.add('is-paused');
    sectionActivity({ state: 'uncertain' });
  }
  finally { polling = false; }
  pollTimer = setTimeout(poll, 2500);
}

async function checkDay() {
  if (document.hidden || config.pinned) return;
  try {
    const day = await api('/api/day');
    if (day.date !== config.date) location.replace(`/${config.kind}.html`);
  } catch { /* Reading cached content stays possible during an outage. */ }
}

const generate = document.querySelector('#generate');
const regenerate = document.querySelector('#regenerate');
const regenerationDialog = document.querySelector('#regenerate-dialog');
regenerate?.addEventListener('click', () => {
  regenerationDialog.returnValue = '';
  regenerationDialog.showModal();
});
regenerationDialog?.addEventListener('close', async () => {
  if (regenerationDialog.returnValue !== 'regenerate') return;
  regenerate.disabled = true;
  const errors = document.querySelector('#regeneration-error');
  errors.textContent = '';
  // Keep the same request key if the response is lost; never create another attempt automatically.
  regenerationRequest ||= {date: config.date, kind: config.kind, previous: job || config.job, id: crypto.randomUUID().replaceAll('-', '')};
  const body = regenerationRequest;
  try {
    const result = await api('/api/regenerate', body);
    if (result.queued) {
      queuedRegeneration = body;
      pollRegenerationQueue();
    } else location.reload();
  } catch (error) { errors.textContent = error.message; regenerate.disabled = false; }
});
generate?.addEventListener('click', async () => {
  generate.disabled = true; errorBox.textContent = '';
  try {
    const result = await api('/api/generate', { date: config.date, kind: config.kind });
    if (result.ready) { location.reload(); return; }
    if (result.queued) {
      queuedBriefing = {date: config.date, kind: config.kind};
      showBriefingQueued(result.position, result.depth);
      generate.hidden = true;
      pollBriefingQueue();
      return;
    }
    job = result.job; generate.hidden = true; poll();
  } catch (error) { errorBox.textContent = error.message; generate.disabled = false; }
});

async function resume() {
  if (regenerate) {
    try {
      const waiting = await api('/api/queue');
      const mine = (waiting.queue || []).find(item => item.work === 'regenerate' && item.date === config.date && item.edition === config.kind);
      if (mine) {
        queuedRegeneration = {previous: mine.previous};
        regenerate.hidden = false; regenerate.disabled = true;
        pollRegenerationQueue();
        return;
      }
    } catch { /* Server checks remain authoritative when queue status is unavailable. */ }
  }
  if (!config.missing) return;
  try {
    const current = await api(`/api/edition/${config.date}/${config.kind}`);
    if (current.job) { job = current.job; if (generate) generate.hidden = true; poll(); return; }
  } catch (error) { errorBox.textContent = error.message; return; }
  try {
    const waiting = await api('/api/queue');
    const mine = (waiting.queue || []).find(item => item.work === 'generate' && item.date === config.date && item.edition === config.kind);
    if (mine) {
      queuedBriefing = {date: config.date, kind: config.kind};
      showBriefingQueued(mine.position, waiting.depth);
      if (generate) { generate.hidden = true; generate.disabled = true; }
      pollBriefingQueue();
    }
  } catch { /* Stay on the generate button when the queue cannot be read. */ }
}
document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearTimeout(pollTimer);
  else { checkDay(); if (queuedRegeneration) pollRegenerationQueue(); else if (job) poll(); else if (queuedBriefing || queuedRecovery) pollBriefingQueue(); }
});
window.addEventListener('focus', checkDay);
document.addEventListener('website:language', () => {
  if (checkinDialogs.size) formSignature = '';  // Redraw check-in labels; its answers live in checkinStates.
  if (queuedRegeneration) pollRegenerationQueue(); else if (job) poll(); else if (queuedBriefing || queuedRecovery) pollBriefingQueue(); });
setInterval(checkDay, 60000);
checkDay(); resume();
