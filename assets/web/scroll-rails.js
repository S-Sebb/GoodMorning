// Scoped phone controls enhance native scrolling; no content or position is saved.
(() => {
  const phone = matchMedia('(max-width: 700px)');
  const viewport = window.visualViewport;
  const root = document.documentElement;
  const messages = document.querySelector('#chat-scroll');
  const translate = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  const clamp = (value, maximum) => Math.max(0, Math.min(maximum, value));
  const controls = [];
  let frame;

  function create(scope, target) {
    const rail = document.createElement('div');
    rail.className = `scroll-rail scroll-rail--${scope}`;
    rail.dataset.scrollScope = scope;
    rail.setAttribute('role', 'scrollbar');
    rail.setAttribute('aria-orientation', 'vertical');
    rail.setAttribute('aria-valuemin', '0');
    rail.setAttribute('aria-valuemax', '100');
    rail.setAttribute('aria-controls', target.id);
    const track = document.createElement('span');
    track.className = 'scroll-rail-track';
    const thumb = document.createElement('span');
    thumb.className = 'scroll-rail-thumb';
    const label = document.createElement('span');
    label.className = 'scroll-rail-label';
    track.setAttribute('aria-hidden', 'true');
    thumb.setAttribute('aria-hidden', 'true');
    label.setAttribute('aria-hidden', 'true');
    thumb.append(label);
    rail.append(track, thumb);
    rail.hidden = true;
    document.body.append(rail);
    const control = {scope, target, rail, thumb, label, drag: null, timer: null, travel: 0, maximum: 0};
    controls.push(control);

    function reveal() {
      // Keep the other scope within reach, so readers can switch without an edge swipe.
      for (const current of controls) {
        current.rail.classList.add('is-active');
        clearTimeout(current.timer);
        current.timer = setTimeout(() => { if (!current.drag) current.rail.classList.remove('is-active'); }, 1400);
      }
    }
    function scroll(top) {
      const scroller = scope === 'page' ? window : target;
      scroller.scrollTo({top: clamp(top, control.maximum), behavior: 'instant'});
      reveal();
      schedule();
    }
    function dragTo(y) {
      const position = y - rail.getBoundingClientRect().top - control.drag.offset;
      scroll(control.travel > 0 ? position / control.travel * control.maximum : 0);
    }
    rail.addEventListener('pointerdown', event => {
      if (!event.isPrimary || event.button !== 0 || rail.hidden) return;
      // Keep an open keyboard and the user's draft focus while moving either rail.
      event.preventDefault();
      const box = thumb.getBoundingClientRect();
      control.drag = {id: event.pointerId, offset: thumb.contains(event.target) ? event.clientY - box.top : box.height / 2};
      rail.classList.add('is-dragging');
      rail.setPointerCapture(event.pointerId);
      dragTo(event.clientY);
    });
    rail.addEventListener('pointermove', event => {
      if (control.drag?.id === event.pointerId) dragTo(event.clientY);
    });
    function stop() {
      control.drag = null;
      rail.classList.remove('is-dragging');
      reveal();
    }
    rail.addEventListener('pointerup', stop);
    rail.addEventListener('pointercancel', stop);
    rail.addEventListener('lostpointercapture', stop);
    rail.addEventListener('focus', reveal);
    rail.addEventListener('keydown', event => {
      const visible = scope === 'page' ? root.clientHeight : target.clientHeight;
      const top = scope === 'page' ? scrollY : target.scrollTop;
      const positions = {ArrowUp: top - 40, ArrowDown: top + 40, PageUp: top - visible * .9,
        PageDown: top + visible * .9, Home: 0, End: control.maximum};
      if (!Object.hasOwn(positions, event.key)) return;
      event.preventDefault();
      scroll(positions[event.key]);
    });
    const scroller = scope === 'page' ? window : target;
    scroller.addEventListener('scroll', () => { reveal(); schedule(); }, {passive: true});
  }

  function update() {
    frame = null;
    const height = viewport?.height || innerHeight;
    const top = viewport?.offsetTop || 0;
    const left = viewport?.offsetLeft || 0;
    const width = viewport?.width || innerWidth;
    for (const control of controls) {
      const {scope, target, rail, thumb, label} = control;
      const page = scope === 'page';
      const visible = page ? height : target.clientHeight;
      const content = page ? root.scrollHeight : target.scrollHeight;
      const maximum = Math.max(0, content - (page ? root.clientHeight : visible));
      const inset = Math.min(88, height * .18);
      const box = page ? {top: top + inset, bottom: top + height - inset, right: left + width}
        : target.getBoundingClientRect();
      const railTop = page ? box.top : Math.max(box.top + 10, top + 12);
      const railBottom = page ? box.bottom : Math.min(box.bottom - 10, top + height - 16);
      const length = Math.max(0, railBottom - railTop);
      rail.hidden = !phone.matches || (viewport && viewport.scale !== 1) || maximum <= 1 || length < 56;
      rail.tabIndex = rail.hidden ? -1 : 0;
      control.maximum = maximum;
      if (rail.hidden) continue;
      rail.style.top = `${railTop}px`;
      rail.style.left = `${box.right - 24}px`;
      rail.style.height = `${length}px`;
      const thumbHeight = Math.min(length - 8, Math.max(44, length * visible / content));
      control.travel = length - thumbHeight;
      const fraction = clamp((page ? scrollY : target.scrollTop) / maximum, 1);
      const percent = Math.round(fraction * 100);
      thumb.style.height = `${thumbHeight}px`;
      thumb.style.transform = `translateY(${fraction * control.travel}px)`;
      const name = translate(page ? 'Page' : 'Messages');
      const position = percent === 0 ? translate(page ? 'Top' : 'Start')
        : percent === 100 ? translate(page ? 'Bottom' : 'Latest') : `${percent}%`;
      label.textContent = `${name} · ${position}`;
      rail.setAttribute('aria-label', translate(page ? 'Scroll page' : 'Scroll messages'));
      rail.setAttribute('aria-valuenow', String(percent));
      rail.setAttribute('aria-valuetext', `${name} · ${position}`);
    }
  }
  function schedule() {
    if (!frame) frame = requestAnimationFrame(update);
  }
  function activate() {
    root.classList.toggle('scroll-rails-ready', phone.matches);
    document.dispatchEvent(new Event('scrollrails:layout'));
    schedule();
  }

  document.body.id ||= 'page-scroll-content';
  create('page', document.body);
  if (messages) create('messages', messages);
  phone.addEventListener('change', activate);
  window.addEventListener('resize', schedule);
  viewport?.addEventListener('resize', schedule);
  viewport?.addEventListener('scroll', schedule);
  document.addEventListener('website:language', schedule);
  const observer = 'ResizeObserver' in window ? new ResizeObserver(schedule) : null;
  for (const node of [document.body, messages, document.querySelector('#chat-messages'), document.querySelector('#chat-questions')]) {
    if (node) observer?.observe(node);
  }
  activate();
})();
