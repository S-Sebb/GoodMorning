// Quiet secretary-calls list. Same-tab navigation only; no popups or sounds.
(() => {
  const panel = document.querySelector('#secretary-calls');
  if (!panel) return;
  const list = document.querySelector('#calls-list');
  const status = document.querySelector('#calls-status');
  const review = document.querySelector('#calls-review');
  const config = JSON.parse(document.querySelector('#chat-config').dataset.config);
  const kinds = {task_wording: 'Wording', ambiguous_schedule: 'Scheduling', tbc_time: 'Time to confirm', calendar_review: 'Calendar review'};
  let loading = false;

  async function api(path, body) {
    const response = await fetch(path, {method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
      headers: body ? {'Content-Type': 'application/json', 'X-Briefing-CSRF': config.csrf} : {}});
    const result = await goodmorningJSON(response);
    if (!response.ok) throw new Error(result.error || goodmorningT('Calls could not be loaded. Your records are unchanged.'));
    return result;
  }

  function setStatus(text) { status.textContent = text ? goodmorningT(text) : ''; }

  function card(item, candidate) {
    const node = document.createElement('li');
    node.className = 'call-card';
    node.dataset.status = item.status || 'candidate';
    const kind = document.createElement('span');
    kind.className = 'call-kind';
    kind.textContent = goodmorningT(kinds[item.kind] || item.kind);
    const title = document.createElement('p');
    title.className = 'call-title';
    title.textContent = item.title;
    title.setAttribute('data-content', '');
    const reason = document.createElement('p');
    reason.className = 'call-reason';
    reason.textContent = item.reason;
    const actions = document.createElement('div');
    actions.className = 'call-actions';
    const arm = (button, armedLabel, run) => {
      button.addEventListener('click', async () => {
        if (!button.dataset.armed) {
          button.dataset.armed = '1';
          button.classList.add('is-armed');
          button.textContent = goodmorningT(armedLabel);
          return;
        }
        await run(button);
      });
    };
    if (candidate) {
      const add = document.createElement('button');
      add.type = 'button';
      add.textContent = goodmorningT('Add call');
      add.addEventListener('click', async () => {
        add.disabled = true;
        try {
          await api('/api/calls', {item: candidate});
          setStatus('');
          await load();
        } catch { setStatus('Calls could not be saved. Your records are unchanged.'); }
        finally { add.disabled = false; }
      });
      actions.append(add);
    } else {
      if (item.status === 'open') {
        const ask = document.createElement('button');
        ask.type = 'button';
        ask.textContent = goodmorningT('Ask in secretary chat');
        ask.addEventListener('click', async () => {
          ask.disabled = true;
          try {
            const receipt = await api(`/api/calls/${item.id}/ask`, {});
            location.href = `/chat?id=${receipt.chat}`;
          } catch { setStatus('Calls could not be saved. Your records are unchanged.'); }
          finally { ask.disabled = false; }
        });
        const resolve = document.createElement('button');
        resolve.type = 'button';
        resolve.textContent = goodmorningT('Resolve');
        arm(resolve, 'Confirm resolved', async button => {
          button.disabled = true;
          try {
            await api(`/api/calls/${item.id}/resolve`, {});
            setStatus('');
            await load();
          } catch { setStatus('Calls could not be saved. Your records are unchanged.'); }
          finally { button.disabled = false; delete button.dataset.armed; button.classList.remove('is-armed'); button.textContent = goodmorningT('Resolve'); }
        });
        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.textContent = goodmorningT('Dismiss call');
        arm(dismiss, 'Confirm dismiss', async button => {
          button.disabled = true;
          try {
            await api(`/api/calls/${item.id}/dismiss`, {});
            setStatus('');
            await load();
          } catch { setStatus('Calls could not be saved. Your records are unchanged.'); }
          finally { button.disabled = false; delete button.dataset.armed; button.classList.remove('is-armed'); button.textContent = goodmorningT('Dismiss call'); }
        });
        actions.append(ask, resolve, dismiss);
      }
    }
    node.append(kind, title, reason, actions);
    return node;
  }

  async function load() {
    try {
      const result = await api('/api/calls');
      list.replaceChildren(...result.calls.map(item => card(item, false)));
      const open = result.calls.filter(item => item.status === 'open').length;
      review.disabled = false;
      return open;
    } catch {
      setStatus('Calls could not be loaded. Your records are unchanged.');
      return 0;
    }
  }

  review.addEventListener('click', async () => {
    if (loading) return;
    loading = true;
    review.disabled = true;
    setStatus('');
    try {
      const result = await api('/api/calls/scan');
      if (!result.candidates.length) {
        setStatus('No calls waiting');
        await load();
        return;
      }
      list.replaceChildren(...result.candidates.map(item => card(item, true)));
    } catch {
      setStatus('Calls could not be loaded. Your records are unchanged.');
    } finally {
      loading = false;
      review.disabled = false;
    }
  });

  document.addEventListener('website:language', () => { load(); });
  load();
})();
