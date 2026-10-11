// Conversation IDs live in the URL. Private text never enters browser storage.
const chatConfig = JSON.parse(document.querySelector('#chat-config').dataset.config);
const modes = {
  initialize: ['Let’s make this yours.', 'Set up your secretary, or review every existing preference. Your saved work stays safe.', 'Start initialization'],
  secretary: ['A little room to plan.', 'Ask about your schedule, preferences, or secretary records.', 'Start conversation'],
  todo: ['Make space for what matters.', 'Write a task to capture. Saving it does not start the work.', 'Save to-do'],
  eureka: ['Keep that spark.', 'Capture an idea before it slips away. No automatic research or execution.', 'Save idea']
};
const textBox = document.querySelector('#chat-text');
const sendButton = document.querySelector('#chat-send');
const errorBox = document.querySelector('#chat-error');
const make = secretaryElement;
const requestedMode = new URLSearchParams(location.search).get('mode');
let mode = Object.hasOwn(modes, requestedMode) ? requestedMode : chatConfig.defaultMode;
let chat = new URLSearchParams(location.search).get('id');
let state = null;
let sending = false;
let polling = false;
let timer;
let formSignature = '';
let messageSignature = '';
let revision = 0;
const drafts = new Map();

async function chatAPI(path, body) {
  let response;
  try {
    response = await fetch(path, { method: body ? 'POST' : 'GET',
      headers: body ? {'Content-Type':'application/json','X-Briefing-CSRF':chatConfig.csrf} : {},
      body: body ? JSON.stringify(body) : undefined, cache:'no-store', credentials:'same-origin' });
  } catch {
    const error = new Error('The connection was interrupted. Refresh to check delivery before sending again.');
    error.uncertain = true; throw error;
  }
  if (response.status === 401) { location.replace('/login'); throw new Error('Please sign in again.'); }
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || 'The secretary is unavailable.');
    error.uncertain = response.status >= 500; throw error;
  }
  return result;
}

function composeState() {
  sendButton.disabled = sending || !chatConfig.connected || (chat && state !== 'idle');
  textBox.disabled = sending || (chat && state !== 'idle');
  sendButton.textContent = chat ? 'Send reply' : modes[mode][2];
  textBox.required = !chat && ['todo','eureka'].includes(mode) || Boolean(chat);
  document.querySelector('#compose-note').textContent = chat && state !== 'idle'
    ? 'Answer pending questions below, or wait for your secretary.' : 'Only your chosen mode. No commands needed.';
}

function showMode() {
  document.querySelectorAll('[data-mode]').forEach(button => {
    const selected = button.dataset.mode === mode;
    button.setAttribute('aria-checked', String(selected)); button.tabIndex = selected ? 0 : -1;
  });
  document.querySelector('#chat-welcome').textContent = modes[mode][0];
  document.querySelector('#mode-description').textContent = modes[mode][1];
  document.querySelector('#chat-hint').textContent = mode === 'initialize'
    ? 'Start with your preferred language. Review the rest a few answers at a time.' : 'Write in your own words. Your secretary will take it from here.';
  composeState();
}

function newConversation(next = chatConfig.defaultMode) {
  drafts.set(mode, textBox.value);
  clearTimeout(timer); revision++;
  chat = null; state = null; sending = false; mode = next;
  history.replaceState(null, '', '/chat');
  formSignature = ''; messageSignature = '';
  document.querySelector('#chat-messages').replaceChildren();
  document.querySelector('#chat-questions').replaceChildren();
  document.querySelector('#chat-empty').hidden = false;
  document.querySelector('#chat-status').textContent = '';
  errorBox.textContent = '';
  textBox.value = drafts.get(mode) || '';
  showMode();
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

async function historyList() {
  const result = await chatAPI('/api/chats');
  chatConfig.defaultMode = result.defaultMode;
  chatConfig.connected = result.connected;
  document.querySelector('#chat-history').replaceChildren(...result.chats.map(item => {
    const link = make('a', item.title); link.href = '/chat?id=' + item.id;
    link.append(make('small', item.mode === 'todo' ? 'To-do' : item.mode[0].toUpperCase() + item.mode.slice(1)));
    if (item.id === chat) link.setAttribute('aria-current', 'page');
    return link;
  }));
}

function showMessages(messages) {
  const signature = JSON.stringify(messages);
  if (signature === messageSignature) return;
  const log = document.querySelector('#chat-messages');
  const nearBottom = document.documentElement.scrollHeight - scrollY - innerHeight < 240;
  const existing = new Map([...log.children].map(node => [node.dataset.message, node]));
  const nodes = messages.map(item => {
    let bubble = existing.get(item.id);
    if (!bubble) {
      bubble = make('section', '', 'chat-message ' + item.role);
      bubble.dataset.message = item.id;
      bubble.append(make('p', item.role === 'user' ? 'You' : 'Your secretary', 'message-author'), make('div', '', 'message-text'));
      log.append(bubble);
    }
    const content = bubble.querySelector('.message-text');
    if (content.textContent !== item.text) content.textContent = item.text;
    return bubble;
  });
  [...log.children].filter(node => !nodes.includes(node)).forEach(node => node.remove());
  document.querySelector('#chat-empty').hidden = messages.length > 0;
  messageSignature = signature;
  if (nearBottom && messages.length) log.lastElementChild.scrollIntoView({block:'nearest'});
}

async function pollChat() {
  clearTimeout(timer);
  if (!chat || document.hidden || polling) return;
  polling = true;
  const current = chat; const version = revision;
  try {
    const result = await chatAPI('/api/chats/' + current);
    if (version !== revision) return;
    mode = result.mode; state = result.state;
    document.querySelector('#chat-status').textContent = result.label;
    if (result.messages) showMessages(result.messages);
    const signature = JSON.stringify([result.forms, result.permissions]);
    if (signature !== formSignature) {
      const refreshed = () => { formSignature = ''; pollChat(); };
      const reply = (category, id, body) => chatAPI(`/api/chats/${current}/${category}/${id}/reply`, body);
      document.querySelector('#chat-questions').replaceChildren(
        ...result.forms.map(info => secretaryQuestion(info, reply, refreshed)),
        ...result.permissions.map(info => secretaryPermission(info, reply, refreshed)));
      formSignature = signature;
    }
    showMode();
    if (state === 'idle') await historyList();
  } catch (error) {
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
  const request = crypto.randomUUID().replaceAll('-', '');
  const current = chat || request;
  const version = revision;
  sending = true; errorBox.textContent = ''; composeState();
  try {
    await chatAPI(first ? '/api/chats' : `/api/chats/${current}/messages`,
      first ? {id: current, mode, text: textBox.value} : {id: request, text: textBox.value});
    if (version !== revision) return;
    chat = current; state = 'starting'; textBox.value = ''; drafts.delete(mode);
    history.replaceState(null, '', '/chat?id=' + chat);
    await historyList();
  } catch (error) {
    if (version !== revision) return;
    errorBox.textContent = error.message;
    if (error.uncertain) {
      chat = current; state = 'uncertain';
      history.replaceState(null, '', '/chat?id=' + chat);
    }
  } finally {
    if (version === revision) { sending = false; composeState(); if (chat) pollChat(); }
  }
});

document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(timer); else pollChat(); });
window.addEventListener('focus', () => { if (chat) pollChat(); });
showMode();
historyList().catch(error => { errorBox.textContent = error.message; });
if (chat) pollChat();
