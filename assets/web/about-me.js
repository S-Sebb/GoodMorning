// About me: edit a profile line in place, or switch an evening extra on or off.
// Without scripts the page is read-only; every change is one request that the server checks.
(() => {
  const page = document.querySelector('.about-me');
  if (!page) return;
  const t = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;

  // Country codes read as names in the website language.
  function names() {
    const language = document.documentElement.lang;
    let regions;
    try { regions = new Intl.DisplayNames([language], {type: 'region'}); } catch { return; }
    const list = new Intl.ListFormat([language], {type: 'conjunction'});
    page.querySelectorAll('[data-countries]').forEach(node => { node.textContent = list.format(node.dataset.countries.split(',').map(code => regions.of(code))); });
    page.querySelectorAll('[data-region]').forEach(node => { node.textContent = t('{region} store', {region: regions.of(node.dataset.region)}); });
  }

  function feedback(row, message, failed) {
    let box = row.querySelector('.about-feedback');
    if (!box) {
      box = document.createElement('dd');
      box.className = 'about-feedback'; box.setAttribute('role', 'status');
      row.append(box);
    }
    box.textContent = message;
    box.classList.toggle('is-error', Boolean(failed));
  }

  async function save(row, value) {
    let response, result;
    try {
      response = await fetch('/api/about-me', {method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': csrf}, body: JSON.stringify({field: row.dataset.field, value})});
      if (response.status === 401) { location.replace('/login'); return null; }
      result = await goodmorningJSON(response);
    } catch {
      feedback(row, t('Couldn’t confirm the save. Refresh the page to see what’s saved.'), true);
      return null;
    }
    if (response.status === 400 && result.error) { feedback(row, t('Not saved. {reason}', {reason: result.error}), true); return null; }
    if (!response.ok || result.field !== row.dataset.field) {
      feedback(row, t('Couldn’t confirm the save. Refresh the page to see what’s saved.'), true);
      return null;
    }
    feedback(row, t('Saved. Your secretary will use this from now on.'));
    return result.value;
  }

  function show(row, value) {
    const content = row.querySelector('.about-content');
    const node = document.createElement('span');
    if (value) { node.className = 'about-value'; node.dataset.content = ''; node.textContent = value; }
    else { node.className = 'about-empty'; node.dataset.uiText = 'Not set yet'; node.textContent = t('Not set yet'); }
    content.replaceChildren(node);
  }

  function edit(row) {
    const content = row.querySelector('.about-content');
    const action = row.querySelector('.about-action');
    const editButton = action.querySelector('.about-edit');
    const before = content.querySelector('.about-value')?.textContent || '';
    const input = Object.assign(document.createElement('input'), {type: 'text', value: before, maxLength: Number(editButton.dataset.limit)});
    input.setAttribute('aria-labelledby', 'about-label-' + row.dataset.field);
    const button = (label, kind) => Object.assign(document.createElement('button'), {type: 'button', className: kind, textContent: t(label)});
    const saveButton = button('Save', 'about-save'), cancelButton = button('Cancel', 'about-cancel');
    const finish = value => {
      show(row, value);
      action.replaceChildren(editButton);
      editButton.focus({preventScroll: true});
    };
    const submit = async () => {
      input.disabled = saveButton.disabled = cancelButton.disabled = true;
      const saved = await save(row, input.value);
      if (saved !== null) return finish(saved);
      input.disabled = saveButton.disabled = cancelButton.disabled = false;
      input.focus();
    };
    saveButton.addEventListener('click', submit);
    cancelButton.addEventListener('click', () => finish(before));
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); submit(); }
      if (event.key === 'Escape') { event.preventDefault(); finish(before); }
    });
    row.querySelector('.about-feedback')?.remove();
    content.replaceChildren(input);
    action.replaceChildren(saveButton, cancelButton);
    input.focus();
    input.select();
  }

  document.addEventListener('website:language', names);
  names();
  // Before setup there is no profile to change; the page stays read-only.
  if (page.hasAttribute('data-readonly')) return;
  page.querySelectorAll('.about-edit').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => edit(button.closest('.about-row')));
  });
  page.querySelectorAll('.about-switch').forEach(control => {
    control.hidden = false;
    control.addEventListener('click', async () => {
      const wanted = control.getAttribute('aria-checked') !== 'true';
      control.disabled = true;
      const saved = await save(control.closest('.about-row'), String(wanted));
      if (saved !== null) control.setAttribute('aria-checked', String(saved === 'true'));
      control.disabled = false;
    });
  });
})();
