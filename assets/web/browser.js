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
  document.querySelector('#generation-progress').value = 2;
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

function sectionActivity(state) {
  const pending = [...document.querySelectorAll('.briefing-section[data-pending]:not([hidden])')];
  const running = ['running', 'starting'].includes(state.state);
  pending.forEach((section, index) => {
    section.classList.toggle('is-working', index === 0 && running);
    section.classList.toggle('is-waiting', index === 0 && state.state === 'waiting');
    section.classList.toggle('is-stopped', index === 0 && ['stopped', 'uncertain'].includes(state.state));
    const label = index > 0 ? 'Waiting its turn'
      : state.state === 'waiting' ? 'Waiting for your answer'
      : ['stopped', 'uncertain'].includes(state.state) ? 'Preparation paused · check the briefing session'
      : resolvedSections === -1 ? 'Getting your plans ready' : 'Preparing this section';
    section.querySelector('.section-loading-label').dataset.uiText=label;
    section.querySelector('.section-loading-label').textContent=browserT(label);
  });
  const notice = document.querySelector('.preview-notice');
  if (notice) notice.textContent = browserT(state.state === 'stopped'
    ? 'Unfinished preview · preparation stopped. Completed sections remain below; the full briefing is not confirmed complete.'
    : 'Unfinished preview · completed sections are readable below. The full briefing is not finished yet.');
}

async function api(path, body) {
  if (body !== undefined) pendingBriefingMutations++;
  try { return await requestAPI(path, body); }
  finally { if (body !== undefined) pendingBriefingMutations--; }
}

async function requestAPI(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Briefing-CSRF': config.csrf },
    body: JSON.stringify(body)
  });
  const data = await response.json();
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
  return secretaryQuestion(info, replyToAgent, refreshAnswers, briefingRequestLanguage);
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
        formSignature = '';
        showBriefingQueued(mine.position, waiting.depth);
        pollTimer = setTimeout(pollBriefingQueue, 2500);
        return;
      }
    }
    briefingRequestLanguage = state.language;
    document.querySelector('#generation').hidden = false;
    document.querySelector('#generation-progress').value = state.progress;
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
document.addEventListener('website:language', () => { if (queuedRegeneration) pollRegenerationQueue(); else if (job) poll(); else if (queuedBriefing || queuedRecovery) pollBriefingQueue(); });
setInterval(checkDay, 60000);
checkDay(); resume();
