// Idea cards in Reminders close with one tap. A saved briefing is a snapshot, so each idea's live state is asked for.
const ideaCards = new WeakMap();
async function ideaRequest(path, options) {
  const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options});
  const result = await goodmorningJSON(response);
  if (!response.ok) throw Object.assign(new Error(result?.error || ''), {status: response.status});
  return result;
}
function ideaLabel(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  node.dataset.uiText = text;
  node.textContent = goodmorningT(text);
  return node;
}
function showIdea(card, state) {
  ideaCards.set(card, state);
  card.classList.toggle('is-closed', state.closed);
  card.querySelector('.idea-actions')?.remove();
  const ask = card.querySelector('.decision-ask');
  if (ask) ask.hidden = state.closed;
  const actions = document.createElement('div');
  actions.className = 'idea-actions';
  const button = ideaLabel('button', state.closed ? 'idea-undo' : 'idea-done', state.closed ? 'Undo' : 'Mark as done');
  button.type = 'button';
  button.addEventListener('click', () => saveIdea(card, button));
  if (state.closed) actions.append(ideaLabel('span', 'idea-closed', 'Idea closed. It won’t show in your briefings anymore.'));
  actions.append(button);
  const error = document.createElement('p');
  error.className = 'idea-error';
  error.setAttribute('role', 'alert');
  actions.append(error);
  if (ask) ask.before(actions); else card.append(actions);
}
async function saveIdea(card, button) {
  const state = ideaCards.get(card);
  button.disabled = true;
  try {
    const saved = await ideaRequest('/api/ideas/close', {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': languageConfig.csrf},
      body: JSON.stringify({id: card.dataset.entry, revision: state.revision, closed: !state.closed, key: crypto.randomUUID()})});
    showIdea(card, {revision: saved.revision, closed: saved.closed});
    card.querySelector('.idea-actions button').focus({preventScroll: true});
  } catch (error) {
    button.disabled = false;
    card.querySelector('.idea-error').textContent = goodmorningT(error.status === 409 ? error.message
      : 'Couldn’t save. Check your connection and try again.');
  }
}
async function findIdeas() {
  const cards = [...document.querySelectorAll('.decision-card[data-entry]')].filter(card => !ideaCards.has(card));
  if (!cards.length) return;
  try {
    const {ideas} = await ideaRequest('/api/ideas?ids=' + cards.slice(0, 50).map(card => card.dataset.entry).join(','));
    cards.forEach(card => { if (ideas[card.dataset.entry]) showIdea(card, ideas[card.dataset.entry]); });
  } catch {
    // Offline copies and failed reads keep the plain card; the secretary can still close the idea.
  }
}
document.addEventListener('briefing:updated', findIdeas);
findIdeas();
