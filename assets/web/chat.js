// Conversation IDs live in the URL. Private text never enters browser storage.
const chatConfig = JSON.parse(document.querySelector('#chat-config').dataset.config);
const chatT = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
const modes = {
  initialize: ['Let’s make this yours.', 'Start initialization'],
  secretary: ['A little room to plan.', 'Start conversation'],
  todo: ['Make space for what matters.', 'Save to-do'],
  eureka: ['Keep that spark.', 'Save idea']
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
const chatViewport = window.visualViewport;
let viewportFrame;
let viewportSignature;

function resizeChatViewport() {
  cancelAnimationFrame(viewportFrame);
  viewportFrame = requestAnimationFrame(() => {
    const mobile = matchMedia('(max-width: 700px)').matches;
    const signature = [mobile, innerHeight, chatViewport.width, chatViewport.height,
      chatViewport.offsetTop, chatViewport.scale].join(':');
    // Page scrolling must not resize the panel or pull readers back to the input.
    if (signature === viewportSignature) return;
    viewportSignature = signature;
    if (!mobile || chatViewport.scale !== 1) {
      chatLayout.style.removeProperty('--chat-viewport-height');
      chatLayout.style.removeProperty('--chat-keyboard-inset');
      resizeComposer(undefined, false);
      updateScrollTools();
      return;
    }
    const follow = nearLatest();
    const followDraft = textBox.scrollHeight - textBox.scrollTop - textBox.clientHeight < 1;
    const previousTop = chatScroll.scrollTop;
    const previousHeight = conversationPanel.offsetHeight;
    chatLayout.style.setProperty('--chat-viewport-height', `${chatViewport.height}px`);
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

if (chatViewport) {
  chatViewport.addEventListener('resize', resizeChatViewport);
  chatViewport.addEventListener('scroll', resizeChatViewport);
  window.addEventListener('resize', resizeChatViewport);
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
window.addEventListener('resize', resizeComposer);
document.addEventListener('scrollrails:layout', resizeComposer);
let attachments = [];
const make = secretaryElement;
const requestedMode = new URLSearchParams(location.search).get('mode');
let mode = Object.hasOwn(modes, requestedMode) ? requestedMode : chatConfig.defaultMode;
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
let followNextUpdate = true;
let statusLabel = '';
let readError = null;
let revision = 0;
let requestLanguage = null;
let secretaryName = typeof chatConfig.secretary_name === 'string' && chatConfig.secretary_name ? chatConfig.secretary_name : null;
const drafts = new Map();
const renderedMessages = new WeakMap();
const historyPanel = document.querySelector('#conversation-history');
const historyPreference = 'goodmorning.chat.history';
try { historyPanel.open = localStorage.getItem(historyPreference) !== 'closed'; } catch { /* Storage may be disabled. */ }
let historyOpen = historyPanel.open;
historyPanel.addEventListener('toggle', () => {
  if (historyPanel.open === historyOpen) return;
  historyOpen = historyPanel.open;
  try { localStorage.setItem(historyPreference, historyOpen ? 'open' : 'closed'); } catch { /* Keep the in-page choice. */ }
});
const modeHelp = document.querySelector('#mode-help');
const modeGuide = document.querySelector('#mode-guide');
modeHelp.addEventListener('click', () => {
  modeGuide.hidden = !modeGuide.hidden;
  modeHelp.setAttribute('aria-expanded', String(!modeGuide.hidden));
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || modeGuide.hidden) return;
  modeGuide.hidden = true;
  modeHelp.setAttribute('aria-expanded', 'false');
  modeHelp.focus({preventScroll: true});
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
      result = await response.json();
      if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Invalid response');
    } catch {
      if (attempt + 1 < attempts) continue;
      const error = new Error(chatT('The server returned an unreadable response. Your draft is safe.'));
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
  sendButton.disabled = sending || !chatConfig.connected || blocked;
  textBox.disabled = initializing || sending || blocked;
  fileInput.disabled = attachButton.disabled = initializing || sendButton.disabled;
  document.querySelectorAll('#chat-attachments .attachment-remove').forEach(button => { button.disabled = sendButton.disabled; });
  const sendLabel = chatT(chat ? 'Send reply' : modes[mode][1]);
  sendButton.querySelector('.chat-send-label').textContent = sendLabel;
  sendButton.setAttribute('aria-label', sendLabel);
  textBox.required = !initializing && !attachments.length && (!chat && ['todo','eureka'].includes(mode) || Boolean(chat));
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
  document.querySelector('#conversation-name').textContent = secretaryName || chatT('Your secretary');
  document.querySelectorAll('[data-mode]').forEach(button => {
    const selected = button.dataset.mode === mode;
    button.setAttribute('aria-checked', String(selected)); button.tabIndex = selected ? 0 : -1;
  });
  document.querySelector('#chat-welcome').textContent = chatT(modes[mode][0]);
  document.querySelector('#chat-hint').textContent = chatT(mode === 'initialize'
    ? 'Review location, timezone and preferences a few answers at a time. Replies follow the website language.' : 'Write in your own words. Your secretary will take it from here.');
  document.querySelector('#request-language-note').textContent = requestLanguage && state !== 'idle' && typeof goodmorningLanguage !== 'undefined' && requestLanguage !== goodmorningLanguage
    ? chatT('This request is finishing in {language}. New requests use your current website language.',{language:chatT(requestLanguage==='zh-CN'?'Simplified Chinese':'English')}) : '';
  composeState();
}

function draftKey() {
  return chat ? 'id:' + chat : mode;
}

function newConversation(next = chatConfig.defaultMode) {
  drafts.set(draftKey(), {text: textBox.value, attachments});
  clearTimeout(timer); revision++;
  clearTimeout(titleTimer); titleRetries = 0;
  chat = null; state = null; sending = false; mode = next; requestLanguage = null;
  history.replaceState(null, '', '/chat');
  document.querySelectorAll('#chat-history [aria-current]').forEach(link => link.removeAttribute('aria-current'));
  formSignature = ''; messageSignature = ''; animateMessages = false;
  followNextUpdate = true;
  document.querySelector('#chat-messages').replaceChildren();
  document.querySelector('#chat-questions').replaceChildren();
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

document.querySelectorAll('[data-mode]').forEach(button => {
  button.addEventListener('click', () => { if (button.dataset.mode !== mode) newConversation(button.dataset.mode); });
  button.addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const buttons = [...document.querySelectorAll('[data-mode]')];
    const index = buttons.indexOf(button);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next].click(); buttons[next].focus();
  });
});
document.querySelector('#new-conversation').addEventListener('click', () => newConversation());

function markCurrentHistoryLink(id) {
  document.querySelectorAll('#chat-history [aria-current]').forEach(link => link.removeAttribute('aria-current'));
  if (!id) return;
  const current = document.querySelector(`#chat-history a[href="/chat?id=${id}"]`);
  if (current) current.setAttribute('aria-current', 'page');
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
  if (push) history.pushState(null, '', '/chat?id=' + id);
  else history.replaceState(null, '', '/chat?id=' + id);
  markCurrentHistoryLink(id);
  formSignature = ''; messageSignature = ''; animateMessages = false;
  followNextUpdate = true;
  document.querySelector('#chat-messages').replaceChildren();
  document.querySelector('#chat-questions').replaceChildren();
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

document.querySelector('#chat-history').addEventListener('click', event => {
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
});

window.addEventListener('popstate', () => {
  const id = new URLSearchParams(location.search).get('id');
  if (!id) {
    if (chat !== null) newConversation(chatConfig.defaultMode);
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
  clearTimeout(titleTimer);
  const result = await chatAPI('/api/chats');
  chatConfig.defaultMode = result.defaultMode;
  chatConfig.connected = result.connected;
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
    const link = make('a', item.title); link.href = '/chat?id=' + item.id;
    const label=item.mode === 'todo' ? 'To-do' : item.mode[0].toUpperCase() + item.mode.slice(1);
    const badge=make('small',chatT(label));badge.dataset.uiText=label;link.append(badge);
    if (item.id === chat) link.setAttribute('aria-current', 'page');
    return link;
  }));
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
  const signature = JSON.stringify([messages, secretaryName]);
  if (signature === messageSignature) return false;
  const log = document.querySelector('#chat-messages');
  const existing = new Map([...log.children].map(node => [node.dataset.message, node]));
  const nodes = messages.map(item => {
    let bubble = existing.get(item.id);
    if (!bubble) {
      bubble = make('section', '', 'chat-message ' + item.role + (item.kind ? ' ' + item.kind : ''));
      bubble.dataset.message = item.id;
      if (item.language) bubble.lang = item.language;
      const authorName = item.role === 'user' ? chatT('You') : (secretaryName || chatT('Your secretary'));
      const author=make('p',authorName,'message-author');
      author.dataset.uiText=item.role==='user'?'You':'Your secretary';
      if (item.role !== 'user' && secretaryName) author.dataset.secretaryName = secretaryName;
      bubble.append(author, make('div', '', 'message-text'), make('div', '', 'message-attachments'));
      if (item.role === 'assistant') {
        const portrait = make('span', '', 'chat-portrait reply-portrait');
        portrait.setAttribute('aria-hidden', 'true');
        const image = make('img'); image.alt = '';
        portrait.append(image); bubble.append(portrait);
      }
      if (animateMessages && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        bubble.classList.add('message-enter');
        bubble.addEventListener('animationend', () => bubble.classList.remove('message-enter'), {once: true});
      }
      log.append(bubble);
    } else if (item.role !== 'user') {
      const author = bubble.querySelector('.message-author');
      const expected = secretaryName || chatT('Your secretary');
      if (author && author.textContent !== expected) author.textContent = expected;
    }
    const content = bubble.querySelector('.message-text');
    if (renderedMessages.get(content) !== item.text) {
      const markdown = item.role === 'assistant' && !item.kind;
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
        if (imageTypes.has(entry.mime) && /^[a-f0-9]{32}$/.test(entry.id)) {
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
  document.querySelector('#chat-empty').hidden = messages.length > 0;
  messageSignature = signature;
  animateMessages = true;
  syncChatAvatar();
  return true;
}

function syncChatAvatar() {
  const figure = document.querySelector('.avatar-display');
  const source = figure.querySelector('.avatar-image').getAttribute('src');
  const custom = source.startsWith('/api/avatar/image/');
  document.querySelectorAll('.chat-portrait').forEach(portrait => {
    portrait.dataset.chatAvatar = custom ? 'custom' : figure.dataset.avatar;
    if (portrait.querySelector('img').getAttribute('src') !== source) portrait.querySelector('img').src = source;
  });
}
new MutationObserver(syncChatAvatar).observe(document.querySelector('.avatar-display .avatar-image'), {attributes: true, attributeFilter: ['src']});
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
      document.querySelector('#chat-questions').replaceChildren(
        ...result.forms.map(info => secretaryQuestion(info, reply, refreshed, result.language)),
        ...result.permissions.map(info => secretaryPermission(info, reply, refreshed, result.language)));
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
  if (!chat) return;
  (state === 'queued' ? pollQueue() : pollChat());
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { clearTimeout(timer); clearTimeout(themeTimer); }
  else { scheduleChatTheme(); pollVisible(); focusComposer(); }
});
document.addEventListener('website:language', () => {
  imageClose.setAttribute('aria-label', chatT('Close image'));
  imageDialog.setAttribute('aria-label', chatT('Image preview'));
  document.querySelectorAll('.attachment-preview').forEach(button => {
    button.setAttribute('aria-label', chatT('Enlarge {name}', {name: button.querySelector('img').alt}));
  });
  showMode(); showAttachments(); pollVisible();
});
document.addEventListener('website:before-refresh', event => { if (sending || pendingChatMutations) event.preventDefault(); });
document.addEventListener('website:refresh-drafts', event => {
  if (attachments.length || [...drafts.values()].some(draft => draft.text.trim() || draft.attachments.length)) event.preventDefault();
});
window.addEventListener('focus', () => { scheduleChatTheme(); pollVisible(); focusComposer(); });
scheduleChatTheme();
resizeComposer();
if (chatViewport) resizeChatViewport();
showMode();
focusComposer();
historyList().catch(error => { errorBox.textContent = error.message; });
if (chat) pollChat();
