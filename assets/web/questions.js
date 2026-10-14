// Shared question widgets. Agent text is always text, never executable markup.
const questionT = (key, values = {}) => typeof goodmorningT === 'function' ? goodmorningT(key, values) : key.replace(/\{([a-z]+)\}/g,(token,name)=>values[name] ?? token);
function secretaryElement(tag, text = '', className = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function secretaryQuestion(info, send, refreshed, language) {
  const make = secretaryElement;
  const form = make('form', '', 'agent-form');
  if (['en','zh-CN'].includes(language)) form.lang=language;
  const generic = !info.title || info.title === 'Questions';
  const heading = make('h2', generic ? questionT('A question for you') : info.title);
  if (generic) {
    heading.dataset.uiText = 'A question for you';
    if (typeof goodmorningLanguage !== 'undefined') heading.lang = goodmorningLanguage;
  }
  form.append(heading);
  const controls = new Map();
  let unsupported = false;
  for (const field of info.fields) {
    const group = make('fieldset');
    group.append(make('legend', field.title || questionT('Your answer')));
    if (field.description) group.append(make('p', field.description));
    const inputs = [];
    let custom;
    if (field.options) {
      const single = field.type !== 'multiselect' || field.maxItems === 1;
      if (field.custom) {
        custom = make('input'); custom.type = 'text';
        custom.placeholder = field.placeholder || questionT('Or write your own answer');
        if (!field.placeholder) custom.setAttribute('data-ui-placeholder','Or write your own answer');
        custom.setAttribute('data-ui-aria-label','Your own answer');
        custom.setAttribute('aria-label', questionT('Your own answer'));
        if (field.customFirst) group.append(custom);
      }
      const optionGroups = new Map();
      for (const option of field.options) {
        let target = group;
        if (typeof option.group === 'string' && option.group) {
          if (!optionGroups.has(option.group)) {
            const section = make('fieldset', '', 'answer-project-group');
            section.append(make('legend', option.group));
            optionGroups.set(option.group, section); group.append(section);
          }
          target = optionGroups.get(option.group);
        }
        const label = make('label', '', 'answer-option');
        const input = make('input');
        input.type = single ? 'radio' : 'checkbox';
        input.name = field.key; input.value = option.value;
        input.checked = Array.isArray(field.default) ? field.default.includes(option.value) : field.default === option.value;
        label.append(input, make('span', option.label));
        if (option.description) label.append(make('small', option.description));
        target.append(label); inputs.push(input);
      }
      if (custom) {
        if (!field.customFirst) group.append(custom);
        custom.addEventListener('input', () => { if (custom.value && single) inputs.forEach(input => { input.checked = false; }); });
        inputs.forEach(input => input.addEventListener('change', () => { if (input.checked && single) custom.value = ''; }));
      }
    } else if (['string', 'number', 'integer', 'boolean'].includes(field.type)) {
      const input = make(field.type === 'string' && !field.format ? 'textarea' : 'input');
      if (input.tagName === 'INPUT') input.type = field.type === 'boolean' ? 'checkbox' : ['number','integer'].includes(field.type) ? 'number' : field.format === 'date' ? 'date' : 'text';
      if (field.type === 'integer') input.step = '1';
      if (field.type === 'boolean') input.checked = field.default === true;
      else input.value = field.default ?? '';
      input.setAttribute('aria-label', field.title || questionT('Your answer'));
      input.required = field.required && field.type !== 'boolean';
      for (const key of ['placeholder','minLength','maxLength']) if (field[key] !== undefined) input[key] = field[key];
      if (Number.isFinite(field.minimum)) input.min = field.minimum;
      if (Number.isFinite(field.maximum)) input.max = field.maximum;
      group.append(input); inputs.push(input);
    } else {
      group.append(make('p', questionT('This question needs administrator help in OpenChamber. Your answers remain unchanged.')));
      unsupported = true;
    }
    controls.set(field.key, { field, group, inputs, custom });
    form.append(group);
  }
  function value({ field, inputs, custom }) {
    if (field.options) {
      const selected = inputs.filter(input => input.checked).map(input => input.value);
      if (custom?.value.trim()) selected.push(custom.value.trim());
      return field.type === 'multiselect' ? selected : selected[0] ?? '';
    }
    if (field.type === 'boolean') return inputs[0].checked;
    if (field.type === 'number' || field.type === 'integer') return inputs[0].value === '' ? undefined : Number(inputs[0].value);
    return inputs[0]?.value;
  }
  function visibility() {
    for (const control of controls.values()) {
      control.group.hidden = control.field.hidden === true || (control.field.when || []).some(condition => {
        const other = controls.get(condition.key);
        const equal = other && value(other) === condition.value;
        return condition.op === 'eq' ? !equal : equal;
      });
      control.inputs.forEach(input => { input.disabled = control.group.hidden; });
      if (control.custom) control.custom.disabled = control.group.hidden;
    }
  }
  form.addEventListener('input', visibility); visibility();
  const submit = make('button', questionT('Send answer')); submit.dataset.uiText='Send answer'; submit.type = 'submit'; submit.disabled = unsupported;
  if (typeof goodmorningLanguage !== 'undefined') submit.lang=goodmorningLanguage;
  const feedback = make('p'); feedback.setAttribute('role', 'alert');
  form.append(submit, feedback);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const answer = {};
    for (const [key, control] of controls) {
      if (control.group.hidden) continue;
      const result = value(control);
      if (control.field.type === 'multiselect') {
        const min = control.field.minItems ?? (control.field.required ? 1 : 0);
        const max = control.field.maxItems ?? Infinity;
        if (result.length < min || result.length > max) { feedback.textContent = questionT('Please select between {min} and {max} answers.',{min,max:max === Infinity ? questionT('all available') : max}); return; }
      }
      if (control.field.required && (result === '' || result === undefined)) { feedback.textContent = questionT('Please answer the required questions.'); return; }
      if (result !== undefined) answer[key] = result;
    }
    submit.disabled = true;
    try { await send('form', info.id, { answer }); form.remove(); refreshed(); }
    catch (error) { feedback.textContent = error.message; submit.disabled = false; }
  });
  return form;
}

function secretaryPermission(info, send, refreshed, language) {
  const make = secretaryElement;
  const form = make('section', '', 'agent-form');
  if (['en','zh-CN'].includes(language)) form.lang=language;
  const heading=make('h2',questionT('Permission needed'));heading.dataset.uiText='Permission needed';
  if (typeof goodmorningLanguage !== 'undefined') heading.lang=goodmorningLanguage;
  form.append(heading, make('p', info.action));
  for (const resource of info.resources) form.append(make('pre', resource));
  const feedback = make('p'); feedback.setAttribute('role', 'alert');
  for (const [decision, text] of [['once','Allow once'], ['reject','Decline']]) {
    const button = make('button', questionT(text)); button.dataset.uiText=text; button.type = 'button';
    if (typeof goodmorningLanguage !== 'undefined') button.lang=goodmorningLanguage;
    button.addEventListener('click', async () => {
      form.querySelectorAll('button').forEach(item => { item.disabled = true; });
      try { await send('permission', info.id, { decision }); form.remove(); refreshed(); }
      catch (error) { feedback.textContent = error.message; form.querySelectorAll('button').forEach(item => { item.disabled = false; }); }
    });
    form.append(button);
  }
  form.append(feedback);
  return form;
}
