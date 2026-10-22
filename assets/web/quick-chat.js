// A compact view of this tab's Secretary conversation. It shares the tab-scoped
// workspace reference with /chat; private text never enters browser storage.
(() => {
  const root = document.querySelector('#quick-chat');
  if (!root) return;
  const t = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
  const $ = selector => root.querySelector(selector);
  const make = secretaryElement;
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;
  const widgetConfig = JSON.parse(root.dataset.config);
  const scope = widgetConfig.workspaceScope;
  const maxUploadBytes = widgetConfig.maxUploadBytes || 50 * 1024 * 1024;
  const workspaceKey = /^[a-f0-9]{64}$/.test(scope || '') ? 'goodmorning.chat.workspace.' + scope : null;
  const openKey = workspaceKey && 'goodmorning.quick-chat.open.' + scope;
  const launcher = $('#quick-chat-launcher');
  // Lets the back-to-top button line up beside the launcher (quick-chat.css).
  if ('ResizeObserver' in window) new ResizeObserver(() => document.documentElement.style.setProperty('--quick-chat-width', root.offsetWidth + 'px')).observe(root);
  const panel = $('#quick-chat-window');
  const textBox = $('#quick-chat-text');
  const sendButton = $('#quick-chat-send');
  const scroller = $('#quick-chat-scroll');
  const log = $('#quick-chat-messages');
  const questions = $('#quick-chat-questions');
  const statusBox = $('#quick-chat-status');
  const errorBox = $('#quick-chat-error');
  const dot = $('#quick-chat-dot');
  const attachButton = $('#quick-chat-attach');
  const fileInput = $('#quick-chat-files');
  const attachBox = $('#quick-chat-attachments');
  const awayLimit = 15 * 60 * 1000;
  const modes = {secretary: 'Secretary', todo: 'To-do', eureka: 'Eureka', initialize: 'Initialize'};
  const specialLabels = {question: 'Question for you', answer: 'Your answer', permission: 'Your permission', outreach: 'Your secretary reached out',
    expired: 'Question expired'};
  const footnotes = {outreach: 'Sent on behalf of the GoodMorning team',
    expired: 'Questions can close after about an hour without an answer. Send a message to continue where you left off.'};
  const actionTargets = {task: 'Task', event: 'Event', draft: 'Event draft', idea: 'Idea', record: 'Record', custom: 'Custom schedule'};
  const actionLabels = {added: '{target} added', updated: '{target} updated', cancelled: '{target} cancelled',
    completed: '{target} completed', approved: '{target} approved', declined: '{target} declined'};
  const imageTypes = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp']);
  const titles = new Map();
  let ready = false, connected = false, secretaryName = null;
  let chat = null, mode = 'secretary', state = null, statusLabel = '';
  let open = false, sending = false, polling = false, revision = 0, timer, titleTimer, titleRetries = 0;
  let messageSignature = '', formSignature = '', follow = true, unread = false;
  // A conversation the secretary opened, waiting to be read (persisted server-side).
  let note = null;
  // Sent messages show at once and stay until the transcript includes their turn.
  let pendingMessages = [], shownMessages = [];
  // Files wait in memory until sent, like the Secretary page; they never enter browser storage.
  let attachments = [];
  let workspace = readWorkspace();

  function validChat(id) { return typeof id === 'string' && /^[a-f0-9]{32}$/.test(id); }

  function readWorkspace() {
    try {
      const saved = workspaceKey && JSON.parse(sessionStorage.getItem(workspaceKey));
      if (!saved || (saved.chat !== null && !validChat(saved.chat))) return {};
      return {chat: saved.chat, resume: validChat(saved.resume) ? saved.resume : null,
        away: Number.isFinite(saved.away) && saved.away > 0 && saved.away <= Date.now() ? saved.away : null,
        draft: saved.draft === true};
    } catch { return {}; }
  }

  function remember(away = null, resume = workspace.resume || null) {
    workspace = {chat: validChat(chat) ? chat : null, resume, away, draft: Boolean(textBox.value.trim())};
    try { if (workspaceKey) sessionStorage.setItem(workspaceKey, JSON.stringify(workspace)); } catch { /* The Secretary link still carries the id. */ }
  }

  async function api(path, body, binary = false) {
    let response;
    try {
      response = await fetch(path, {method: body ? 'POST' : 'GET', cache: 'no-store', credentials: 'same-origin',
        headers: body ? {'Content-Type': binary ? 'application/octet-stream' : 'application/json', 'X-Briefing-CSRF': csrf} : {},
        body: body ? (binary ? body : JSON.stringify(body)) : undefined});
    } catch {
      const error = new Error(t('The connection was interrupted. Refresh to check delivery before sending again.'));
      error.uncertain = Boolean(body); throw error;
    } finally { if (body) document.dispatchEvent(new Event('activity:refresh')); }
    if (response.status === 401) { location.replace('/login'); throw new Error(t('Please sign in again.')); }
    let result;
    try {
      result = await goodmorningJSON(response);
      if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Invalid response');
    } catch (cause) {
      const error = new Error(response.status === 429 ? cause.message : t('The server returned an unreadable response. Your draft is safe.'));
      error.status = response.status;
      error.uncertain = Boolean(body) && (response.ok || response.status >= 500);
      if (error.uncertain) error.message += ' ' + t('Refresh to check delivery before sending again.');
      throw error;
    }
    if (!response.ok) {
      const error = new Error(result.error || t('The secretary is unavailable.'));
      error.status = response.status; error.uncertain = Boolean(body) && response.status >= 500; throw error;
    }
    return result;
  }

  function showAvatar(settings) {
    const entry = (settings.avatars || []).find(item => item.id === settings.avatar) || (settings.avatars || [])[0];
    const source = entry && (entry.profile || entry[document.documentElement.dataset.edition === 'gn' ? 'night' : 'day']);
    if (typeof source !== 'string' || !source.startsWith('/')) return;
    root.querySelectorAll('.quick-chat-portrait').forEach(portrait => {
      const image = portrait.querySelector('img');
      if (image.getAttribute('src') !== source) image.src = source;
    });
  }

  function showHeader() {
    const name = secretaryName || t('Your secretary');
    const ask = note ? (secretaryName ? t('New message from {name}', {name: secretaryName}) : t('New message from your secretary'))
      : secretaryName ? t('Ask {name}', {name: secretaryName}) : t('Ask your secretary');
    $('#quick-chat-launcher-label').textContent = ask;
    launcher.classList.toggle('has-note', Boolean(note));
    launcher.setAttribute('aria-label', [ask, ...(dot.hidden || note ? [] : [dot.title])].join(' · '));
    $('#quick-chat-title').textContent = titles.get(chat) || t(chat ? 'Conversation' : 'New conversation');
    $('#quick-chat-mode').textContent = t(modes[mode] || 'Secretary') + ' · ' + name;
    $('#quick-chat-open').href = chat ? '/chat?id=' + chat : '/chat';
    const resume = !chat && validChat(workspace.resume);
    $('#quick-chat-resume').hidden = !resume;
    if (resume) $('#quick-chat-resume-link').href = '/chat?id=' + workspace.resume;
    $('#quick-chat-empty').hidden = Boolean(chat) || sending || log.childElementCount > 0;
  }

  function showDot() {
    const label = state === 'waiting' ? 'Your secretary needs your answer'
      : ['starting', 'running', 'queued'].includes(state) ? 'Your secretary is working' : unread ? 'A new reply is ready'
      : note ? 'New message from your secretary' : '';
    dot.hidden = open || !label;
    dot.dataset.state = state === 'waiting' ? 'waiting' : ['starting', 'running', 'queued'].includes(state) ? 'working'
      : unread ? 'unread' : 'note';
    dot.title = label ? t(label) : '';
    showHeader();
  }

  function showStatus() {
    const active = sending || ['starting', 'running'].includes(state);
    const text = t(sending ? 'Sending your message' : state === 'starting' ? 'Opening your conversation'
      : state === 'running' ? 'Your secretary is working' : state === 'idle' ? '' : statusLabel);
    statusBox.replaceChildren();
    if (active) {
      const dots = make('span', '', 'quick-chat-dots'); dots.setAttribute('aria-hidden', 'true');
      dots.append(make('span'), make('span'), make('span'));
      statusBox.append(dots);
    }
    statusBox.append(make('span', text));
    statusBox.hidden = !text;
    const blocked = chat && ['waiting', 'uncertain', 'unavailable'].includes(state);
    sendButton.disabled = sending || !connected || blocked || (!textBox.value.trim() && !attachments.length);
    textBox.disabled = sending || blocked;
    attachButton.disabled = sending || !connected || blocked;
    attachBox.querySelectorAll('button').forEach(button => { button.disabled = sending; });
    sendButton.setAttribute('aria-label', t(chat ? 'Send reply' : 'Send message'));
    showDot();
  }

  function active() { return ['starting', 'running', 'queued'].includes(state); }
  function nearLatest() { return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80; }
  function scrollToLatest() { scroller.scrollTop = scroller.scrollHeight; }

  function resizeComposer() {
    textBox.style.height = 'auto';
    textBox.style.height = Math.min(textBox.scrollHeight, parseFloat(getComputedStyle(textBox).maxHeight) || 120) + 'px';
  }

  function messageLabel(item) {
    if (item.kind === 'action') {
      const target = t(actionTargets[item.action?.target] || 'Record');
      return t(actionLabels[item.action?.operation] || '{target} updated', {target});
    }
    return Object.hasOwn(specialLabels, item.kind) ? t(specialLabels[item.kind]) : '';
  }

  function showMessages(messages) {
    shownMessages = messages;
    const delivered = new Set(messages.map(item => item.turn).filter(Boolean));
    pendingMessages = pendingMessages.filter(item => !delivered.has(item.turn));
    const visible = [...messages, ...pendingMessages.map(item => ({...item, role: 'user', pending: true}))];
    const signature = JSON.stringify([visible, typeof goodmorningLanguage === 'undefined' ? '' : goodmorningLanguage]);
    if (signature === messageSignature) return false;
    messageSignature = signature;
    log.replaceChildren(...visible.map(item => {
      const bubble = make('div', '', 'quick-chat-message ' + (item.role === 'user' ? 'user' : 'assistant')
        + (item.kind ? ' special' : '') + (item.pending ? ' pending' : ''));
      if (item.language) bubble.lang = item.language;
      const label = messageLabel(item);
      if (label) bubble.append(make('p', label, 'quick-chat-label'));
      const content = make('div', '', 'quick-chat-text');
      if (item.kind === 'outreach') bubble.classList.add('outreach');
      if (item.role === 'assistant' && (!item.kind || item.kind === 'outreach')) {
        try { content.classList.add('message-markdown'); content.append(secretaryMarkdown(item.text)); }
        catch { content.classList.remove('message-markdown'); content.textContent = item.text; }
      } else content.textContent = item.text;
      bubble.append(content);
      if (footnotes[item.kind]) bubble.append(make('p', t(footnotes[item.kind]), 'quick-chat-footnote'));
      for (const entry of item.attachments || []) {
        const file = make('p', '', 'quick-chat-attachment');
        if (entry.preview || (imageTypes.has(entry.mime) && /^[a-f0-9]{32}$/.test(entry.id))) {
          const image = make('img'); image.alt = entry.name; image.src = entry.preview || `/api/chat-uploads/${entry.id}/image`;
          file.append(image);
        } else file.textContent = '📎 ' + entry.name;
        bubble.append(file);
      }
      return bubble;
    }));
    return true;
  }

  function showForms(result, current, version) {
    const signature = JSON.stringify([result.forms, result.permissions, result.language]);
    if (signature === formSignature) return false;
    formSignature = signature;
    const refreshed = () => { formSignature = ''; follow = true; poll(); };
    const reply = async (category, id, body) => {
      const receipt = await api(`/api/chats/${current}/${category}/${id}/reply`, body);
      if (version === revision && receipt.queued) { state = 'queued'; statusLabel = queueText(receipt.position, receipt.depth); showStatus(); }
      return receipt;
    };
    questions.replaceChildren(...result.forms.map(info => secretaryQuestion(info, reply, refreshed, result.language)),
      ...result.permissions.map(info => secretaryPermission(info, reply, refreshed, result.language)));
    return true;
  }

  function queueText(position, depth) {
    const place = t('You are #{position} in line', {position});
    return depth > 1 ? `${t('In queue')} · ${place} · ${t('{depth} waiting', {depth})}` : `${t('In queue')} · ${place}`;
  }

  async function pollQueue(current, version) {
    const status = await api('/api/queue');
    if (version !== revision) return null;
    const mine = (status.queue || []).find(item => ['chat', 'reply'].includes(item.work) && item.chat === current);
    return mine ? {...mine, depth: status.depth} : null;
  }

  // While open, read the full conversation; while minimized, only its read-only status.
  async function poll() {
    clearTimeout(timer);
    if (!chat || document.hidden || polling) return;
    polling = true;
    const current = chat, version = revision, full = open;
    try {
      if (state === 'queued') {
        const mine = await pollQueue(current, version);
        if (version !== revision) return;
        if (mine) { statusLabel = queueText(mine.position, mine.depth); return; }
        state = 'starting';
      }
      const result = await api(`/api/chats/${current}${full ? '' : '/status'}`);
      if (version !== revision) return;
      const wasActive = ['starting', 'running', 'queued'].includes(state);
      mode = result.mode; state = result.state; statusLabel = result.label;
      if (typeof result.secretary_name === 'string' && result.secretary_name) secretaryName = result.secretary_name;
      if (result.reservation_required === false) {
        const mine = await pollQueue(current, version);
        if (version !== revision) return;
        if (mine?.work === 'reply') { state = 'queued'; statusLabel = queueText(mine.position, mine.depth); formSignature = ''; questions.replaceChildren(); return; }
      }
      if (full && result.unread) api(`/api/chats/${current}/seen`, {}).then(refreshTitles).catch(() => {});
      if (full) {
        const keep = follow || nearLatest();
        const messagesChanged = result.messages ? showMessages(result.messages) : false;
        const formsChanged = showForms(result, current, version);
        if (keep && (messagesChanged || formsChanged)) scrollToLatest();
        follow = false;
      } else if (wasActive && ['idle', 'waiting'].includes(state)) unread = true;
      if (['idle', 'waiting'].includes(state)) refreshTitles();
    } catch (error) {
      if (version !== revision) return;
      if (error.status === 404 && !(await pollQueue(current, version).catch(() => null))) {
        newConversation();
        errorBox.textContent = t('This conversation is no longer available. Start a new one.');
        return;
      }
      if (error.status === 404) state = 'queued';
      else if (full) { state = 'unavailable'; errorBox.textContent = error.message; }
    } finally {
      polling = false;
      if (version === revision) {
        showStatus();
        if (chat && !['idle', 'uncertain', 'unavailable'].includes(state) && (open || state !== 'waiting')) timer = setTimeout(poll, 2500);
      } else if (chat) timer = setTimeout(poll, 0);
    }
  }

  async function refreshTitles() {
    clearTimeout(titleTimer);
    try {
      const result = await api('/api/chats');
      connected = result.connected;
      for (const item of result.chats || []) titles.set(item.id, item.title);
      findNote(result.chats);
      if (typeof result.secretary_name === 'string' && result.secretary_name) secretaryName = result.secretary_name;
      showStatus();
      if (chat && (result.chats || []).some(item => item.id === chat && item.title_pending) && titleRetries++ < 20)
        titleTimer = setTimeout(refreshTitles, 3000);
    } catch { /* Titles are decoration; the conversation stays usable. */ }
  }

  function findNote(chats) {
    note = (chats || []).find(item => item.unread && !(open && item.id === chat))?.id || null;
  }

  function reset() {
    clearTimeout(timer); clearTimeout(titleTimer); revision++; titleRetries = 0;
    state = null; statusLabel = ''; messageSignature = ''; formSignature = ''; follow = true; unread = false;
    pendingMessages = []; shownMessages = [];
    log.replaceChildren(); questions.replaceChildren(); errorBox.textContent = '';
  }

  function newConversation(resume = null) {
    reset(); chat = null; mode = 'secretary';
    remember(open ? null : Date.now(), resume);
    showStatus();
    if (open) textBox.focus({preventScroll: true});
  }

  function openConversation(id) {
    reset(); chat = id; state = 'starting';
    remember(open ? null : workspace.away);
    showStatus(); poll();
  }

  // Match /chat: settled conversations open as a fresh draft after 15 minutes away.
  async function restore() {
    const saved = workspace;
    if (!validChat(saved.chat)) { chat = null; showStatus(); return; }
    if (saved.away && Date.now() - saved.away >= awayLimit && !saved.draft) {
      try {
        const status = await api(`/api/chats/${saved.chat}/status`);
        if (status.state === 'idle' && !(status.forms || []).length && !(status.permissions || []).length) {
          chat = saved.chat; newConversation(saved.chat); return;
        }
      } catch { /* The poller reports missing or unavailable conversations. */ }
    }
    if (saved.chat !== chat) openConversation(saved.chat);
    else poll();
  }

  function present(value, animate) {
    open = value;
    try { if (openKey) open ? sessionStorage.setItem(openKey, '1') : sessionStorage.removeItem(openKey); } catch { /* Opening still works. */ }
    document.body.classList.toggle('quick-chat-open', open);
    launcher.setAttribute('aria-expanded', String(open));
    const [show, hide] = open ? [panel, launcher] : [launcher, panel];
    hide.hidden = true; show.hidden = false;
    if (animate && !matchMedia('(prefers-reduced-motion: reduce)').matches)
      show.animate([{opacity: 0, transform: 'translateY(10px) scale(.98)'}, {opacity: 1, transform: 'none'}],
        {duration: open ? 260 : 200, easing: 'cubic-bezier(.22, 1, .36, 1)'});
  }

  async function openWindow(animate = true) {
    unread = false; follow = true; present(true, animate); fitViewport();
    messageSignature = ''; formSignature = '';
    await restore();
    remember(null);
    resizeComposer(); scrollToLatest();
    if (animate) (matchMedia('(pointer: fine)').matches ? textBox : panel).focus({preventScroll: true});
  }

  function closeWindow() {
    present(false, true); remember(Date.now());
    launcher.focus({preventScroll: true});
    if (active()) poll();
  }

  function fileSize(size) {
    return size < 1024 * 1024 ? `${Math.ceil(size / 1024)} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  function releasePreviews(entries) {
    for (const entry of entries) if (entry.preview) URL.revokeObjectURL(entry.preview);
  }

  function showAttachments() {
    attachBox.replaceChildren(...attachments.map(entry => {
      const chip = make('div', '', 'quick-chat-chip');
      if (entry.preview) { const image = make('img'); image.alt = ''; image.src = entry.preview; chip.append(image); }
      chip.append(make('span', `${entry.file.name} · ${fileSize(entry.file.size)}`));
      const remove = make('button', '×');
      remove.type = 'button';
      remove.setAttribute('aria-label', t('Remove {name}', {name: entry.file.name}));
      remove.addEventListener('click', () => {
        releasePreviews([entry]);
        attachments = attachments.filter(item => item !== entry);
        showAttachments(); textBox.focus({preventScroll: true});
      });
      chip.append(remove);
      return chip;
    }));
    attachBox.hidden = !attachments.length;
    showStatus();
  }

  function addFiles(files) {
    if (attachButton.disabled) return;
    errorBox.textContent = '';
    for (const file of files) {
      if (file.size > maxUploadBytes) { errorBox.textContent = t('Files must be 50 MB or smaller.'); continue; }
      if (attachments.length >= 100) { errorBox.textContent = t('Attach up to 100 files per message.'); break; }
      attachments.push({file, id: crypto.randomUUID().replaceAll('-', ''), uploaded: false,
        preview: imageTypes.has(file.type) ? URL.createObjectURL(file) : null});
    }
    showAttachments();
  }

  attachButton.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });
  textBox.addEventListener('paste', event => {
    const clipboard = event.clipboardData;
    const files = Array.from(clipboard?.items || []).filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean);
    if (!files.length) files.push(...Array.from(clipboard?.files || []));
    if (!files.length) return;
    event.preventDefault();
    addFiles(files);
    const text = clipboard.getData('text/plain');
    if (text) {
      textBox.setRangeText(text, textBox.selectionStart, textBox.selectionEnd, 'end');
      textBox.dispatchEvent(new Event('input', {bubbles: true}));
    }
  });
  const draggingFiles = event => Array.from(event.dataTransfer?.types || []).includes('Files');
  let dragDepth = 0;
  panel.addEventListener('dragenter', event => {
    if (!draggingFiles(event) || attachButton.disabled) return;
    event.preventDefault(); dragDepth++; panel.classList.add('is-dragging');
  });
  panel.addEventListener('dragleave', event => {
    if (!draggingFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) panel.classList.remove('is-dragging');
  });
  // A file dropped elsewhere on the page must not navigate away from an open, unsent draft.
  for (const name of ['dragover', 'drop']) document.addEventListener(name, event => {
    if (!open || !draggingFiles(event)) return;
    event.preventDefault();
    if (name === 'dragover') event.dataTransfer.dropEffect = panel.contains(event.target) && !attachButton.disabled ? 'copy' : 'none';
    else {
      dragDepth = 0; panel.classList.remove('is-dragging');
      if (panel.contains(event.target)) addFiles(event.dataTransfer.files);
    }
  });

  launcher.addEventListener('click', () => {
    // A waiting note opens instead of the last conversation; reading it clears the note.
    if (note) { const id = note; note = null; reset(); chat = id; remember(null); }
    openWindow();
  });
  $('#quick-chat-minimize').addEventListener('click', closeWindow);
  $('#quick-chat-new').addEventListener('click', () => newConversation());
  $('#quick-chat-open').addEventListener('click', () => remember(null));
  $('#quick-chat-resume-link').addEventListener('click', event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); openConversation(workspace.resume);
  });
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !document.querySelector('dialog[open]')) { event.preventDefault(); closeWindow(); }
  });
  textBox.addEventListener('input', () => { resizeComposer(); showStatus(); });
  textBox.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!sendButton.disabled) $('#quick-chat-compose').requestSubmit();
  });

  $('#quick-chat-compose').addEventListener('submit', async event => {
    event.preventDefault();
    if (sendButton.disabled) return;
    const first = !chat, request = crypto.randomUUID().replaceAll('-', ''), current = chat || request, version = revision;
    const text = textBox.value;
    const selectedFiles = attachments;
    sending = true; errorBox.textContent = ''; showStatus(); showHeader();
    const pending = {turn: request, text, attachments: selectedFiles.map(entry => ({id: entry.id, name: entry.file.name,
      size: entry.file.size, preview: entry.preview}))};
    pendingMessages.push(pending);
    showMessages(shownMessages); scrollToLatest();
    let result;
    try {
      for (const entry of selectedFiles) {
        if (!entry.uploaded) {
          await api(`/api/chat-uploads/${entry.id}?name=${encodeURIComponent(entry.file.name)}`, entry.file, true);
          entry.uploaded = true;
        }
        if (version !== revision) return;
      }
      const body = first ? {id: current, mode: 'secretary', text} : {id: request, text};
      if (selectedFiles.length) body.attachments = selectedFiles.map(entry => entry.id);
      result = await api(first ? '/api/chats' : `/api/chats/${current}/messages`, body);
      if (version !== revision) return;
      chat = current; textBox.value = ''; resizeComposer();
      attachments = []; showAttachments();
      // Keep local previews until the transcript shows the delivered turn's own images.
      setTimeout(() => releasePreviews(selectedFiles), 60000);
      state = result?.queued ? 'queued' : 'starting';
      statusLabel = result?.queued ? queueText(result.position, result.depth) : '';
      follow = true; remember(null, null);
    } catch (error) {
      if (version !== revision) return;
      // The draft stays in the composer; the transcript shows it if it did arrive.
      pendingMessages = pendingMessages.filter(item => item !== pending);
      showMessages(shownMessages);
      errorBox.textContent = error.status === 429 ? t(error.message) : error.message;
      if (error.uncertain) { chat = current; state = 'uncertain'; remember(null, null); }
    } finally {
      if (version === revision) {
        sending = false; showStatus();
        if (open && matchMedia('(pointer: fine)').matches) textBox.focus({preventScroll: true});
        if (chat) poll();
      }
    }
  });

  // Keep the sheet above a phone keyboard without resizing the page beneath it.
  const viewport = window.visualViewport;
  function fitViewport() {
    if (!viewport || !open) return;
    root.style.setProperty('--quick-chat-keyboard', Math.max(0, innerHeight - viewport.height - viewport.offsetTop) + 'px');
    root.style.setProperty('--quick-chat-viewport', viewport.height + 'px');
  }
  viewport?.addEventListener('resize', fitViewport);
  viewport?.addEventListener('scroll', fitViewport);

  // On phones, floating buttons slide away while reading down and return on scroll up,
  // near the top or end, after a pause, or when keyboard focus reaches them.
  const phone = matchMedia('(max-width: 700px)');
  let lastY = scrollY, pause;
  const tuck = value => document.documentElement.classList.toggle('floaters-tucked', value);
  window.addEventListener('scroll', () => {
    const y = scrollY, down = y > lastY + 4, up = y < lastY - 4;
    if (down || up) lastY = y;
    clearTimeout(pause);
    if (!phone.matches || open || up || y < 80 || y + innerHeight >= document.documentElement.scrollHeight - 80) return tuck(false);
    if (down) tuck(true);
    pause = setTimeout(() => tuck(false), 1200);
  }, {passive: true});
  document.addEventListener('focusin', event => {
    if (event.target.closest?.('#quick-chat, #mobile-sections, .back-to-top')) tuck(false);
  });

  // Review links open this panel with a starter line instead of leaving the page; nothing sends by itself.
  document.addEventListener('click', event => {
    const link = event.target.closest?.('[data-quick-ask]');
    if (!link || !ready || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const starter = t(link.dataset.quickAsk, {title: link.dataset.quickAskTitle || ''});
    (open ? Promise.resolve() : openWindow()).then(() => {
      if (!textBox.value.trim()) { textBox.value = starter; resizeComposer(); showStatus(); }
      textBox.focus({preventScroll: true});
    });
  });

  window.addEventListener('pagehide', () => { if (open) remember(Date.now()); });
  window.addEventListener('pageshow', event => {
    if (!event.persisted || !ready) return;
    workspace = readWorkspace();
    if (open) restore(); else { chat = workspace.chat || null; poll(); }
  });
  window.addEventListener('beforeunload', event => {
    if (!textBox.value.trim() && !attachments.length && !sending) return;
    event.preventDefault(); event.returnValue = '';
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden || !ready) return;
    if (open || active()) poll();
    else refreshTitles();
  });
  document.addEventListener('website:before-refresh', event => { if (sending) event.preventDefault(); });
  document.addEventListener('website:refresh-drafts', event => { if (textBox.value.trim() || attachments.length) event.preventDefault(); });
  document.addEventListener('website:language', () => {
    messageSignature = ''; formSignature = '';
    showStatus(); if (open) poll();
  });
  document.addEventListener('secretary:avatar', () => api('/api/avatar').then(showAvatar).catch(() => {}));

  async function start() {
    let settings, avatars;
    try { [settings, avatars] = await Promise.all([api('/api/chats'), api('/api/avatar')]); }
    catch { return; }
    if (settings.defaultMode !== 'secretary') return;
    ready = true; connected = settings.connected;
    if (typeof settings.secretary_name === 'string' && settings.secretary_name) secretaryName = settings.secretary_name;
    for (const item of settings.chats || []) titles.set(item.id, item.title);
    findNote(settings.chats);
    showAvatar(avatars);
    root.hidden = false;
    if (!connected) errorBox.textContent = t('The secretary is unavailable.');
    let reopen = false;
    try { reopen = Boolean(openKey && sessionStorage.getItem(openKey)); } catch { /* Start minimized. */ }
    if (reopen) openWindow(false);
    else {
      present(false, false);
      if (validChat(workspace.chat)) { chat = workspace.chat; poll(); }
      showStatus();
    }
  }
  start();
})();
