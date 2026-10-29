// The account's secretary avatar: picked in the Account menu, shown by every portrait on the page.
// No browser storage or agent work.
(() => {
  const t = (key, values = {}) => typeof goodmorningT === 'function' ? goodmorningT(key, values)
    : key.replace(/\{([a-z]+)\}/g, (_, name) => values[name] ?? name);
  const csrf = JSON.parse(document.querySelector('#language-config').dataset.config).csrf;
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const picker = document.querySelector('#avatar-settings');
  const displays = [...document.querySelectorAll('.avatar-display')];
  if (!picker && !displays.length) return;

  const first = displays[0];
  let sources = Object.fromEntries((first ? JSON.parse(first.dataset.avatarOptions) : []).map(item => [item.id, item]));
  let ids = Object.keys(sources);
  let saved = first ? first.dataset.avatar : null;
  let wanted = saved;
  let saving = false;
  let uploading = false;
  let syncRevision = 0;
  let notice = '';
  let uploadVariant = 'night';
  // Evening pages and night-time desks show the lamp-lit scene; everything else shows daylight.
  const variant = () => document.documentElement.dataset.edition === 'gn' ? 'night' : 'day';
  const scene = id => sources[id][variant()];
  // Built-in avatars also have a gently animated scene; the <source> shows it unless motion is reduced.
  const moving = id => sources[id][variant() + 'Animated'] || '';

  function updateOptions(items) {
    if (!Array.isArray(items)) return;
    const valid = value => /^\/api\/avatar\/image\/[a-f0-9]{64}\.png$/.test(value);
    const usable = items.filter(item => item.id !== 'custom' ? typeof item.day === 'string' && typeof item.night === 'string'
      : valid(item.day) && valid(item.night) && (item.profile === null || valid(item.profile)));
    if (!usable.length) return;
    sources = Object.fromEntries(usable.map(item => [item.id, item]));
    ids = Object.keys(sources);
  }

  const revisions = new WeakMap();
  async function showImage(root, id) {
    const image = root.querySelector('.avatar-image');
    const profile = root.querySelector('.avatar-profile');
    let motion = image.parentElement.querySelector('source');
    if (!motion) {
      motion = document.createElement('source');
      motion.media = '(prefers-reduced-motion: no-preference)';
      image.before(motion);
    }
    const revision = (revisions.get(root) || 0) + 1;
    revisions.set(root, revision);
    root.dataset.avatar = id;
    root.dataset.profile = sources[id].profile || '';
    profile.src = sources[id].profile || scene(id);
    if (image.getAttribute('src') === scene(id) && (motion.getAttribute('srcset') || '') === moving(id)) {
      image.classList.remove('is-changing');
      return;
    }
    const next = new Image();
    next.src = moving(id) && !reduced() ? moving(id) : scene(id);
    image.classList.add('is-changing');
    try { await next.decode(); } catch { /* The normal image fallback remains visible. */ }
    if (revision !== revisions.get(root)) return;
    if (moving(id)) motion.srcset = moving(id);
    else motion.removeAttribute('srcset');
    image.src = scene(id);
    image.classList.remove('is-changing');
    if (!reduced()) {
      image.getAnimations().forEach(animation => animation.cancel());
      image.animate([{opacity: .4}, {opacity: 1}], {duration: 220, easing: 'ease-out'});
    }
  }

  const strip = picker && picker.querySelector('.avatar-previews');
  const feedback = picker && picker.querySelector('.avatar-feedback');
  const uploads = picker ? [...picker.querySelectorAll('[data-avatar-upload]')] : [];
  const fileInput = picker && picker.querySelector('[data-avatar-file]');

  function choices() {
    // Rebuilt only when the set of avatars changes, so keyboard focus stays put.
    if (strip.dataset.ids !== ids.join()) {
      strip.dataset.ids = ids.join();
      strip.replaceChildren(...ids.map(id => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'avatar-preview';
        button.setAttribute('role', 'option');
        button.dataset.avatarChoice = id;
        const preview = document.createElement('img');
        preview.alt = '';
        preview.width = preview.height = 72;
        preview.loading = 'lazy';
        button.append(preview);
        button.addEventListener('click', () => choose(id));
        return button;
      }));
    }
    return [...strip.children];
  }

  function render() {
    if (!wanted || !sources[wanted]) return;
    displays.forEach(root => showImage(root, wanted));
    if (!picker) return;
    choices().forEach((button, index) => {
      const id = button.dataset.avatarChoice;
      const selected = id === wanted;
      button.setAttribute('aria-selected', String(selected));
      button.setAttribute('aria-label', t('Avatar {number}', {number: index + 1}));
      button.tabIndex = selected ? 0 : -1;
      button.disabled = uploading;
      const preview = button.querySelector('img');
      if (preview.getAttribute('src') !== scene(id)) preview.src = scene(id);
    });
    uploads.forEach(button => { button.disabled = saving || uploading; });
    feedback.textContent = notice ? t(notice) : uploading ? t('Uploading avatar…') : saving ? t('Saving avatar…') : '';
    feedback.classList.toggle('is-error', Boolean(notice));
    picker.setAttribute('aria-busy', String(saving || uploading));
    picker.hidden = false;
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
        const result = await goodmorningJSON(response);
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
    if (uploading || !ids.includes(id)) return;
    syncRevision++;
    wanted = id;
    notice = '';
    render();
    persist();
  }

  async function sync() {
    if (saving || uploading || document.hidden) return;
    const revision = syncRevision;
    try {
      const response = await fetch('/api/avatar', {cache: 'no-store', credentials: 'same-origin'});
      if (!response.ok) return;
      const result = await goodmorningJSON(response);
      if (revision !== syncRevision || saving || uploading) return;
      updateOptions(result.avatars);
      if (!ids.includes(result.avatar)) return;
      saved = wanted = result.avatar;
      render();
    } catch { /* Keep the visible avatar during an outage. */ }
  }

  if (picker) {
    uploads.forEach(button => button.addEventListener('click', () => { uploadVariant = button.dataset.avatarUpload; fileInput.click(); }));
    fileInput.addEventListener('change', async () => {
      const file = fileInput.files[0];
      fileInput.value = '';
      if (!file || saving || uploading) return;
      if (!file.size || file.size > 5 * 1024 * 1024) {
        notice = 'Avatar images must be 5 MB or smaller.';
        render();
        return;
      }
      syncRevision++;
      uploading = true;
      notice = '';
      render();
      try {
        const response = await fetch('/api/avatar/upload/' + uploadVariant, {method: 'POST',
          headers: {'Content-Type': 'application/octet-stream', 'X-Briefing-CSRF': csrf},
          body: file, credentials: 'same-origin', cache: 'no-store'});
        if (response.status === 401) { location.replace('/login'); throw new Error('Sign-in required'); }
        const result = await goodmorningJSON(response);
        if (!response.ok || result.avatar !== 'custom') throw new Error('Avatar upload failed');
        updateOptions(result.avatars);
        if (!ids.includes('custom')) throw new Error('Avatar upload failed');
        saved = wanted = 'custom';
        document.dispatchEvent(new Event('secretary:avatar'));
      } catch {
        notice = 'Avatar could not be uploaded. Use a PNG, JPEG or WebP image up to 5 MB.';
      } finally {
        uploading = false;
        render();
      }
    });
    strip.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || !event.target.matches('[data-avatar-choice]')) return;
      event.preventDefault();
      const index = ids.indexOf(wanted);
      choose(ids[event.key === 'Home' ? 0 : event.key === 'End' ? ids.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + ids.length) % ids.length]);
      strip.children[ids.indexOf(wanted)].focus({preventScroll: true});
    });
    document.addEventListener('website:before-refresh', event => { if (saving || uploading) event.preventDefault(); });
  }
  document.addEventListener('website:language', render);
  new MutationObserver(render).observe(document.documentElement, {attributes: true, attributeFilter: ['data-edition']});
  document.addEventListener('secretary:avatar', () => { if (!saving) sync(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) sync(); });
  window.addEventListener('focus', sync);
  // Pages without a portrait learn the avatars from the server before the picker appears.
  if (picker) sync();
  render();
})();
