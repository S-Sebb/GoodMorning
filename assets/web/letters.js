// The letter wheel: scroll, tap or use arrow keys to read another week's letter in place.
// Without scripts the wheel is a plain list of links.
(() => {
  const list = document.querySelector('.letter-wheel ol');
  if (!list) return;
  const items = [...list.querySelectorAll('a')];
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  const across = () => getComputedStyle(list).flexDirection === 'row';
  let settle = 0, request = 0, frame = 0;

  const middle = item => across() ? item.offsetLeft + item.offsetWidth / 2 : item.offsetTop + item.offsetHeight / 2;
  const view = () => across() ? list.scrollLeft + list.clientWidth / 2 : list.scrollTop + list.clientHeight / 2;
  const nearest = () => items.reduce((best, item) => Math.abs(middle(item) - view()) < Math.abs(middle(best) - view()) ? item : best);

  // Items curve away from the centre like a drum turning.
  function shape() {
    frame = 0;
    const radius = (across() ? list.clientWidth : list.clientHeight) / 2;
    for (const item of items) {
      const offset = Math.max(-1, Math.min(1, (middle(item) - view()) / radius));
      item.style.opacity = String(1 - Math.abs(offset) * .6);
      item.style.transform = still.matches ? '' : `${across() ? 'rotateY' : 'rotateX'}(${(across() ? 1 : -1) * offset * 55}deg) scale(${1 - Math.abs(offset) * .16})`;
    }
  }

  function center(item, smooth) {
    const target = middle(item) - (across() ? list.clientWidth : list.clientHeight) / 2;
    list.scrollTo({[across() ? 'left' : 'top']: target, behavior: smooth && !still.matches ? 'smooth' : 'auto'});
  }

  async function open(item, push) {
    if (item.getAttribute('aria-current') === 'page') return;
    items.forEach(each => each.removeAttribute('aria-current'));
    item.setAttribute('aria-current', 'page');
    const mine = ++request;
    try {
      const response = await fetch(item.href, {credentials: 'same-origin'});
      if (!response.ok) throw new Error('Letter unavailable');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = page.querySelector('.weekly-letter');
      if (mine !== request) return;
      if (!next) throw new Error('Letter unavailable');
      next.classList.add('is-arriving');
      document.querySelector('.weekly-letter').replaceWith(next);
      document.title = page.title;
      if (push) history.pushState(null, '', item.href);
    } catch {
      if (mine === request) location.assign(item.href);
    }
  }

  list.addEventListener('scroll', () => {
    frame ||= requestAnimationFrame(shape);
    clearTimeout(settle);
    settle = setTimeout(() => open(nearest(), true), 260);
  }, {passive: true});
  list.addEventListener('click', event => {
    const item = event.target.closest('a');
    if (!item || event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
    event.preventDefault();
    center(item, true);
    open(item, true);
  });
  list.addEventListener('keydown', event => {
    const step = {ArrowUp: -1, ArrowLeft: -1, ArrowDown: 1, ArrowRight: 1}[event.key];
    const index = items.indexOf(document.activeElement);
    if (!step || index < 0) return;
    event.preventDefault();
    const item = items[Math.max(0, Math.min(items.length - 1, index + step))];
    item.focus({preventScroll: true});
    center(item, true);
    open(item, true);
  });
  addEventListener('popstate', () => {
    const item = items.find(each => new URL(each.href).pathname === location.pathname) || items[0];
    center(item, false);
    open(item, false);
  });
  addEventListener('resize', () => { center(list.querySelector('[aria-current]') || items[0], false); shape(); });

  list.classList.add('is-turning');
  center(list.querySelector('[aria-current]') || items[0], false);
  shape();
})();
