// About me: edit a profile line or a part of the memory note in place, or switch a setting on or off.
// Without scripts the page is read-only; every change is one request that the server checks.
(() => {
  const page = document.querySelector('.about-me');
  if (!page) return;
  const t = (key, values) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key;
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;
  // The secretary's saved name, or "your secretary" before there is one.
  const secretary = page.dataset.secretary;
  const named = (text, unnamed) => secretary ? text.replace('{name}', secretary) : unnamed;

  // Public-holiday regions, with names in both website languages.
  const holidayRegions = JSON.parse(page.querySelector('[data-holiday-regions]')?.dataset.holidayRegions || '[]');
  const holidayName = code => {
    const region = holidayRegions.find(entry => entry.code === code);
    const pick = pair => pair[document.documentElement.lang.startsWith('zh') ? 1 : 0];
    return region.region ? pick(region.country) + ' — ' + pick(region.region) : pick(region.country);
  };

  // A month and day, such as "February 13", in the website language.
  const monthDay = (text, options = {month: 'long', day: 'numeric'}) => {
    const [month, day] = text.split('-').map(Number);
    return new Intl.DateTimeFormat([document.documentElement.lang], {...options, timeZone: 'UTC'}).format(Date.UTC(2000, month - 1, day));
  };

  // Country codes read as names in the website language.
  function names() {
    const language = document.documentElement.lang;
    page.querySelectorAll('[data-birthday]').forEach(node => { node.textContent = monthDay(node.dataset.birthday); });
    page.querySelectorAll('[data-holidays]').forEach(node => {
      node.textContent = node.dataset.holidays.split(',').map(holidayName).join(language.startsWith('zh') ? '、' : ', ');
    });
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

  async function save(row, value, field = row.dataset.field, done = named('Saved! {name} will remember this.', 'Saved! Your secretary will remember this.')) {
    let response, result;
    try {
      response = await fetch('/api/about-me', {method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': csrf}, body: JSON.stringify({field, value})});
      if (response.status === 401) { location.replace('/login'); return null; }
      result = await goodmorningJSON(response);
    } catch {
      feedback(row, t('Couldn’t confirm the save. Refresh the page to see what’s saved.'), true);
      return null;
    }
    if (response.status === 400 && result.error) { feedback(row, t('Not saved. {reason}', {reason: result.error}), true); return null; }
    if (!response.ok || result.field !== field) {
      feedback(row, t('Couldn’t confirm the save. Refresh the page to see what’s saved.'), true);
      return null;
    }
    feedback(row, t(done));
    return result.value;
  }

  function show(row, value) {
    const content = row.querySelector('.about-content');
    const node = document.createElement('span');
    if (value) { node.className = 'about-value'; node.dataset.content = ''; node.textContent = value; }
    else {
      node.className = 'about-empty';
      node.dataset.uiText = row.dataset.empty || named('{name} doesn’t know yet', 'Your secretary doesn’t know yet');
      node.textContent = t(node.dataset.uiText);
    }
    content.replaceChildren(node);
  }

  // Holidays are picked from the listed regions: China and the US whole, the others by nation, state or province.
  function editHolidays(row) {
    const content = row.querySelector('.about-content');
    const action = row.querySelector('.about-action');
    const editButton = action.querySelector('.about-edit');
    const before = [...content.childNodes];
    const chosen = new Set((content.querySelector('[data-holidays]')?.dataset.holidays || '').split(','));
    const picker = document.createElement('div');
    picker.className = 'about-holidays';
    picker.setAttribute('role', 'group');
    picker.setAttribute('aria-labelledby', 'about-label-' + row.dataset.field);
    const box = entry => {
      const label = document.createElement('label');
      const input = Object.assign(document.createElement('input'), {type: 'checkbox', value: entry.code, checked: chosen.has(entry.code)});
      label.append(input, holidayName(entry.code).split(' — ').pop());
      return label;
    };
    const countries = new Map();
    holidayRegions.forEach(entry => countries.set(entry.country[0], [...(countries.get(entry.country[0]) || []), entry]));
    countries.forEach(entries => {
      if (entries.length === 1) return picker.append(box(entries[0]));
      const group = document.createElement('fieldset');
      const legend = document.createElement('legend');
      legend.textContent = entries[0].country[document.documentElement.lang.startsWith('zh') ? 1 : 0];
      group.append(legend, ...entries.map(box));
      picker.append(group);
    });
    const button = (label, kind) => Object.assign(document.createElement('button'), {type: 'button', className: kind, textContent: t(label)});
    const saveButton = button('Save', 'about-save'), cancelButton = button('Cancel', 'about-cancel');
    const finish = nodes => {
      content.replaceChildren(...nodes);
      action.replaceChildren(editButton);
      editButton.focus({preventScroll: true});
    };
    saveButton.addEventListener('click', async () => {
      const inputs = [...picker.querySelectorAll('input'), saveButton, cancelButton];
      inputs.forEach(input => { input.disabled = true; });
      const saved = await save(row, [...picker.querySelectorAll('input:checked')].map(input => input.value).join(', '));
      if (saved === null) return inputs.forEach(input => { input.disabled = false; });
      const node = document.createElement('span');
      node.className = 'about-value';
      if (saved === 'none') { node.dataset.uiText = 'No public holidays'; node.textContent = t(node.dataset.uiText); }
      else { node.dataset.holidays = saved.split(', ').join(','); }
      finish([node]);
      names();
    });
    cancelButton.addEventListener('click', () => finish(before));
    row.querySelector('.about-feedback')?.remove();
    content.replaceChildren(picker);
    action.replaceChildren(saveButton, cancelButton);
    picker.querySelector('input').focus();
  }

  // A birthday is a month and day, never a year; the empty choice clears it.
  function editBirthday(row) {
    const content = row.querySelector('.about-content');
    const action = row.querySelector('.about-action');
    const editButton = action.querySelector('.about-edit');
    const before = [...content.childNodes];
    const [month, day] = (content.querySelector('[data-birthday]')?.dataset.birthday || '-').split('-');
    const list = (values, label, chosen) => {
      const select = document.createElement('select');
      select.append(new Option('—', ''), ...values.map(([text, value]) => new Option(text, value, false, value === chosen)));
      select.setAttribute('aria-label', label);
      return select;
    };
    const pad = number => String(number).padStart(2, '0');
    const months = list([...Array(12)].map((_, index) => [monthDay(pad(index + 1) + '-01', {month: 'long'}), pad(index + 1)]), t('Month'), month);
    let days;
    // 2000 is a leap year, so 29 February can be picked.
    const fill = () => {
      const count = months.value ? new Date(Date.UTC(2000, Number(months.value), 0)).getUTCDate() : 31;
      const chosen = days?.value || day;
      const next = list([...Array(count)].map((_, index) => [String(index + 1), pad(index + 1)]), t('Day'), chosen);
      if (days) days.replaceWith(next);
      days = next;
    };
    fill();
    months.addEventListener('change', fill);
    const button = (label, kind) => Object.assign(document.createElement('button'), {type: 'button', className: kind, textContent: t(label)});
    const saveButton = button('Save', 'about-save'), cancelButton = button('Cancel', 'about-cancel');
    const finish = nodes => {
      content.replaceChildren(...nodes);
      action.replaceChildren(editButton);
      editButton.focus({preventScroll: true});
    };
    saveButton.addEventListener('click', async () => {
      const controls = [months, days, saveButton, cancelButton];
      controls.forEach(control => { control.disabled = true; });
      const saved = await save(row, months.value && days.value ? months.value + '-' + days.value : '');
      if (saved === null) return controls.forEach(control => { control.disabled = false; });
      if (!saved) { show(row, ''); action.replaceChildren(editButton); return editButton.focus({preventScroll: true}); }
      const node = Object.assign(document.createElement('span'), {className: 'about-value'});
      node.dataset.birthday = saved;
      node.textContent = monthDay(saved);
      finish([node]);
    });
    cancelButton.addEventListener('click', () => finish(before));
    row.querySelector('.about-feedback')?.remove();
    const picker = Object.assign(document.createElement('div'), {className: 'about-birthday'});
    picker.append(months, days);
    content.replaceChildren(picker);
    action.replaceChildren(saveButton, cancelButton);
    months.focus();
  }

  function edit(row) {
    const content = row.querySelector('.about-content');
    const action = row.querySelector('.about-action');
    const editButton = action.querySelector('.about-edit');
    const actions = [...action.children];
    const before = content.querySelector('.about-value')?.textContent || '';
    // The memory note is prose, so its parts edit in a text area.
    const multiline = 'multiline' in editButton.dataset;
    const input = Object.assign(document.createElement(multiline ? 'textarea' : 'input'), {value: before, maxLength: Number(editButton.dataset.limit)});
    if (multiline) input.rows = 4; else input.type = 'text';
    input.setAttribute('aria-labelledby', 'about-label-' + row.dataset.field);
    const button = (label, kind) => Object.assign(document.createElement('button'), {type: 'button', className: kind, textContent: t(label)});
    const saveButton = button('Save', 'about-save'), cancelButton = button('Cancel', 'about-cancel');
    const finish = value => {
      show(row, value);
      action.replaceChildren(...actions);
      editButton.focus({preventScroll: true});
    };
    const submit = async () => {
      input.disabled = saveButton.disabled = cancelButton.disabled = true;
      const saved = await save(row, input.value);
      // A new secretary name appears all over the page, so it reloads with it.
      if (saved !== null && row.dataset.field === 'secretary_name' && saved !== before) return location.reload();
      if (saved !== null) return finish(saved);
      input.disabled = saveButton.disabled = cancelButton.disabled = false;
      input.focus();
    };
    saveButton.addEventListener('click', submit);
    cancelButton.addEventListener('click', () => finish(before));
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && (!multiline || event.ctrlKey || event.metaKey)) { event.preventDefault(); submit(); }
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
    button.addEventListener('click', () => {
      const row = button.closest('.about-row');
      ({holiday_countries: editHolidays, birthday: editBirthday}[row.dataset.field] || edit)(row);
    });
  });
  // Forgetting deletes the note for good, so it asks first.
  const forget = page.querySelector('#about-memory [data-field="forget"]');
  const forgetAll = forget?.querySelector('.about-forget-all');
  if (forgetAll) {
    forgetAll.hidden = !page.querySelector('#about-memory .about-value[data-content]');
    forgetAll.addEventListener('click', async () => {
      if (!confirm(t('Forget everything your secretary remembers about you? The whole note will be deleted for good.'))) return;
      forgetAll.disabled = true;
      const saved = await save(forget, 'all', 'forget', 'Forgotten.');
      forgetAll.disabled = false;
      if (saved === null) return;
      page.querySelectorAll('#about-memory [data-field^="memory:"]').forEach(row => show(row, ''));
      const empty = Object.assign(document.createElement('span'), {className: 'about-empty'});
      empty.dataset.uiText = named('Nothing yet. Chat with {name} and this note will grow from there.',
        'Nothing yet. Chat with your secretary and this note will grow from there.');
      empty.textContent = t(empty.dataset.uiText);
      forget.querySelector('.about-content').replaceChildren(empty);
      forgetAll.hidden = true;
    });
  }
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
