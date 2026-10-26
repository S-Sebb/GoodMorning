// Tab-scoped workspace references supplement the URL. Private text never enters browser storage.
const chatConfig = JSON.parse(document.querySelector('#chat-config').dataset.config);
const chatT = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
const modes = {
  initialize: ['Let’s make this yours.', 'Start initialization'],
  secretary: ['A little space to plan.', 'Start conversation']
};
const textBox = document.querySelector('#chat-text');
const sendButton = document.querySelector('#chat-send');
const errorBox = document.querySelector('#chat-error');
const fileInput = document.querySelector('#chat-files');
const attachButton = document.querySelector('#chat-attach');
const composer = document.querySelector('#chat-compose');
const chatScroll = document.querySelector('#chat-scroll');
const latestButton = document.querySelector('#chat-latest');
const chatLayout = document.querySelector('.chat-layout');
const conversationPanel = document.querySelector('#conversation');
const chatViewport = window.visualViewport || {get width() { return innerWidth; }, get height() { return innerHeight; }, offsetTop: 0, scale: 1};
let viewportFrame;
let viewportSignature;
let mobileLayoutWidth = innerWidth;
let mobileLayoutHeight = innerHeight;

function resizeChatViewport() {
  cancelAnimationFrame(viewportFrame);
  viewportFrame = requestAnimationFrame(() => {
    const mobile = matchMedia('(max-width: 700px)').matches;
    if (mobileLayoutWidth !== innerWidth) { mobileLayoutWidth = innerWidth; mobileLayoutHeight = innerHeight; }
    mobileLayoutHeight = Math.max(mobileLayoutHeight, innerHeight);
    const panelTop = conversationPanel.getBoundingClientRect().top + window.scrollY;
    const keyboardOpen = mobile && document.activeElement === textBox
      && (innerHeight - chatViewport.height > 100 || mobileLayoutHeight - innerHeight > 100);
    const signature = [mobile, keyboardOpen, panelTop, innerHeight, chatViewport.width, chatViewport.height,
      chatViewport.offsetTop, chatViewport.scale].join(':');
    // Page scrolling must not resize the panel or pull readers back to the input.
    if (signature === viewportSignature) return;
    viewportSignature = signature;
    if (mobile && chatViewport.scale !== 1) return;
    if (!mobile) {
      conversationPanel.classList.remove('is-keyboard-open');
      chatLayout.style.removeProperty('--chat-viewport-height');
      chatLayout.style.removeProperty('--chat-keyboard-inset');
      chatLayout.style.removeProperty('--chat-panel-height');
      resizeComposer(undefined, false);
      updateScrollTools();
      return;
    }
    const follow = nearLatest();
    const followDraft = textBox.scrollHeight - textBox.scrollTop - textBox.clientHeight < 1;
    const previousTop = chatScroll.scrollTop;
    const previousHeight = conversationPanel.offsetHeight;
    conversationPanel.classList.toggle('is-keyboard-open', keyboardOpen);
    chatLayout.style.setProperty('--chat-viewport-height', `${chatViewport.height}px`);
    chatLayout.style.setProperty('--chat-panel-height', `${Math.max(keyboardOpen ? 280 : 240, chatViewport.height - panelTop - 12)}px`);
    // Keep the page's scroll range when only the visual viewport shrinks.
    chatLayout.style.setProperty('--chat-keyboard-inset', `${Math.max(0, innerHeight - chatViewport.height)}px`);
    if (previousHeight !== conversationPanel.offsetHeight) resizeComposer(undefined, follow, followDraft);
    if (follow && previousHeight !== conversationPanel.offsetHeight) scrollToLatest();
    else {
      if (!follow) chatScroll.scrollTop = previousTop;
      updateScrollTools();
    }
    if (document.activeElement === textBox) {
      const gap = conversationPanel.getBoundingClientRect().bottom - chatViewport.offsetTop - chatViewport.height;
      if (gap > 1 || composer.getBoundingClientRect().top < chatViewport.offsetTop) {
        window.scrollBy({top: gap, behavior: 'instant'});
      }
    }
  });
}

{
  window.visualViewport?.addEventListener('resize', resizeChatViewport);
  window.visualViewport?.addEventListener('scroll', resizeChatViewport);
  window.addEventListener('resize', resizeChatViewport);
  const headerObserver = new ResizeObserver(resizeChatViewport);
  document.querySelectorAll('.masthead, .toolbar-row, .secretary-identity').forEach(node => headerObserver.observe(node));
}

function resizeComposer(event, follow = nearLatest(), followDraft = false) {
  const previousHeight = textBox.offsetHeight;
  const previousScroll = textBox.scrollTop;
  textBox.style.height = 'auto';
  const maxHeight = parseFloat(getComputedStyle(textBox).maxHeight);
  const height = Math.min(textBox.scrollHeight, maxHeight);
  textBox.style.height = `${height}px`;
  textBox.style.overflowY = textBox.scrollHeight > height ? 'auto' : 'hidden';
  textBox.scrollTop = (event?.type === 'input' || followDraft) && textBox.selectionEnd === textBox.value.length
    ? textBox.scrollHeight : previousScroll;
  if (follow && previousHeight !== textBox.offsetHeight) scrollToLatest();
}
textBox.addEventListener('input', resizeComposer);
textBox.addEventListener('focus', resizeChatViewport);
textBox.addEventListener('blur', resizeChatViewport);
window.addEventListener('resize', resizeComposer);
document.addEventListener('scrollrails:layout', resizeComposer);
let attachments = [];
const make = secretaryElement;
// Older To-do/Eureka chats keep their mode label; new conversations use the profile's default.
let mode = chatConfig.defaultMode;
let chat = new URLSearchParams(location.search).get('id');
let state = null;
let sending = false;
let pendingChatMutations = 0;
let polling = false;
let timer;
let titleTimer;
let titleRetries = 0;
let formSignature = '';
let messageSignature = '';
let animateMessages = false;
// Sent messages show at once and stay until the transcript includes their turn.
let pendingMessages = [];
let shownMessages = [];
let followNextUpdate = true;
let statusLabel = '';
let readError = null;
let revision = 0;
let requestLanguage = null;
let secretaryName = typeof chatConfig.secretary_name === 'string' && chatConfig.secretary_name ? chatConfig.secretary_name : null;
const drafts = new Map();
const conversationTitles = new Map();
const workspaceKey = /^[a-f0-9]{64}$/.test(chatConfig.workspaceScope || '')
  ? 'goodmorning.chat.workspace.' + chatConfig.workspaceScope : null;
const awayLimit = 15 * 60 * 1000;
let restoringWorkspace = false;
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

function hasUnsentInput() {
  return Boolean(textBox.value.trim() || attachments.length || sending || pendingChatMutations
    || [...drafts.values()].some(draft => draft.text.trim() || draft.attachments.length)
    // Question answers count only once they differ from the question's own defaults.
    || [...document.querySelectorAll('#chat-questions input, #chat-questions textarea')]
      .some(input => input.type === 'checkbox' || input.type === 'radio' ? input.checked !== input.defaultChecked
        : input.value.trim() !== input.defaultValue.trim()));
}

function rememberWorkspace(away = null, resume = workspace.resume || null) {
  workspace = {chat: validChat(chat) ? chat : null, resume, away, draft: hasUnsentInput()};
  try { if (workspaceKey) sessionStorage.setItem(workspaceKey, JSON.stringify(workspace)); } catch { /* URL navigation still works. */ }
}

function leaveSecretary() {
  // visibilitychange and pagehide can both fire; keep the beginning of the absence.
  rememberWorkspace(workspace.away || Date.now());
}

function showTopic() {
  document.querySelector('#chat-topic').textContent = conversationTitles.get(chat) || chatT(chat ? 'Conversation' : 'New conversation');
  document.querySelector('#chat-topic-mode').textContent = chatT(mode === 'todo' ? 'To-do' : mode[0].toUpperCase() + mode.slice(1));
  // A fresh conversation has nothing to continue or replace yet.
  document.querySelector('#new-conversation').hidden = !chat;
  document.querySelector('.chat-topic-hint').hidden = !chat;
  const resume = !chat && validChat(workspace.resume);
  document.querySelector('#chat-resume-notice').hidden = !resume;
  if (resume) document.querySelector('#chat-resume').href = '/chat?id=' + workspace.resume;
}

async function restoreWorkspace(initial = false) {
  if (restoringWorkspace) return;
  // Conversation links and setup links (?mode=) open their destination, not the workspace.
  if (initial && ['id', 'mode'].some(name => new URLSearchParams(location.search).has(name))) {
    rememberWorkspace(null, null); showTopic(); return;
  }
  const saved = workspace;
  const candidate = chat || saved.chat;
  if (!validChat(candidate)) { showTopic(); return; }
  restoringWorkspace = true; conversationPanel.setAttribute('aria-busy', 'true'); composeState();
  const version = revision;
  try {
    if (saved.away && Date.now() - saved.away >= awayLimit && !saved.draft && !hasUnsentInput()) {
      // Only a fresh, read-only account-scoped status can authorize a visual reset.
      const status = await chatAPI(`/api/chats/${candidate}/status`);
      if (version !== revision || document.hidden) return;
      if (status.state === 'idle' && !(status.forms || []).length && !(status.permissions || []).length) {
        newConversation({resume: candidate});
        return;
      }
    }
    if (version !== revision) return;
    if (!chat) openConversation(candidate, {push: false});
    rememberWorkspace(document.hidden ? saved.away : null);
    showTopic();
  } catch {
    // Missing/queued recovery and connection errors belong to the existing poller.
    if (version === revision && !chat) openConversation(candidate, {push: false});
    if (version === revision) rememberWorkspace(document.hidden ? saved.away : null);
  } finally {
    restoringWorkspace = false; conversationPanel.setAttribute('aria-busy', 'false'); composeState();
  }
}

window.addEventListener('pagehide', leaveSecretary);
window.addEventListener('beforeunload', event => {
  if (!hasUnsentInput()) return;
  event.preventDefault(); event.returnValue = '';
});
window.addEventListener('pageshow', event => {
  if (!event.persisted) return;
  // Quick chat on another page may have moved this tab to another conversation.
  const saved = readWorkspace();
  if (Object.hasOwn(saved, 'chat') && saved.chat !== chat) {
    workspace = saved;
    if (saved.chat) openConversation(saved.chat, {push: false});
    else newConversation({resume: saved.resume});
  }
  returnToSecretary();
});
const renderedMessages = new WeakMap();
const specialLabels = {question: 'Question for you', answer: 'Your answer', permission: 'Your permission', outreach: 'Your secretary reached out',
  expired: 'Question expired'};
const footnotes = {outreach: 'Sent on behalf of the GoodMorning team',
  expired: 'Questions can close after about an hour without an answer. Send a message to continue where you left off.'};
const actionTargets = {task: 'Task', event: 'Event', draft: 'Event draft', idea: 'Idea', record: 'Record', custom: 'Custom schedule'};
const actionLabels = {added: '{target} added', updated: '{target} updated', cancelled: '{target} cancelled',
  completed: '{target} completed', approved: '{target} approved', declined: '{target} declined'};

// Original rounded line icons: inherit the palette, never fetch external images.
function specialIcon(kind, action = {}) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': '1.7', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false'})) svg.setAttribute(key, value);
  const shapes = {
    question: ['M19 15a4 4 0 0 1-4 4H9l-5 2v-6a4 4 0 0 1-1-3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v5',
      'M9 8a3 3 0 0 1 6 0c0 2-3 2-3 4', 'M12 15h.01'],
    answer: ['M20 14a5 5 0 0 1-5 5H9l-5 2V9a5 5 0 0 1 5-5h7a4 4 0 0 1 4 4', 'm9 11 2 2 5-5'],
    permission: ['m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6l8-3Z', 'M12 8v4', 'M12 16h.01'],
    outreach: ['M20 11V7a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h7', 'm3 7 9 6 9-6',
      'M18 21s-3.5-2-3.5-4.2a1.8 1.8 0 0 1 3.5-.6 1.8 1.8 0 0 1 3.5.6C21.5 19 18 21 18 21Z'],
    expired: ['M11 19H9l-5 2v-6a4 4 0 0 1-1-3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v3',
      'M9 8a3 3 0 0 1 6 0c0 1-.6 1.6-1.3 2', 'M18 21a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M18 15.5V17l1 1']
  };
  const bases = {
    event: 'M4 7h16M8 3v4m8-4v4M11 21H6a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v4M7 11h2m-2 4h2',
    draft: 'M4 7h16M8 3v4m8-4v4M11 21H6a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v4M8 12h.01',
    idea: 'M9 18H8v-2c-3-2-4-7-1-10s7-3 10 0c2 2 2 4 1 6M9 21h2M8 3 7 2m13 2 1-1',
    task: 'M11 21H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v5M7 8l1 1 2-2m3 1h4M7 13h3',
    record: 'M11 21H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v5M7 8h10M7 13h3'
  };
  const marks = {added: 'M18 14v8m-4-4h8', updated: 'm14 19 6-6 2 2-6 6-3 1 1-3Z',
    cancelled: 'M14 18h8', completed: 'm14 18 3 3 5-6', approved: 'm14 18 3 3 5-6', declined: 'm15 15 6 6m0-6-6 6'};
  for (const d of shapes[kind] || [bases[action.target] || bases.record, marks[action.operation] || marks.updated]) {
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', d); svg.append(path);
  }
  return svg;
}

function specialBadge(kind, action = {}) {
  const badge = make('div', '', 'chat-special-label');
  const icon = make('span', '', 'chat-special-icon'); icon.append(specialIcon(kind, action));
  const label = make('span');
  if (kind === 'action') {
    badge.dataset.target = action.target;
    badge.dataset.operation = action.operation;
    const target = chatT(actionTargets[action.target] || 'Record');
    label.textContent = chatT(actionLabels[action.operation] || '{target} updated', {target});
  } else { label.dataset.uiText = specialLabels[kind]; label.textContent = chatT(specialLabels[kind]); }
  if (typeof goodmorningLanguage !== 'undefined') label.lang = goodmorningLanguage;
  badge.append(icon, label);
  return badge;
}

function enterMessage(node, animate) {
  if (!animate || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  node.classList.add('message-enter');
  node.addEventListener('animationend', event => {
    if (event.target === node) node.classList.remove('message-enter');
  });
}

function specialForm(info, category, reply, refreshed, language, replay, existing) {
  const key = category + ':' + info.id;
  const signature = JSON.stringify([info, language]);
  const previous = existing.get(key);
  if (previous?.dataset.signature === signature) return previous;
  const form = category === 'question' ? secretaryQuestion(info, reply, refreshed, language)
    : secretaryPermission(info, reply, refreshed, language);
  form.dataset.input = key; form.dataset.signature = signature; form.dataset.special = category;
  form.prepend(specialBadge(category));
  enterMessage(form, !replay && !previous);
  return form;
}
const chatHelp = document.querySelector('#chat-help');
const chatGuide = document.querySelector('#chat-guide');
chatHelp.addEventListener('click', () => {
  chatGuide.hidden = !chatGuide.hidden;
  chatHelp.setAttribute('aria-expanded', String(!chatGuide.hidden));
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || chatGuide.hidden) return;
  chatGuide.hidden = true;
  chatHelp.setAttribute('aria-expanded', 'false');
  chatHelp.focus({preventScroll: true});
});
// A starter only fills in the message box; nothing is sent until the user does.
document.querySelector('#chat-starters').addEventListener('click', event => {
  const button = event.target.closest('[data-starter]');
  if (!button || textBox.disabled) return;
  const label = button.querySelector('[data-ui-text]')?.dataset.uiText || button.textContent;
  textBox.value = chatT(label).replace(/…$/, typeof goodmorningLanguage !== 'undefined' && goodmorningLanguage === 'zh-CN' ? '' : ' ');
  resizeComposer(); focusComposer(true);
  textBox.setSelectionRange(textBox.value.length, textBox.value.length);
});
let themeTimer;

function updateChatTheme(now = new Date()) {
  const hour = Number(new Intl.DateTimeFormat('en-GB', {timeZone: chatConfig.timezone || 'UTC',
    hour: '2-digit', hourCycle: 'h23'}).format(now));
  document.documentElement.dataset.edition = hour >= 6 && hour < 18 ? 'gm' : 'gn';
}

function scheduleChatTheme() {
  clearTimeout(themeTimer);
  updateChatTheme();
  themeTimer = setTimeout(scheduleChatTheme, 60000 - Date.now() % 60000);
}

function applySecretaryName() {
  const heading = document.querySelector('#secretary-heading');
  if (heading) heading.textContent = secretaryName || chatT('Your secretary');
  document.querySelector('#conversation-name').textContent = secretaryName || chatT('Your secretary');
  // Force author labels to refresh on next message render.
  messageSignature = '';
}

async function chatAPI(path, body, binary = false) {
  if (body) pendingChatMutations++;
  try { return await chatRequest(path, body, binary); }
  finally {
    if (body) {
      pendingChatMutations--;
      document.dispatchEvent(new Event('activity:refresh'));
    }
  }
}

async function chatRequest(path, body, binary = false) {
  // Only the read-only history listing may retry. Queue reads and sends can dispatch work.
  const attempts = !body && path === '/api/chats' ? 2 : 1;
  for (let attempt = 0; attempt < attempts; attempt++) {
    let response;
    try {
      response = await fetch(path, { method: body ? 'POST' : 'GET',
        headers: body ? {'Content-Type':binary ? 'application/octet-stream' : 'application/json','X-Briefing-CSRF':chatConfig.csrf} : {},
        body: body ? (binary ? body : JSON.stringify(body)) : undefined, cache:'no-store', credentials:'same-origin' });
    } catch {
      if (attempt + 1 < attempts) continue;
      const error = new Error(chatT('The connection was interrupted. Refresh to check delivery before sending again.'));
      error.uncertain = Boolean(body);
      if (!body) readError = error.message;
      throw error;
    }
    if (response.status === 401) { location.replace('/login'); throw new Error(chatT('Please sign in again.')); }
    let result;
    try {
      result = await goodmorningJSON(response);
      if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Invalid response');
    } catch (cause) {
      if (attempt + 1 < attempts) continue;
      const error = new Error(response.status === 429 ? cause.message : chatT('The server returned an unreadable response. Your draft is safe.'));
      error.status = response.status;
      error.uncertain = Boolean(body) && (response.ok || response.status >= 500);
      if (error.uncertain) error.message += ' ' + chatT('Refresh to check delivery before sending again.');
      if (!body) readError = error.message;
      throw error;
    }
    if (!response.ok) {
      const error = new Error(result.error || chatT('The secretary is unavailable.'));
      error.status = response.status;
      error.uncertain = response.status >= 500; throw error;
    }
    if (!body && errorBox.textContent === readError) { errorBox.textContent = ''; readError = null; }
    return result;
  }
}

function composeState() {
  const initializing = !chat && mode === 'initialize';
  const changed = composer.classList.contains('is-initializing') !== initializing;
  composer.classList.toggle('is-initializing', initializing);
  const blocked = chat && ['waiting', 'uncertain', 'unavailable'].includes(state);
  sendButton.disabled = sending || restoringWorkspace || !chatConfig.connected || blocked;
  textBox.disabled = initializing || sending || blocked;
  fileInput.disabled = attachButton.disabled = initializing || sendButton.disabled;
  document.querySelectorAll('#chat-attachments .attachment-remove').forEach(button => { button.disabled = sendButton.disabled; });
  const sendLabel = chatT(chat ? 'Send reply' : modes[mode][1]);
  sendButton.querySelector('.chat-send-label').textContent = sendLabel;
  sendButton.setAttribute('aria-label', sendLabel);
  textBox.required = !initializing && !attachments.length && Boolean(chat);
  if (changed) resizeComposer();
  showActivity();
}

function fileSize(size) {
  return size < 1024 * 1024 ? `${Math.ceil(size / 1024)} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

const imageTypes = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp']);
const imageDialog = make('dialog', '', 'chat-image-dialog');
const imageClose = make('button', '×');
imageClose.type = 'button';
imageClose.setAttribute('aria-label', chatT('Close image'));
imageDialog.setAttribute('aria-label', chatT('Image preview'));
const enlargedImage = make('img');
imageDialog.append(imageClose, enlargedImage);
document.body.append(imageDialog);
imageClose.addEventListener('click', () => imageDialog.close());
imageDialog.addEventListener('click', event => { if (event.target === imageDialog) imageDialog.close(); });
imageDialog.addEventListener('close', () => enlargedImage.removeAttribute('src'));

function imagePreview(source, name) {
  const button = make('button', '', 'attachment-preview');
  button.type = 'button';
  button.setAttribute('aria-label', chatT('Enlarge {name}', {name}));
  const image = make('img');
  image.alt = name;
  image.src = source;
  button.append(image);
  button.addEventListener('click', () => {
    enlargedImage.alt = name;
    enlargedImage.src = source;
    imageDialog.showModal();
  });
  return button;
}

function releasePreviews(entries) {
  for (const entry of entries) if (entry.preview) URL.revokeObjectURL(entry.preview);
}

function showAttachments() {
  document.querySelector('#chat-attachments').replaceChildren(...attachments.map(entry => {
    const chip = make('div', '', 'attachment-chip');
    if (entry.preview) chip.append(imagePreview(entry.preview, entry.file.name));
    chip.append(make('span', `${entry.file.name} · ${fileSize(entry.file.size)}`));
    const remove = make('button', '×', 'attachment-remove');
    remove.type = 'button';
    remove.setAttribute('aria-label', chatT('Remove {name}', {name: entry.file.name}));
    remove.addEventListener('click', () => {
      releasePreviews([entry]);
      attachments = attachments.filter(item => item !== entry);
      showAttachments(); composeState();
    });
    chip.append(remove);
    return chip;
  }));
  composeState();
}

attachButton.addEventListener('click', () => fileInput.click());
function addFiles(files) {
  errorBox.textContent = '';
  for (const file of files) {
    if (file.size > chatConfig.maxUploadBytes) {
      errorBox.textContent = chatT('Files must be 50 MB or smaller.');
      continue;
    }
    if (attachments.length >= 100) {
      errorBox.textContent = chatT('Attach up to 100 files per message.');
      break;
    }
    attachments.push({file, id: crypto.randomUUID().replaceAll('-', ''), uploaded: false,
      preview: imageTypes.has(file.type) ? URL.createObjectURL(file) : null});
  }
  showAttachments();
}
fileInput.addEventListener('change', () => {
  addFiles(fileInput.files);
  fileInput.value = '';
});
textBox.addEventListener('paste', event => {
  const clipboard = event.clipboardData;
  const files = Array.from(clipboard?.items || []).filter(item => item.kind === 'file')
    .map(item => item.getAsFile()).filter(Boolean);
  if (!files.length) files.push(...Array.from(clipboard?.files || []));
  if (!files.length) return;
  event.preventDefault();
  if (attachButton.disabled) return;
  addFiles(files);
  const text = clipboard.getData('text/plain');
  if (text) {
    textBox.setRangeText(text, textBox.selectionStart, textBox.selectionEnd, 'end');
    textBox.dispatchEvent(new Event('input', {bubbles: true}));
  }
});

const draggingFiles = event => Array.from(event.dataTransfer?.types || []).includes('Files');
let dragDepth = 0;
composer.addEventListener('dragenter', event => {
  if (!draggingFiles(event) || attachButton.disabled) return;
  event.preventDefault(); dragDepth++;
  composer.classList.add('is-dragging');
});
composer.addEventListener('dragover', event => {
  if (!draggingFiles(event)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = attachButton.disabled ? 'none' : 'copy';
});
composer.addEventListener('dragleave', event => {
  if (!draggingFiles(event)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) composer.classList.remove('is-dragging');
});
composer.addEventListener('drop', event => {
  if (!draggingFiles(event)) return;
  event.preventDefault(); dragDepth = 0;
  composer.classList.remove('is-dragging');
  if (!attachButton.disabled) addFiles(event.dataTransfer.files);
});
// A dropped file must not navigate away from private, unsent conversation data.
for (const name of ['dragover', 'drop']) document.addEventListener(name, event => {
  if (draggingFiles(event)) {
    event.preventDefault();
    if (name === 'drop') { dragDepth = 0; composer.classList.remove('is-dragging'); }
  }
});

function composerReady() {
  return !textBox.disabled && !sendButton.disabled;
}

function focusComposer(force = false) {
  if (!composerReady() || document.hidden || imageDialog.open) return;
  if (document.activeElement === textBox) return;
  const active = document.activeElement;
  if (!force && active && active !== document.body && active !== document.documentElement) {
    if (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT'
      || active.tagName === 'BUTTON' || active.tagName === 'A' || active.tagName === 'SUMMARY' || active.isContentEditable) return;
    if (active.closest && active.closest('a, button, summary, details, form, [role="dialog"], [role="listbox"]')) return;
  }
  if (!force && typeof matchMedia === 'function' && !matchMedia('(pointer:fine)').matches) return;
  textBox.focus({preventScroll: true});
}

function showActivity() {
  const status = document.querySelector('#chat-status');
  const active = sending || ['starting', 'running'].includes(state);
  document.querySelector('#chat-empty').hidden = active || Boolean(chat)
    || document.querySelector('#chat-messages').childElementCount > 0;
  let label = status.querySelector('.chat-status-label');
  if (!label) {
    const dots = make('span', '', 'chat-activity-dots');
    dots.setAttribute('aria-hidden', 'true');
    dots.append(make('span'), make('span'), make('span'));
    label = make('span', '', 'chat-status-label');
    status.replaceChildren(dots, label);
  }
  const text = chatT(sending ? 'Sending your message' : state === 'starting'
    ? 'Opening your conversation' : state === 'running' ? 'Your secretary is working' : statusLabel);
  if (label.textContent !== text) label.textContent = text;
  status.hidden = !text;
  status.classList.toggle('is-working', active);
  chatScroll.classList.toggle('is-working', active);
  status.classList.toggle('is-queued', !sending && state === 'queued');
}

function queueText(position, depth) {
  const place = chatT('You are #{position} in line', {position});
  if (depth > 1) return `${chatT('In queue')} · ${place} · ${chatT('{depth} waiting', {depth})}`;
  return `${chatT('In queue')} · ${place}`;
}

function showQueued(position, depth) {
  statusLabel = queueText(position, depth);
  showActivity();
}

function clearQueued() {
  document.querySelector('#chat-status').classList.remove('is-queued');
}

function showMode() {
  showTopic();
  document.querySelector('#conversation-name').textContent = secretaryName || chatT('Your secretary');
  document.querySelector('#chat-welcome').textContent = chatT((modes[mode] || modes.secretary)[0]);
  document.querySelector('#chat-hint').textContent = chatT(mode === 'initialize'
    ? 'Review location, timezone and preferences a few answers at a time. Replies follow the website language.' : 'Save a to-do, jot down an idea, plan your week or change a preference, all in one place.');
  document.querySelector('#chat-starters').hidden = mode === 'initialize';
  document.querySelector('#request-language-note').textContent = requestLanguage && state !== 'idle' && typeof goodmorningLanguage !== 'undefined' && requestLanguage !== goodmorningLanguage
    ? chatT('This request is finishing in {language}. New requests use your current website language.',{language:chatT(requestLanguage==='zh-CN'?'Simplified Chinese':'English')}) : '';
  composeState();
}

function draftKey() {
  return chat ? 'id:' + chat : mode;
}

function newConversation({resume = null} = {}) {
  drafts.set(draftKey(), {text: textBox.value, attachments});
  clearTimeout(timer); revision++;
  clearTimeout(titleTimer); titleRetries = 0;
  chat = null; state = null; sending = false; mode = chatConfig.defaultMode; requestLanguage = null;
  rememberWorkspace(null, resume);
  history.replaceState(null, '', '/chat');
  markCurrentHistoryLink(null);
  formSignature = ''; messageSignature = ''; animateMessages = false;
  pendingMessages = []; shownMessages = [];
  followNextUpdate = true;
  document.querySelector('#chat-messages').replaceChildren();
  document.querySelector('#chat-questions').replaceChildren();
  document.querySelector('#chat-action-notice').hidden = true;
  document.querySelector('#chat-empty').hidden = false;
  chatScroll.scrollTop = 0;
  latestButton.hidden = true;
  statusLabel = '';
  document.querySelector('#chat-status').classList.remove('is-queued');
  errorBox.textContent = '';
  const draft = drafts.get(mode);
  textBox.value = draft?.text || '';
  resizeComposer();
  attachments = draft?.attachments || [];
  showAttachments();
  showMode();
  focusComposer(true);
}

function syncModes() {
  document.querySelectorAll('[data-guide]').forEach(item => { item.hidden = item.dataset.guide !== chatConfig.defaultMode; });
  // Preserve an existing setup conversation and its replies after setup completes.
  if (!chat) mode = chatConfig.defaultMode;
  showMode();
}
document.querySelector('#new-conversation').addEventListener('click', () => newConversation());

function markCurrentHistoryLink(id) {
  document.querySelectorAll('#chat-history a').forEach(link => {
    const selected = new URL(link.href).searchParams.get('id') === id;
    if (selected) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
    const badge = link.querySelector('.history-current');
    if (badge) badge.hidden = !selected;
  });
}

function openConversation(id, {push = true} = {}) {
  if (!id || id === chat) {
    markCurrentHistoryLink(chat);
    return;
  }
  drafts.set(draftKey(), {text: textBox.value, attachments});
  clearTimeout(timer); revision++;
  clearTimeout(titleTimer); titleRetries = 0;
  chat = id; state = 'starting'; sending = false; requestLanguage = null;
  rememberWorkspace(null, null);
  showTopic();
  if (push) history.pushState(null, '', '/chat?id=' + id);
  else history.replaceState(null, '', '/chat?id=' + id);
  markCurrentHistoryLink(id);
  formSignature = ''; messageSignature = ''; animateMessages = false;
  pendingMessages = []; shownMessages = [];
  followNextUpdate = true;
  document.querySelector('#chat-messages').replaceChildren();
  document.querySelector('#chat-questions').replaceChildren();
  document.querySelector('#chat-action-notice').hidden = true;
  document.querySelector('#chat-empty').hidden = false;
  chatScroll.scrollTop = 0;
  latestButton.hidden = true;
  statusLabel = '';
  document.querySelector('#chat-status').classList.remove('is-queued');
  errorBox.textContent = '';
  const draft = drafts.get('id:' + id);
  textBox.value = draft?.text || '';
  resizeComposer();
  attachments = draft?.attachments || [];
  showAttachments();
  showActivity();
  composeState();
  pollChat();
}

function historyClick(event) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest('a[href]');
  if (!link) return;
  let url;
  try { url = new URL(link.href, location.origin); }
  catch { return; }
  if (url.origin !== location.origin || url.pathname !== '/chat') return;
  const id = url.searchParams.get('id');
  if (!id) return;
  event.preventDefault();
  openConversation(id);
}
document.querySelector('#chat-history').addEventListener('click', historyClick);
document.querySelector('#chat-resume').addEventListener('click', historyClick);

window.addEventListener('popstate', () => {
  const id = new URLSearchParams(location.search).get('id');
  if (!id) {
    if (chat !== null) newConversation();
    return;
  }
  if (id !== chat) openConversation(id, {push: false});
});

textBox.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  if (sendButton.disabled) return;
  const form = document.querySelector('#chat-compose');
  if (typeof form.requestSubmit === 'function') form.requestSubmit();
  else sendButton.click();
});

document.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey
    || event.isComposing || event.keyCode === 229) return;
  if (document.activeElement === textBox || !composerReady()) return;
  const target = event.target;
  if (target instanceof HTMLElement) {
    if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A', 'SUMMARY'].includes(target.tagName) || target.isContentEditable) return;
    if (target.closest && target.closest('a, button, summary, details, form, [role="dialog"], [role="listbox"]')) return;
  }
  event.preventDefault();
  focusComposer(true);
});

async function historyList() {
  try {
    await fetchHistoryList();
    const notice = document.querySelector('#history-notice');
    notice.hidden = document.querySelector('#chat-history').children.length > 0;
    notice.textContent = chatT('Your conversations will appear here.');
    document.querySelector('#history-retry').hidden = true;
  } catch (error) {
    const notice = document.querySelector('#history-notice');
    notice.hidden = false; notice.textContent = chatT('Conversation history is temporarily unavailable. Your current chat is preserved.');
    document.querySelector('#history-retry').hidden = false;
    throw error;
  }
}
document.querySelector('#history-retry').addEventListener('click', () => historyList().catch(() => {}));

async function fetchHistoryList() {
  clearTimeout(titleTimer);
  const result = await chatAPI('/api/chats');
  chatConfig.defaultMode = result.defaultMode;
  chatConfig.connected = result.connected;
  syncModes();
  if (typeof result.timezone === 'string' && result.timezone !== chatConfig.timezone) {
    chatConfig.timezone = result.timezone;
    scheduleChatTheme();
  }
  if (typeof result.secretary_name === 'string' && result.secretary_name && result.secretary_name !== secretaryName) {
    secretaryName = result.secretary_name;
    applySecretaryName();
  }
  if (typeof result.avatar === 'string') document.dispatchEvent(new CustomEvent('secretary:avatar', {detail: result.avatar}));
  const historyNav = document.querySelector('#chat-history');
  const historyDetails = document.querySelector('#conversation-history');
  const historyTop = historyNav.scrollTop;
  const detailsTop = historyDetails ? historyDetails.scrollTop : 0;
  const pageTop = window.scrollY;
  historyNav.replaceChildren(...result.chats.map(item => {
    conversationTitles.set(item.id, item.title);
    const link = make('a'); link.href = '/chat?id=' + item.id;
    link.append(make('span', item.title, 'history-title'));
    const meta = make('span', '', 'history-meta');
    const current = make('small', chatT('Current'), 'history-current'); current.dataset.uiText = 'Current'; current.hidden = item.id !== chat;
    if (item.unread && item.id !== chat) {
      const fresh = make('small', chatT('New'), 'history-new'); fresh.dataset.uiText = 'New';
      meta.append(fresh); link.classList.add('is-unread');
    }
    if (typeof item.created === 'number') {
      const started = new Date(item.created * 1000);
      const when = make('small', new Intl.DateTimeFormat(document.documentElement.lang || 'en', {timeZone: chatConfig.timezone || undefined,
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false}).format(started), 'history-time');
      when.title = started.toISOString();
      meta.append(when);
    }
    meta.append(current); link.append(meta);
    if (item.id === chat) link.setAttribute('aria-current', 'page');
    return link;
  }));
  showTopic();
  if (historyNav.scrollTop !== historyTop) historyNav.scrollTop = historyTop;
  if (historyDetails && historyDetails.scrollTop !== detailsTop) historyDetails.scrollTop = detailsTop;
  if (window.scrollY !== pageTop) window.scrollTo({left: window.scrollX, top: pageTop, behavior: 'instant'});
  if (result.chats.some(item => item.title_pending) && titleRetries++ < 20) {
    titleTimer = setTimeout(() => { if (!document.hidden) historyList().catch(() => {}); }, 3000);
  }
}

function nearLatest() {
  return chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 80;
}

function updateScrollTools() {
  latestButton.hidden = nearLatest();
}

function scrollToLatest(smooth = false) {
  chatScroll.scrollTo({top: chatScroll.scrollHeight,
    behavior: smooth && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'instant'});
  updateScrollTools();
}

chatScroll.addEventListener('scroll', updateScrollTools, {passive: true});
latestButton.addEventListener('click', () => scrollToLatest(true));
window.addEventListener('resize', updateScrollTools);

function showMessages(messages) {
  shownMessages = messages;
  const delivered = new Set(messages.map(item => item.turn).filter(Boolean));
  pendingMessages = pendingMessages.filter(item => !delivered.has(item.turn));
  const visible = [...messages, ...pendingMessages.map(item => ({...item, id: 'pending:' + item.turn, role: 'user', pending: true}))];
  const signature = JSON.stringify([visible, secretaryName]);
  if (signature === messageSignature) return false;
  const log = document.querySelector('#chat-messages');
  const existing = new Map([...log.children].map(node => [node.dataset.message, node]));
  const nodes = visible.map(item => {
    // A delivered message takes over its pending bubble instead of entering again.
    let bubble = existing.get(item.id) || (item.turn && existing.get('pending:' + item.turn));
    if (!bubble) {
      bubble = make('section', '', 'chat-message ' + item.role + (item.kind ? ' ' + item.kind : ''));
      bubble.dataset.message = item.id;
      const special = item.kind === 'action' || Object.hasOwn(specialLabels, item.kind) ? item.kind : null;
      if (special) {
        bubble.dataset.special = special;
        if (special === 'action') bubble.dataset.operation = item.action?.operation || 'updated';
        bubble.append(specialBadge(special, item.action));
      }
      if (item.language) bubble.lang = item.language;
      const authorName = item.role === 'user' ? chatT('You') : (secretaryName || chatT('Your secretary'));
      const author=make('p',authorName,'message-author');
      author.dataset.uiText=item.role==='user'?'You':'Your secretary';
      if (item.role !== 'user' && secretaryName) author.dataset.secretaryName = secretaryName;
      bubble.append(author, make('div', '', 'message-text'), make('div', '', 'message-attachments'));
      if (footnotes[item.kind]) {
        const note = make('p', chatT(footnotes[item.kind]), 'message-footnote');
        note.dataset.uiText = footnotes[item.kind];
        bubble.append(note);
      }
      if (item.role === 'assistant' && item.kind !== 'action') {
        const portrait = make('span', '', 'chat-portrait reply-portrait');
        portrait.setAttribute('aria-hidden', 'true');
        const image = make('img'); image.alt = '';
        portrait.append(image); bubble.append(portrait);
      }
      enterMessage(bubble, animateMessages);
      log.append(bubble);
    } else if (item.role !== 'user') {
      const author = bubble.querySelector('.message-author');
      const expected = secretaryName || chatT('Your secretary');
      if (author && author.textContent !== expected) author.textContent = expected;
    }
    bubble.dataset.message = item.id;
    bubble.classList.toggle('pending', Boolean(item.pending));
    const content = bubble.querySelector('.message-text');
    if (renderedMessages.get(content) !== item.text) {
      const markdown = item.role === 'assistant' && (!item.kind || item.kind === 'outreach');
      content.classList.toggle('message-markdown', markdown);
      if (markdown) {
        try { content.replaceChildren(secretaryMarkdown(item.text)); }
        catch { content.classList.remove('message-markdown'); content.textContent = item.text; }
      } else content.textContent = item.text;
      renderedMessages.set(content, item.text);
    }
    const attachmentBox = bubble.querySelector('.message-attachments');
    const attachmentSignature = JSON.stringify(item.attachments || []);
    if (attachmentBox.dataset.signature !== attachmentSignature) {
      attachmentBox.replaceChildren(...(item.attachments || []).map(entry => {
        const file = make('div', '', 'message-attachment');
        if (entry.removed) {
          file.append(make('p', chatT('{name} · removed after 30 days', {name: entry.name}), 'attachment-name'));
        } else if (entry.preview) {
          // The local preview is released after sending, so it is not enlargeable.
          const image = make('img'); image.alt = entry.name; image.src = entry.preview;
          file.append(image);
        } else if (imageTypes.has(entry.mime) && /^[a-f0-9]{32}$/.test(entry.id)) {
          file.append(imagePreview(`/api/chat-uploads/${entry.id}/image`, entry.name));
        } else {
          file.append(make('p', `${entry.name} · ${fileSize(entry.size)}`, 'attachment-name'));
        }
        return file;
      }));
      attachmentBox.dataset.signature = attachmentSignature;
    }
    return bubble;
  });
  [...log.children].filter(node => !nodes.includes(node)).forEach(node => node.remove());
  nodes.forEach((node, index) => { if (log.children[index] !== node) log.insertBefore(node, log.children[index] || null); });
  document.querySelector('#chat-empty').hidden = visible.length > 0;
  messageSignature = signature;
  animateMessages = true;
  syncChatAvatar();
  return true;
}

// Round portraits use the profile picture, or a crop of the scene when a custom avatar has none.
function syncChatAvatar() {
  const figure = document.querySelector('.avatar-display');
  const source = figure.dataset.profile || figure.querySelector('.avatar-image').getAttribute('src');
  document.querySelectorAll('.chat-portrait').forEach(portrait => {
    if (portrait.querySelector('img').getAttribute('src') !== source) portrait.querySelector('img').src = source;
  });
}
new MutationObserver(syncChatAvatar).observe(document.querySelector('.avatar-display .avatar-image'), {attributes: true, attributeFilter: ['src']});
new MutationObserver(syncChatAvatar).observe(document.querySelector('.avatar-display'), {attributes: true, attributeFilter: ['data-profile']});
syncChatAvatar();

async function pollQueue() {
  clearTimeout(timer);
  if (!chat || document.hidden || polling) return;
  polling = true;
  const current = chat; const version = revision;
  try {
    const status = await chatAPI('/api/queue');
    if (version !== revision) return;
    const mine = (status.queue || []).find(item => ['chat', 'reply'].includes(item.work) && item.chat === current);
    if (mine) {
      state = 'queued';
      showQueued(mine.position, status.depth);
      showMode();
    } else {
      state = 'starting'; clearQueued(); showActivity();
      timer = setTimeout(pollChat, 0);
      return;
    }
  } catch (error) {
    if (version !== revision) return;
    if (error.status === 401) throw error;
    errorBox.textContent = error.message;
  } finally {
    polling = false;
    if (version !== revision && chat) timer = setTimeout(pollQueue, 0);
  }
  if (version === revision && chat && state === 'queued') timer = setTimeout(pollQueue, 2500);
}

async function recoverQueuedAfterReload() {
  try {
    const status = await chatAPI('/api/queue');
    const mine = (status.queue || []).find(item => ['chat', 'reply'].includes(item.work) && item.chat === chat);
    if (mine) {
      state = 'queued';
      errorBox.textContent = '';
      showQueued(mine.position, status.depth);
      showMode();
      pollQueue();
      return true;
    }
  } catch { /* Fall through to the unavailable notice below. */ }
  return false;
}

async function pollChat() {
  clearTimeout(timer);
  if (!chat || document.hidden || polling) return;
  polling = true;
  const current = chat; const version = revision;
  try {
    const result = await chatAPI('/api/chats/' + current);
    if (version !== revision) return;
    const follow = followNextUpdate || nearLatest();
    const replay = !animateMessages;
    mode = result.mode; state = result.state;
    requestLanguage = result.language;
    if (typeof result.secretary_name === 'string' && result.secretary_name && result.secretary_name !== secretaryName) {
      secretaryName = result.secretary_name;
      applySecretaryName();
    }
    statusLabel = result.label;
    document.querySelector('#chat-status').classList.remove('is-queued');
    const messagesChanged = result.messages ? showMessages(result.messages) : false;
    // Reading a secretary-opened conversation clears its "New" badge everywhere.
    if (result.unread) chatAPI(`/api/chats/${current}/seen`, {}).then(() => historyList()).catch(() => {});
    const notice = document.querySelector('#chat-action-notice');
    notice.hidden = !result.action_history_unavailable;
    notice.textContent = chatT(notice.dataset.uiText);
    if (result.reservation_required === false) {
      const waiting = await chatAPI('/api/queue');
      if (version !== revision) return;
      const mine = (waiting.queue || []).find(item => item.work === 'reply' && item.chat === current);
      if (mine) {
        state = 'queued'; formSignature = '';
        document.querySelector('#chat-questions').replaceChildren();
        showQueued(mine.position, waiting.depth); showMode();
        timer = setTimeout(pollQueue, 2500);
        return;
      }
      statusLabel += ' ' + chatT('Take your time. Other requests can continue while you decide.');
    }
    const signature = JSON.stringify([result.forms, result.permissions]);
    const formsChanged = signature !== formSignature;
    if (formsChanged) {
      const refreshed = () => { formSignature = ''; if (state === 'queued') pollQueue(); else pollChat(); };
      const reply = async (category, id, body) => {
        const receipt = await chatAPI(`/api/chats/${current}/${category}/${id}/reply`, body);
        if (version === revision) {
          followNextUpdate = true;
          if (receipt.queued) { state = 'queued'; showQueued(receipt.position, receipt.depth); showMode(); }
        }
        return receipt;
      };
      const questions = document.querySelector('#chat-questions');
      const existing = new Map([...questions.children].map(node => [node.dataset.input, node]));
      questions.replaceChildren(
        ...result.forms.map(info => specialForm(info, 'question', reply, refreshed, result.language, replay, existing)),
        ...result.permissions.map(info => specialForm(info, 'permission', reply, refreshed, result.language, replay, existing)));
      formSignature = signature;
    }
    showMode();
    if (follow && (messagesChanged || formsChanged)) {
      const question = document.querySelector('#chat-questions .agent-form');
      if (formsChanged && question && question.offsetHeight > chatScroll.clientHeight) {
        chatScroll.scrollTo({top: chatScroll.scrollTop + question.getBoundingClientRect().top
          - chatScroll.getBoundingClientRect().top - 12, behavior: 'instant'});
      } else scrollToLatest(!replay);
      followNextUpdate = false;
    }
    updateScrollTools();
    if (state === 'idle' || state === 'waiting') await historyList();
    if (state === 'idle') focusComposer();
  } catch (error) {
    if (version === revision && error.status === 404) {
      if (await recoverQueuedAfterReload()) return;
      newConversation();
      errorBox.textContent = chatT('This conversation is no longer available. Start a new one.');
      historyList().catch(() => {});
      return;
    }
    if (version === revision) { state = 'unavailable'; errorBox.textContent = error.message; composeState(); }
  } finally {
    polling = false;
    if (version !== revision && chat) timer = setTimeout(pollChat, 0);
  }
  if (version === revision && chat && !['idle','uncertain'].includes(state)) timer = setTimeout(pollChat, 2500);
}

document.querySelector('#chat-compose').addEventListener('submit', async event => {
  event.preventDefault();
  if (sendButton.disabled) return;
  const first = !chat;
  const text = first && mode === 'initialize'
    ? chatT('Start the initialization process with me.') : textBox.value;
  const request = crypto.randomUUID().replaceAll('-', '');
  const current = chat || request;
  const version = revision;
  const selectedFiles = attachments;
  let dispatching = false;
  sending = true; animateMessages = true; errorBox.textContent = ''; composeState();
  const pending = {turn: request, text, attachments: selectedFiles.map(entry => ({id: entry.id,
    name: entry.file.name, size: entry.file.size, preview: entry.preview}))};
  pendingMessages.push(pending);
  showMessages(shownMessages); scrollToLatest(true);
  try {
    for (const entry of selectedFiles) {
      if (!entry.uploaded) {
        await chatAPI(`/api/chat-uploads/${entry.id}?name=${encodeURIComponent(entry.file.name)}`, entry.file, true);
        entry.uploaded = true;
      }
      if (version !== revision) return;
    }
    const body = first ? {id: current, mode, text} : {id: request, text};
    if (selectedFiles.length) body.attachments = selectedFiles.map(entry => entry.id);
    dispatching = true;
    const result = await chatAPI(first ? '/api/chats' : `/api/chats/${current}/messages`,
      body);
    if (version !== revision) return;
    chat = current; textBox.value = ''; drafts.delete(mode); drafts.delete('id:' + current);
    releasePreviews(selectedFiles);
    resizeComposer();
    followNextUpdate = true;
    attachments = []; showAttachments();
    rememberWorkspace(null, null);
    history.replaceState(null, '', '/chat?id=' + chat);
    if (result && result.queued) {
      state = 'queued';
      showQueued(result.position, result.depth);
    } else {
      state = 'starting'; clearQueued();
    }
    await historyList();
  } catch (error) {
    if (version !== revision) return;
    // The draft stays in the composer; the transcript shows it if it did arrive.
    pendingMessages = pendingMessages.filter(item => item !== pending);
    showMessages(shownMessages);
    errorBox.textContent = error.status === 429 ? chatT(error.message) : error.message;
    if (dispatching && error.uncertain) {
      chat = current; state = 'uncertain';
      history.replaceState(null, '', '/chat?id=' + chat);
    }
  } finally {
    if (version === revision) {
      sending = false; composeState();
      if (chat) (state === 'queued' ? pollQueue() : pollChat());
    }
  }
});

function pollVisible() {
  if (!chat || restoringWorkspace) return;
  (state === 'queued' ? pollQueue() : pollChat());
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { leaveSecretary(); clearTimeout(timer); clearTimeout(themeTimer); }
  else returnToSecretary();
});
async function returnToSecretary() {
  if (document.hidden || restoringWorkspace) return;
  scheduleChatTheme();
  await restoreWorkspace();
  pollVisible(); focusComposer();
}
document.addEventListener('website:language', () => {
  document.querySelectorAll('.chat-special-label[data-target]').forEach(badge => {
    const target = chatT(actionTargets[badge.dataset.target] || 'Record');
    badge.lastElementChild.textContent = chatT(actionLabels[badge.dataset.operation] || '{target} updated', {target});
    if (typeof goodmorningLanguage !== 'undefined') badge.lastElementChild.lang = goodmorningLanguage;
  });
  document.querySelectorAll('.chat-special-label [data-ui-text]').forEach(label => {
    label.textContent = chatT(label.dataset.uiText);
    if (typeof goodmorningLanguage !== 'undefined') label.lang = goodmorningLanguage;
  });
  imageClose.setAttribute('aria-label', chatT('Close image'));
  imageDialog.setAttribute('aria-label', chatT('Image preview'));
  document.querySelectorAll('.attachment-preview').forEach(button => {
    button.setAttribute('aria-label', chatT('Enlarge {name}', {name: button.querySelector('img').alt}));
  });
  showMode(); showAttachments(); pollVisible(); historyList().catch(() => {});
});
document.addEventListener('website:before-refresh', event => { if (sending || pendingChatMutations) event.preventDefault(); });
document.addEventListener('website:refresh-drafts', event => {
  if (attachments.length || [...drafts.values()].some(draft => draft.text.trim() || draft.attachments.length)) event.preventDefault();
});
window.addEventListener('focus', returnToSecretary);
scheduleChatTheme();
resizeComposer();
if (chatViewport) resizeChatViewport();
showMode();
focusComposer();
async function startWorkspace() {
  await restoreWorkspace(true);
  historyList().catch(() => {});
  if (chat) pollVisible();
}
startWorkspace();
