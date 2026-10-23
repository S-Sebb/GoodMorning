// Friends menu and the username form in Account. Friendship starts with a request the other person
// accepts; each friend has their own switches for what they can see, all off at first.
(() => {
  const menu = document.querySelector('#friends-menu');
  if (!menu) return;
  const t = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;
  const LABELS = {schedule: 'Schedule', todos: 'To-dos', stocks: 'Stocks', anime: 'New episodes', games: 'Game sales'};
  const badge = menu.querySelector('#friends-badge');
  const feedback = menu.querySelector('#friend-feedback');
  const nameInput = menu.querySelector('#friend-name');
  const usernameForm = document.querySelector('#username-form');
  let state = null;
  let accepting = null;  // The incoming request whose switches are showing.
  const open = new Set();  // Friends whose rows are expanded, kept across redraws.

  const post = async (path, body) => {
    const response = await fetch(path, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': csrf}, body: JSON.stringify(body)});
    const value = await goodmorningJSON(response);
    if (!response.ok) throw new Error(value.error || t('That could not be saved. Refresh the page and try again.'));
    return value;
  };
  const element = (tag, attributes = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
      if (key === 'text') node.textContent = value; else node.setAttribute(key, value);
    }
    node.append(...children);
    return node;
  };
  const button = (text, action, variant) => {
    const node = element('button', {type: 'button', text: t(text), ...(variant ? {class: variant} : {})});
    node.addEventListener('click', async () => {
      node.disabled = true;
      try { await action(); } catch (error) { feedback.textContent = error.message; node.disabled = false; }
    });
    return node;
  };
  // A switch per section; changes reach onChange with the full new list.
  const switches = (legend, chosen, onChange) => {
    const set = element('fieldset', {class: 'friend-sharing'}, element('legend', {text: legend}));
    for (const key of state.sections) {
      const box = element('input', {type: 'checkbox', name: key});
      box.checked = chosen.includes(key);
      box.addEventListener('change', () => onChange(state.sections.filter(name => set.elements[name].checked), box));
      set.append(element('label', {}, box, ' ' + t(LABELS[key])));
    }
    set.append(element('p', {class: 'notification-note', text: t('Schedule shows event titles and times only, never notes or places.')}));
    return set;
  };

  function draw() {
    const incoming = menu.querySelector('#friend-incoming');
    const outgoing = menu.querySelector('#friend-outgoing');
    const list = menu.querySelector('#friend-list');
    badge.hidden = !state.incoming.length;
    badge.textContent = state.incoming.length;
    badge.setAttribute('aria-label', t('{count} friend requests', {count: state.incoming.length}));
    menu.querySelector('#friend-requests').hidden = !state.incoming.length && !state.outgoing.length;
    incoming.replaceChildren(...state.incoming.map(name => {
      const item = element('li', {class: 'friend-request'},
        element('div', {}, element('strong', {text: name}), element('small', {text: t('wants to be friends')})));
      if (accepting === name) {
        let chosen = [];
        item.append(switches(t('Choose what {name} can see', {name}), [], value => { chosen = value; }),
          element('div', {class: 'friend-actions'},
            button('Accept', async () => {
              apply(await post('/api/friends/accept', {name, sections: chosen}));
              accepting = null;
              feedback.textContent = t('You and {name} are friends now.', {name});
            }, 'primary'),
            button('Back', async () => { accepting = null; draw(); })));
      } else {
        item.append(element('div', {class: 'friend-actions'},
          button('Accept', async () => { accepting = name; draw(); }, 'primary'),
          button('Decline', async () => { apply(await post('/api/friends/decline', {name})); feedback.textContent = ''; })));
      }
      return item;
    }));
    outgoing.replaceChildren(...state.outgoing.map(name => element('li', {class: 'friend-request'},
      element('div', {}, element('strong', {text: name}), element('small', {text: t('Waiting for them to accept')})),
      element('div', {class: 'friend-actions'}, button('Cancel', async () => apply(await post('/api/friends/cancel', {name})))))));
    menu.querySelector('#friend-empty').hidden = state.friends.length > 0;
    list.replaceChildren(...state.friends.map(friend => {
      const sharing = friend.sharing.length ? friend.sharing.map(key => t(LABELS[key])).join(t(', ')) : t('Sharing nothing');
      const details = element('details', {class: 'friend'},
        element('summary', {}, element('strong', {text: friend.name}), element('small', {text: sharing})));
      details.open = open.has(friend.name);
      details.addEventListener('toggle', () => { if (details.open) open.add(friend.name); else open.delete(friend.name); });
      details.append(
        element('a', {class: 'friend-page', href: '/friends/' + encodeURIComponent(friend.name), text: t('Open {name}’s page', {name: friend.name})}),
        switches(t('What {name} can see', {name: friend.name}), friend.sharing, async (value, box) => {
          box.disabled = true;
          try {
            apply(await post('/api/friends/share', {name: friend.name, sections: value}));
            feedback.textContent = t('Saved. {name} sees this the next time their page loads.', {name: friend.name});
          } catch (error) { box.checked = !box.checked; box.disabled = false; feedback.textContent = error.message; }
        }),
        element('div', {class: 'friend-actions'}, button('Remove friend', async () => {
          if (!confirm(t('Remove {name}? You will stop seeing each other’s shared sections.', {name: friend.name}))) throw new Error('');
          open.delete(friend.name);
          apply(await post('/api/friends/remove', {name: friend.name}));
          feedback.textContent = t('{name} is no longer your friend.', {name: friend.name});
        }, 'danger')));
      return element('li', {}, details);
    }));
  }

  function apply(value) {
    state = value;
    draw();
    // The saved name is the field's default, so refreshing does not count it as unsent text.
    if (usernameForm && !usernameForm.contains(document.activeElement)) {
      const field = usernameForm.elements.username;
      field.defaultValue = field.value = value.name;
    }
  }

  menu.querySelector('#friend-add').addEventListener('submit', async event => {
    event.preventDefault();
    const submit = event.target.querySelector('button[type="submit"]');
    const name = nameInput.value.trim();
    submit.disabled = true; feedback.textContent = '';
    try {
      const value = await post('/api/friends/request', {name});
      apply(value); nameInput.value = '';
      feedback.textContent = value.result === 'friends' ? t('{name} had already asked you, so you are friends now.', {name: name.toLowerCase()})
        : t('Request sent. {name} will see it in their Friends menu.', {name: name.toLowerCase()});
    } catch (error) { feedback.textContent = error.message; }
    finally { submit.disabled = false; }
  });

  if (usernameForm) usernameForm.addEventListener('submit', async event => {
    event.preventDefault();
    const status = usernameForm.querySelector('#username-feedback');
    const submit = usernameForm.querySelector('button[type="submit"]');
    submit.disabled = true; status.textContent = '';
    try {
      const value = await post('/api/account/username', {username: usernameForm.elements.username.value.trim(), password: usernameForm.elements.password.value});
      usernameForm.elements.password.value = '';
      apply(value);
      status.textContent = t('Your username is now {name}. Use it the next time you sign in.', {name: value.name});
    } catch (error) { status.textContent = error.message; }
    finally { submit.disabled = false; }
  });

  document.addEventListener('website:language', () => { if (state) draw(); });
  (async () => {
    try {
      const response = await fetch('/api/friends', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      apply(await goodmorningJSON(response));
      if (usernameForm) usernameForm.hidden = false;
    } catch { /* Without the server's answer the menu stays empty. */ }
  })();
})();
