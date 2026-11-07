// Progressive enhancement: native anchors and all content work without JavaScript.
let sections = [];
const progress = document.querySelector('.reading-progress');
const touch = window.matchMedia('(pointer: coarse)');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const hero = document.querySelector('.hero');
const backTop = document.querySelector('.back-to-top');
const sectionButton = document.querySelector('#mobile-sections');
const sectionDialog = document.querySelector('#mobile-section-dialog');
const sectionList = document.querySelector('#mobile-section-list');
const mobile = matchMedia('(max-width: 700px)');
// Han characters set about twice as wide as Latin ones.
document.querySelectorAll('.hero-copy h1').forEach(title => {
  const length = [...title.textContent.trim()].reduce((sum, char) => sum + (char.codePointAt(0) >= 0x2E80 ? 2 : 1), 0);
  title.style.setProperty('--title-length', length);
});
if (sectionButton) {
  sectionButton.addEventListener('click', () => {
    sectionDialog.showModal();
    document.documentElement.classList.add('section-picker-open');
    sectionButton.setAttribute('aria-expanded', 'true');
    sectionList.querySelector('[aria-current]')?.focus();
  });
  document.querySelector('#close-sections').addEventListener('click', () => sectionDialog.close());
  sectionDialog.addEventListener('close', () => {
    if (sectionDialog.open) return;
    document.documentElement.classList.remove('section-picker-open');
    sectionButton.setAttribute('aria-expanded', 'false');
  });
  sectionDialog.addEventListener('click', event => {
    const rect = sectionDialog.getBoundingClientRect();
    if (event.target === sectionDialog && (event.clientX < rect.left || event.clientX > rect.right
      || event.clientY < rect.top || event.clientY > rect.bottom)) sectionDialog.close();
  });
  // Phones have no floating Back to top button; the picker offers it instead.
  document.querySelector('#sections-top').addEventListener('click', () => sectionDialog.close());
  sectionList.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link) return;
    sectionDialog.close();
    const target = document.querySelector(link.getAttribute('href'));
    target.tabIndex = -1;
    requestAnimationFrame(() => target.focus({preventScroll: true}));
  });
  mobile.addEventListener('change', () => { if (!mobile.matches && sectionDialog.open) sectionDialog.close(); });
}
backTop.hidden = false;
let scheduled = false;
let positions = [];
let heroVisible = true;
let maxScroll = 0;
let viewportHeight = innerHeight;
let previousCurrent = -1;
let topVisible = false;
let previousDrift = -1;

function measureSections() {
  if (!sections.length) return;
  maxScroll = document.documentElement.scrollHeight - innerHeight;
  viewportHeight = innerHeight;
  positions = sections.map(section => ({ top: section.offsetTop, height: section.offsetHeight }));
  // Center in the actual content gutter, including wide screens and safe areas.
  const contentRight = sections[0].getBoundingClientRect().right;
  const safeRight = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--safe-right')) || 0;
  backTop.style.setProperty('--gutter-right', `${safeRight + (document.documentElement.clientWidth - safeRight - contentRight - backTop.offsetWidth) / 2}px`);
  previousCurrent = -1;
  updateReading();
}

function updateReading() {
  if (!sections.length || !positions.length) return;
  const y = window.scrollY;
  const max = maxScroll;
  progress.style.transform = `scaleX(${max > 0 ? Math.max(0, Math.min(1, y / max)) : 0})`;
  const readingLine = y + Math.min(viewportHeight * .3, 180);
  let current = 0;
  positions.forEach((position, index) => {
    if (position.top <= readingLine) current = index;
  });
  const atEnd = max <= 0 || window.scrollY >= max - 2;
  if (atEnd) current = positions.length - 1;
  const inlineNav = document.querySelector('.briefing-section-nav');
  const inlineLinks = inlineNav ? Array.from(inlineNav.children) : [];
  if (current !== previousCurrent) {
    const mark = (node, active) => {
      if (!node) return;
      node.classList.toggle('active', active);
      if (active) node.setAttribute('aria-current', 'location');
      else node.removeAttribute('aria-current');
    };
    sections.forEach((section, index) => {
      const active = index === current;
      section.classList.toggle('is-current', active);
      mark(inlineLinks[index], active);
      mark(sectionList?.children[index], active);
    });
  }
  previousCurrent = current;
  const showBackTop = y > Math.min(viewportHeight * .45, 320);
  if (showBackTop !== topVisible) {
    backTop.classList.toggle('is-visible', showBackTop);
    backTop.setAttribute('aria-hidden', String(!showBackTop));
    topVisible = showBackTop;
  }
  if (!showBackTop && document.activeElement === backTop) {
    document.querySelector('.wordmark').focus({ preventScroll: true });
  }
  // A bounded decorative drift, only on pointer devices while the hero is visible.
  if (heroVisible || reducedMotion.matches) {
    const drift = reducedMotion.matches || touch.matches ? 0 : Math.min(Math.max(0, window.scrollY), 380) * .025;
    if (drift !== previousDrift) {
      hero.style.setProperty('--sun-drift', `${drift}px`);
      previousDrift = drift;
    }
  }
  scheduled = false;
}
function scheduleReading() {
  if (!scheduled) { scheduled = true; requestAnimationFrame(updateReading); }
}
window.addEventListener('scroll', scheduleReading, { passive: true });
window.addEventListener('resize', measureSections);
reducedMotion.addEventListener('change', updateReading);
const resizeObserver = 'ResizeObserver' in window ? new ResizeObserver(measureSections) : null;
let entryObserver;
const observedFrames = new WeakSet();
if ('IntersectionObserver' in window) {
  const heroObserver = new IntersectionObserver(entries => {
    heroVisible = entries[0].isIntersecting;
    updateReading();
  });
  heroObserver.observe(hero);
  // Each section fades in once; replaying the fade on every re-entry repainted sections while scrolling back.
  entryObserver = new IntersectionObserver(entries => {
    for (const entry of entries.filter(entry => entry.isIntersecting)) {
      entry.target.firstElementChild.classList.add('arriving');
      entryObserver.unobserve(entry.target);
    }
  }, { rootMargin: '0px 0px -8% 0px' });
}
function refreshBriefing() {
  const previousSections = sections;
  // Each weather headline's one-line width in em, so briefing.css can shrink a long one to its tile.
  // A language switch changes the text, so this reruns.
  document.querySelectorAll('.weather-main').forEach(value => {
    value.style.width = 'max-content';
    value.style.setProperty('--value-ems', value.getBoundingClientRect().width / parseFloat(getComputedStyle(value).fontSize));
    value.style.width = '';
  });
  sections = Array.from(document.querySelectorAll('.briefing-section:not([hidden])'));
  const inlineNav = document.querySelector('.briefing-section-nav');
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  if (inlineNav) inlineNav.replaceChildren(...sections.map(section => {
    const link = document.createElement('a');
    const heading = section.querySelector('h2');
    link.href = '#' + section.id;
    const layout = (section.className.match(/briefing-section\s+(\S+)/) || [])[1] || 'notes';
    link.dataset.layout = layout;
    const symbol = section.querySelector('.section-symbol svg');
    if (symbol) link.appendChild(symbol.cloneNode(true));
    const dateBadge = heading.querySelector('[data-date]');
    const iso = dateBadge?.dataset.date;
    // Base title without date badges or screen-reader-only suffixes.
    const clean = heading.cloneNode(true);
    clean.querySelectorAll('.section-date,.preview-date,.nav-date,.visually-hidden').forEach(node => node.remove());
    const base = clean.textContent.trim();
    const uiLabel = heading.querySelector('[data-ui-text]');
    const labelSpan = document.createElement('span');
    labelSpan.className = 'nav-label';
    if (iso) {
      labelSpan.textContent = base;
      if (uiLabel) labelSpan.dataset.uiText = uiLabel.dataset.uiText;
      else labelSpan.dataset.content = '';
      link.appendChild(labelSpan);
      const parts = iso.split('-').map(Number);
      const dateSpan = document.createElement('span');
      dateSpan.className = 'nav-date';
      dateSpan.textContent = '· ' + months[parts[1] - 1] + ' ' + parts[2];
      dateSpan.dataset.date = iso;
      dateSpan.dataset.content = '';
      link.appendChild(document.createTextNode(' '));
      link.appendChild(dateSpan);
      link.setAttribute('aria-label', base + ' — ' + iso);
    } else {
      const full = heading.textContent.trim();
      const dated = full.match(/^(.*)\s+—\s+(\d{4}-\d{2}-\d{2})$/);
      if (dated) {
        labelSpan.textContent = dated[1].trim();
        if (uiLabel) labelSpan.dataset.uiText = uiLabel.dataset.uiText;
        else labelSpan.dataset.content = '';
        link.appendChild(labelSpan);
        const parts = dated[2].split('-').map(Number);
        const dateSpan = document.createElement('span');
        dateSpan.className = 'nav-date';
        dateSpan.textContent = '· ' + months[parts[1] - 1] + ' ' + parts[2];
        dateSpan.dataset.date = dated[2];
        dateSpan.dataset.content = '';
        link.appendChild(document.createTextNode(' '));
        link.appendChild(dateSpan);
        link.setAttribute('aria-label', full);
      } else {
        labelSpan.textContent = base || full;
        if (uiLabel) labelSpan.dataset.uiText = uiLabel.dataset.uiText;
        else labelSpan.dataset.content = '';
        link.appendChild(labelSpan);
        if (!uiLabel) link.dataset.content = '';
      }
    }
    return link;
  }));
  if (sectionList && inlineNav) {
    sectionList.replaceChildren(...Array.from(inlineNav.children, link => link.cloneNode(true)));
    sectionButton.hidden = !sections.length;
    if (!sections.length && sectionDialog.open) sectionDialog.close();
  }
  resizeObserver?.disconnect();
  const questions = document.querySelector('#agent-questions');
  if (questions) resizeObserver?.observe(questions);
  previousSections.filter(section => !sections.includes(section)).forEach(section => entryObserver?.unobserve(section.parentElement));
  sections.forEach(section => {
    resizeObserver?.observe(section);
    let frame = section.parentElement;
    if (!frame.classList.contains('section-entry')) {
      frame = document.createElement('div');
      frame.className = 'section-entry';
      section.before(frame); frame.append(section);
    }
    if (!observedFrames.has(frame)) {
      entryObserver?.observe(frame);
      observedFrames.add(frame);
    }
  });
  measureSections();
}
document.addEventListener('briefing:updated', refreshBriefing);
document.addEventListener('website:language', refreshBriefing);
if (document.fonts) document.fonts.ready.then(measureSections);
refreshBriefing();
// The app's News widget opens ?section=news: start at that kind of section, as its own anchor would.
const asked = new URLSearchParams(location.search).get('section');
if (asked) {
  const start = sections.find(section => section.classList.contains(asked));
  history.replaceState(history.state, '', location.pathname + (start ? '#' + start.id : ''));
  start?.scrollIntoView({behavior: 'instant'});
}
const days = document.querySelector('.briefing-letter .week-picker');
if (days && innerWidth <= 700) days.scrollLeft = days.scrollWidth;
// An offline copy (sw.js) names its date unless its edition is the account's current day, which ends at
// 04:00 in the account's timezone (briefing_day.py), wherever this device and its clock happen to be.
const offlineNotice = document.querySelector('.offline-notice');
if (offlineNotice) {
  const now = Object.fromEntries(new Intl.DateTimeFormat('en', {timeZone: offlineNotice.dataset.zone, year: 'numeric',
    month: 'numeric', day: 'numeric', hour: 'numeric', hourCycle: 'h23'}).formatToParts(new Date()).map(part => [part.type, Number(part.value)]));
  const today = new Date(Date.UTC(now.year, now.month - 1, now.day - (now.hour < 4))).toISOString().slice(0, 10);
  const shown = ('unreachable' in offlineNotice.dataset ? 'unreachable' : 'offline') + (offlineNotice.dataset.day === today ? '-today' : '-earlier');
  for (const line of offlineNotice.querySelectorAll('span')) line.hidden = line.className !== shown;
}
