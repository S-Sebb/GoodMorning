// One account-local picker for briefings and chat. No browser storage or agent work.
(() => {
  const t = (key, values = {}) => typeof goodmorningT === 'function' ? goodmorningT(key, values)
    : key.replace(/\{([a-z]+)\}/g, (_, name) => values[name] ?? name);
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  document.querySelectorAll('[data-avatar-options]').forEach((root, index) => {
    const options = JSON.parse(root.dataset.avatarOptions);
    const ids = options.map(item => item.id);
    const sources = Object.fromEntries(options.map(item => [item.id, item.src]));
    const toggle = root.querySelector('[data-avatar-toggle]');
    const menu = root.querySelector('.avatar-menu');
    const image = root.querySelector('.avatar-image');
    const strip = root.querySelector('.avatar-previews');
    const choices = [...root.querySelectorAll('[data-avatar-choice]')];
    const feedback = root.querySelector('.avatar-feedback');
    let saved = root.dataset.avatar;
    let wanted = saved;
    let saving = false;
    let imageRevision = 0;
    let syncRevision = 0;
    let notice = '';
    menu.id = 'avatar-picker-' + index;
    toggle.setAttribute('aria-controls', menu.id);
    toggle.disabled = false;

    function center(behavior = 'smooth') {
      const selected = choices[ids.indexOf(wanted)];
      strip.scrollTo({left: selected.offsetLeft - strip.offsetLeft - (strip.clientWidth - selected.clientWidth) / 2,
        behavior: reduced() ? 'auto' : behavior});
    }

    async function showImage(id) {
      const revision = ++imageRevision;
      if (image.getAttribute('src') === sources[id]) { image.classList.remove('is-changing'); return; }
      const next = new Image();
      next.src = sources[id];
      image.classList.add('is-changing');
      try { await next.decode(); } catch { /* The normal image fallback remains visible. */ }
      if (revision !== imageRevision) return;
      image.src = sources[id];
      image.classList.remove('is-changing');
      if (!reduced()) {
        image.getAnimations().forEach(animation => animation.cancel());
        image.animate([{opacity: .4}, {opacity: 1}], {duration: 220, easing: 'ease-out'});
      }
    }

    function render() {
      root.dataset.avatar = wanted;
      choices.forEach(button => {
        const selected = button.dataset.avatarChoice === wanted;
        button.setAttribute('aria-selected', String(selected));
        button.tabIndex = selected ? 0 : -1;
      });
      feedback.textContent = t(notice || (saving ? 'Saving avatar…' : 'Avatar {current} of {total}'),
        {current: ids.indexOf(wanted) + 1, total: ids.length});
      feedback.classList.toggle('is-error', Boolean(notice));
      root.setAttribute('aria-busy', String(saving));
      showImage(wanted);
      if (!menu.hidden) center();
    }

    function close(returnFocus = false) {
      menu.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      if (returnFocus) toggle.focus({preventScroll: true});
    }

    function open() {
      menu.hidden = false;
      menu.classList.remove('is-above');
      const frame = root.querySelector('.avatar-frame').getBoundingClientRect();
      menu.classList.toggle('is-above', innerHeight - frame.bottom < menu.offsetHeight + 16 && frame.top > menu.offsetHeight + 16);
      toggle.setAttribute('aria-expanded', 'true');
      center('auto');
      choices[ids.indexOf(wanted)].focus({preventScroll: true});
    }

    async function persist() {
      if (saving || saved === wanted) return;
      saving = true;
      render();
      try {
        while (saved !== wanted) {
          const requested = wanted;
          const response = await fetch('/api/avatar', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Briefing-CSRF': csrf},
            body: JSON.stringify({avatar: requested}), credentials: 'same-origin', cache: 'no-store'});
          if (response.status === 401) { location.replace('/login'); throw new Error('Sign-in required'); }
          const result = await response.json();
          if (!response.ok || !ids.includes(result.avatar)) throw new Error('Avatar save failed');
          saved = result.avatar;
          if (wanted === requested) wanted = saved;
        }
      } catch {
        wanted = saved;
        notice = 'Avatar could not be saved. Try again.';
      } finally {
        saving = false;
        render();
      }
    }

    function choose(id) {
      if (!ids.includes(id)) return;
      syncRevision++;
      wanted = id;
      notice = '';
      render();
      persist();
    }

    function step(delta) {
      choose(ids[(ids.indexOf(wanted) + delta + ids.length) % ids.length]);
    }

    async function sync() {
      if (saving || document.hidden) return;
      const revision = syncRevision;
      try {
        const response = await fetch('/api/avatar', {cache: 'no-store', credentials: 'same-origin'});
        if (!response.ok) return;
        const result = await response.json();
        if (revision !== syncRevision || saving || !ids.includes(result.avatar)) return;
        saved = wanted = result.avatar;
        render();
      } catch { /* Keep the visible avatar during an outage. */ }
    }

    toggle.addEventListener('click', () => menu.hidden ? open() : close());
    root.querySelector('[data-avatar-prev]').addEventListener('click', () => step(-1));
    root.querySelector('[data-avatar-next]').addEventListener('click', () => step(1));
    choices.forEach(button => button.addEventListener('click', () => choose(button.dataset.avatarChoice)));
    menu.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(true); }
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || !event.target.matches('[data-avatar-choice]')) return;
      event.preventDefault();
      if (event.key === 'Home' || event.key === 'End') choose(ids[event.key === 'Home' ? 0 : ids.length - 1]);
      else step(event.key === 'ArrowRight' ? 1 : -1);
      choices[ids.indexOf(wanted)].focus({preventScroll: true});
    });
    document.addEventListener('pointerdown', event => { if (!root.contains(event.target)) close(); });
    root.addEventListener('focusout', event => { if (event.relatedTarget && !root.contains(event.relatedTarget)) close(); });
    document.addEventListener('website:language', render);
    document.addEventListener('website:before-refresh', event => { if (saving) event.preventDefault(); });
    document.addEventListener('secretary:avatar', () => { if (!saving) sync(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) sync(); });
    window.addEventListener('focus', sync);
    render();
  });
})();
