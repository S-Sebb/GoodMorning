// Only the server shares account activity; links stay in the current tab.
(() => {
  const panel = document.querySelector('#account-activity');
  if (!panel) return;
  const items = document.querySelector('#activity-items');
  const windowBox = document.querySelector('#activity-window');
  const restore = document.querySelector('#activity-restore');
  const minimize = document.querySelector('#activity-minimize');
  const origins = JSON.parse(panel.dataset.origins);
  const modes = {secretary: 'Secretary', initialize: 'Initialize', todo: 'To-do', eureka: 'Eureka', gm: 'Morning briefing', gn: 'Evening briefing'};
  const states = {working: 'Your secretary is working', waiting: 'Your secretary needs your answer', queued: 'Your request is queued.',
    uncertain: 'Activity needs checking. Open it before trying again.', unavailable: 'Activity status is unavailable. Open it to check.'};
  const titles = {working: 'Making a little room for you.', waiting: 'A little question for you.',
    queued: 'Your request is in line.', uncertain: 'Let’s check on this.', unavailable: 'Let’s check on this.'};
  let activity = [], fetching = false, signature = '';
  let collapsed = matchMedia('(max-width: 700px)').matches;
  function collapse(value, focus = false) {
    collapsed = value;
    windowBox.hidden = collapsed;
    restore.hidden = !collapsed;
    restore.setAttribute('aria-expanded', String(!collapsed));
    if (focus) (collapsed ? restore : minimize).focus({preventScroll: true});
  }
  minimize.addEventListener('click', () => collapse(true, true));
  restore.addEventListener('click', () => collapse(false, true));
  const make = (tag, text = '', className = '') => {
    const node = document.createElement(tag);
    node.textContent = text;
    node.className = className;
    return node;
  };
  function render() {
    const next = JSON.stringify([activity, goodmorningT('Ongoing activity')]);
    if (signature === next) return;
    signature = next;
    const heading = goodmorningT('Ongoing activity');
    document.querySelector('#activity-heading').textContent = goodmorningT('Your secretary');
    panel.setAttribute('aria-label', heading);
    items.replaceChildren(...activity.map(entry => {
      const row = document.createElement('div');
      row.className = 'activity-item'; row.dataset.state = entry.state;
      const body = make('div', '', 'activity-window-body');
      const desk = make('div', '', 'activity-desk');
      desk.setAttribute('aria-hidden', 'true');
      desk.append(document.querySelector('#activity-desk-art').content.cloneNode(true), make('span', '?', 'activity-question-mark'));
      const copy = make('div', '', 'activity-copy');
      copy.append(make('p', goodmorningT(titles[entry.state]), 'activity-title'), make('p', goodmorningT(states[entry.state]), 'activity-detail'));
      body.append(desk, copy);
      const footer = make('div', '', 'activity-footer');
      const mode = make('span', '', 'activity-mode');
      const dots = make('span', '', 'activity-dots');
      dots.setAttribute('aria-hidden', 'true');
      dots.append(make('i'), make('i'), make('i'));
      mode.append(dots, make('span', goodmorningT(modes[entry.mode])));
      const link = document.createElement('a');
      link.href = entry.url;
      link.textContent = goodmorningT('Open activity');
      link.setAttribute('aria-label', `${goodmorningT('Open activity')}: ${goodmorningT(modes[entry.mode])} · ${goodmorningT(states[entry.state])}`);
      const arrow = make('span', '→'); arrow.setAttribute('aria-hidden', 'true'); link.append(arrow);
      footer.append(mode, link);
      row.append(body, footer); return row;
    }));
    panel.hidden = !activity.length;
    if (activity.length) {
      panel.dataset.state = activity[0].state;
      document.querySelector('#activity-summary').textContent = goodmorningT(states[activity[0].state]);
      restore.setAttribute('aria-label', goodmorningT('Expand ongoing activity') + ': ' + goodmorningT(states[activity[0].state]));
    }
    collapse(collapsed);
  }
  async function sync() {
    if (document.hidden || fetching) return;
    fetching = true;
    try {
      const response = await fetch('/api/activity', {credentials: 'same-origin', cache: 'no-store'});
      if ([401, 403].includes(response.status)) { activity = []; render(); return; }
      if (!response.ok) throw new Error('Unavailable');
      const value = await response.json();
      if (!Array.isArray(value.activity)) throw new Error('Invalid activity');
      activity = value.activity.filter(entry => {
        if (!Object.hasOwn(states, entry.state) || !Object.hasOwn(modes, entry.mode)) return false;
        try {
          const url = new URL(entry.url);
          return origins.includes(url.origin) && !url.username && !url.password &&
            /^(?:\/|\/chat\?id=[a-f0-9]{32}|\/d\/\d{4}-\d{2}-\d{2}\/(?:gm|gn)\.html)$/.test(url.pathname + url.search);
        } catch { return false; }
      });
      render();
    } catch {
      // An outage is not evidence that known work finished. Preserve its link.
      activity = activity.map(entry => ({...entry, state: 'unavailable'})); render();
    } finally { fetching = false; }
  }
  document.addEventListener('website:language', render);
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('focus', sync);
  setInterval(sync, 10000);
  sync();
})();
