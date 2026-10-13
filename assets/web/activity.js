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
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const animations = new WeakMap();
  const visibility = new WeakMap();
  let activity = [], fetching = false, refreshPending = false, signature = '', timer;
  let collapsed = matchMedia('(max-width: 700px)').matches;
  function animate(node, frames, duration, finished = () => {}) {
    animations.get(node)?.cancel();
    if (reducedMotion.matches) { animations.delete(node); finished(); return; }
    const animation = node.animate(frames, {duration, easing: 'cubic-bezier(.22, 1, .36, 1)'});
    animations.set(node, animation);
    animation.onfinish = () => {
      if (animations.get(node) !== animation) return;
      animations.delete(node); finished();
    };
  }
  function show(node, visible) {
    if (visibility.get(node) === visible) return;
    visibility.set(node, visible);
    node.inert = !visible;
    if (node.hidden && !visible) return;
    const style = getComputedStyle(node);
    const from = node.hidden ? {opacity: 0, transform: 'translateY(8px) scale(.98)'}
      : {opacity: style.opacity, transform: style.transform};
    node.hidden = false;
    animate(node, [from, {opacity: visible ? 1 : 0,
      transform: visible ? 'none' : 'translateY(6px) scale(.98)'}], visible ? 280 : 200,
      () => { node.hidden = !visible; });
  }
  function collapse(value, focus = false) {
    collapsed = value;
    if (focus) { show(windowBox, !collapsed); show(restore, collapsed); }
    else {
      windowBox.hidden = collapsed; restore.hidden = !collapsed;
      visibility.set(windowBox, !collapsed); visibility.set(restore, collapsed);
    }
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
    if (!activity.length) { show(panel, false); return; }
    const wasHidden = panel.hidden || panel.inert;
    const height = items.getBoundingClientRect().height;
    animations.get(items)?.cancel();
    const existing = new Map([...items.children].map(row => [row.dataset.url, row]));
    const rows = activity.map(entry => {
      let row = existing.get(entry.url);
      const rowSignature = JSON.stringify([entry, heading]);
      if (row?.dataset.signature === rowSignature) return row;
      const created = !row;
      if (created) {
        row = document.createElement('div');
        row.className = 'activity-item'; row.dataset.url = entry.url;
        const body = make('div', '', 'activity-window-body');
        const desk = make('div', '', 'activity-desk');
        desk.setAttribute('aria-hidden', 'true');
        desk.append(document.querySelector('#activity-desk-art').content.cloneNode(true), make('span', '?', 'activity-question-mark'));
        const copy = make('div', '', 'activity-copy');
        copy.append(make('p', '', 'activity-title'), make('p', '', 'activity-detail'));
        body.append(desk, copy);
        const footer = make('div', '', 'activity-footer');
        const mode = make('span', '', 'activity-mode');
        const dots = make('span', '', 'activity-dots');
        dots.setAttribute('aria-hidden', 'true');
        dots.append(make('i'), make('i'), make('i'));
        mode.append(dots, make('span', '', 'activity-mode-label'));
        footer.append(mode, document.createElement('a'));
        row.append(body, footer);
      }
      row.dataset.state = entry.state; row.dataset.signature = rowSignature;
      row.querySelector('.activity-title').textContent = goodmorningT(titles[entry.state]);
      row.querySelector('.activity-detail').textContent = goodmorningT(states[entry.state]);
      row.querySelector('.activity-mode-label').textContent = goodmorningT(modes[entry.mode]);
      const link = row.querySelector('a');
      link.href = entry.url;
      link.textContent = goodmorningT('Open activity');
      link.setAttribute('aria-label', `${goodmorningT('Open activity')}: ${goodmorningT(modes[entry.mode])} · ${goodmorningT(states[entry.state])}`);
      const arrow = make('span', '→'); arrow.setAttribute('aria-hidden', 'true'); link.append(arrow);
      if (!wasHidden) animate(row, [{opacity: created ? 0 : .35}, {opacity: 1}], 240);
      return row;
    });
    [...items.children].filter(row => !rows.includes(row)).forEach(row => row.remove());
    rows.forEach((row, index) => { if (items.children[index] !== row) items.insertBefore(row, items.children[index] || null); });
    if (!wasHidden && !windowBox.hidden) {
      const nextHeight = items.getBoundingClientRect().height;
      if (height !== nextHeight) animate(items, [{height: `${height}px`}, {height: `${nextHeight}px`}], 240);
    }
    panel.dataset.state = activity[0].state;
    const summary = document.querySelector('#activity-summary');
    summary.textContent = goodmorningT(states[activity[0].state]);
    if (!wasHidden && collapsed) animate(summary, [{opacity: .35}, {opacity: 1}], 240);
    restore.setAttribute('aria-label', goodmorningT('Expand ongoing activity') + ': ' + goodmorningT(states[activity[0].state]));
    show(panel, true);
  }
  async function sync() {
    clearTimeout(timer);
    if (document.hidden) return;
    if (fetching) { refreshPending = true; return; }
    fetching = true;
    try {
      const response = await fetch('/api/activity', {credentials: 'same-origin', cache: 'no-store'});
      if ([401, 403].includes(response.status)) { activity = []; render(); return; }
      if (!response.ok) throw new Error('Unavailable');
      const value = await goodmorningJSON(response);
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
    } finally {
      fetching = false;
      if (!document.hidden) timer = setTimeout(sync, refreshPending ? 0 : activity.length ? 1000 : 2000);
      refreshPending = false;
    }
  }
  document.addEventListener('website:language', render);
  document.addEventListener('activity:refresh', sync);
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('focus', sync);
  collapse(collapsed);
  sync();
})();
