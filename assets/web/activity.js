// Each tab uses its own host-only login. Only the server shares account activity.
(() => {
  const panel = document.querySelector('#account-activity');
  if (!panel) return;
  const items = document.querySelector('#activity-items');
  const origins = JSON.parse(panel.dataset.origins);
  const modes = {secretary: 'Secretary', initialize: 'Initialize', todo: 'To-do', eureka: 'Eureka', gm: 'Morning briefing', gn: 'Evening briefing'};
  const states = {working: 'Your secretary is working', waiting: 'Your secretary needs your answer', queued: 'Your request is queued.',
    uncertain: 'Activity needs checking. Open it before trying again.', unavailable: 'Activity status is unavailable. Open it to check.'};
  let activity = [], fetching = false, signature = '';
  function render() {
    const next = JSON.stringify([activity, goodmorningT('Ongoing activity')]);
    if (signature === next) return;
    signature = next;
    const heading = goodmorningT('Ongoing activity');
    document.querySelector('#activity-heading').textContent = heading;
    panel.setAttribute('aria-label', heading);
    items.replaceChildren(...activity.map(entry => {
      const row = document.createElement('div');
      row.className = 'activity-item'; row.dataset.state = entry.state;
      const text = document.createElement('span');
      text.textContent = `${goodmorningT(modes[entry.mode])} · ${goodmorningT(states[entry.state])}`;
      const link = document.createElement('a');
      link.href = entry.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = goodmorningT('Open activity');
      link.setAttribute('aria-label', `${goodmorningT('Open activity')}: ${text.textContent}`);
      row.append(text, link); return row;
    }));
    panel.hidden = !activity.length;
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
