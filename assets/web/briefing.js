// Progressive enhancement: native anchors and all content work without JavaScript.
let sections = [];
let links = [];
const progress = document.querySelector('.reading-progress');
const touch = window.matchMedia('(pointer: coarse)');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const map = document.querySelector('.scroll-map');
const track = document.querySelector('.scroll-track');
const cursor = document.querySelector('.scroll-cursor');
const hero = document.querySelector('.hero');
const backTop = document.querySelector('.back-to-top');
const sectionButton = document.querySelector('#mobile-sections');
const sectionDialog = document.querySelector('#mobile-section-dialog');
const sectionList = document.querySelector('#mobile-section-list');
const mobile = matchMedia('(max-width: 700px)');
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
let cursorPositions = [];
let measuredTrackScroll = 0;
let lastCurrent = null;
let heroVisible = true;
let keyboardFocus = true;
let maxScroll = 0;
let viewportHeight = innerHeight;
let previousCurrent = -1;
let fills = [];
let topVisible = false;
let previousDrift = -1;
let previousCursorTop = -1;
let trackHeight = 0;

function dismissPreviews() {
  for (const link of links) {
    link.parentElement.classList.remove('preview-open', 'keyboard-preview');
    link.parentElement.classList.add('preview-dismissed');
    link.removeAttribute('aria-expanded');
  }
}

const boundLinks = new WeakSet();
function bindLinks() {
  for (const link of links) {
    if (boundLinks.has(link)) continue;
    boundLinks.add(link);
    const segment = link.parentElement;
    link.addEventListener('focus', () => {
      segment.classList.remove('preview-dismissed');
      if (keyboardFocus) segment.classList.add('keyboard-preview');
    });
    link.addEventListener('blur', () => segment.classList.remove('keyboard-preview'));
    segment.addEventListener('pointerenter', () => segment.classList.remove('preview-dismissed'));
    segment.querySelector('.nav-preview').addEventListener('click', () => link.click());
    link.addEventListener('click', event => {
      // Keyboard activation remains a single action, including on touch laptops.
      if (touch.matches && event.detail > 0 && !segment.classList.contains('preview-open')) {
        event.preventDefault();
        dismissPreviews();
        segment.classList.remove('preview-dismissed');
        segment.classList.add('preview-open');
        link.setAttribute('aria-expanded', 'true');
        return;
      }
      dismissPreviews();
    });
  }
}
document.addEventListener('pointerdown', event => {
  keyboardFocus = false;
  if (!event.target.closest('.scroll-map')) dismissPreviews();
});
document.addEventListener('keydown', event => {
  keyboardFocus = true;
  if (event.key === 'Escape') dismissPreviews();
});

function measureSections() {
  if (!sections.length) return;
  maxScroll = document.documentElement.scrollHeight - innerHeight;
  viewportHeight = innerHeight;
  positions = sections.map(section => ({ top: section.offsetTop, height: section.offsetHeight }));
  // Center in the actual content gutter, including wide screens and safe areas.
  const contentRight = sections[0].getBoundingClientRect().right;
  const safeRight = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--safe-right')) || 0;
  backTop.style.right = `${safeRight + (document.documentElement.clientWidth - safeRight - contentRight - backTop.offsetWidth) / 2}px`;
  positions.forEach((position, index) => {
    // Segment length reflects the section's share of the document.
    links[index].parentElement.style.flexGrow = String(position.height);
  });
  const mapTop = map.getBoundingClientRect().top;
  cursorPositions = links.map(link => {
    const bar = link.querySelector('.chunk-bar').getBoundingClientRect();
    return { top: bar.top - mapTop, height: bar.height };
  });
  measuredTrackScroll = track.scrollTop;
  trackHeight = track.clientHeight;
  lastCurrent = null;
  previousCurrent = -1;
  updateReading();
  map.classList.add('is-ready');
}

function updateReading() {
  if (!sections.length || !positions.length) return;
  const y = window.scrollY;
  const trackScroll = track.scrollTop;
  const max = maxScroll;
  progress.style.transform = `scaleX(${max > 0 ? Math.max(0, Math.min(1, y / max)) : 0})`;
  const readingLine = y + Math.min(viewportHeight * .3, 180);
  let current = 0;
  positions.forEach((position, index) => {
    if (position.top <= readingLine) current = index;
  });
  const atEnd = max <= 0 || window.scrollY >= max - 2;
  if (atEnd) current = positions.length - 1;
  links.forEach((link, index) => {
    const position = positions[index];
    // End-of-page selection must agree with the fills, even when the last
    // sections are shorter than the viewport and cannot reach the reading line.
    const fraction = atEnd || index < current ? 1 : index > current ? 0
      : Math.max(0, Math.min(1, (readingLine - position.top) / position.height));
    if (fraction !== fills[index]) {
      link.style.setProperty('--section-progress', String(fraction));
      fills[index] = fraction;
    }
    const active = index === current;
    if (current !== previousCurrent) {
      link.classList.toggle('active', active);
      sections[index].classList.toggle('is-current', active);
      if (active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
      const item = sectionList?.children[index];
      if (item) {
        if (active) item.setAttribute('aria-current', 'location');
        else item.removeAttribute('aria-current');
      }
    }
  });
  let cursorTop = cursorPositions[current].top - (trackScroll - measuredTrackScroll);
  if (current !== lastCurrent) {
    const bottom = cursorTop + cursorPositions[current].height;
    if (cursorTop < 0) track.scrollTop += cursorTop;
    else if (bottom > trackHeight) track.scrollTop += bottom - trackHeight;
    cursorTop = cursorPositions[current].top - (track.scrollTop - measuredTrackScroll);
    lastCurrent = current;
  }
  if (cursorTop !== previousCursorTop) {
    cursor.style.transform = `translateY(${cursorTop}px)`;
    previousCursorTop = cursorTop;
  }
  if (current !== previousCurrent) cursor.style.height = `${cursorPositions[current].height}px`;
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
track.addEventListener('scroll', scheduleReading, { passive: true });
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
  entryObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      entry.target.firstElementChild.classList.toggle('arriving', entry.isIntersecting);
    }
  }, { rootMargin: '0px 0px -8% 0px' });
}
function refreshBriefing() {
  const previousSections = sections;
  sections = Array.from(document.querySelectorAll('.briefing-section:not([hidden])'));
  const visibleIds = new Set(sections.map(section => '#' + section.id));
  links = Array.from(document.querySelectorAll('.scroll-segment:not([hidden]) .scroll-chunk')).filter(link => visibleIds.has(link.hash));
  const inlineNav = document.querySelector('.briefing-section-nav');
  if (inlineNav) inlineNav.replaceChildren(...sections.map(section => {
    const link = document.createElement('a');
    const heading = section.querySelector('h2');
    link.href = '#' + section.id;
    link.textContent = heading.textContent;
    const label = heading.querySelector('[data-ui-text]');
    if (label) link.dataset.uiText = label.dataset.uiText;
    else link.dataset.content = '';
    return link;
  }));
  fills = links.map(() => -1);
  if (sectionList && inlineNav) {
    sectionList.replaceChildren(...Array.from(inlineNav.children, link => link.cloneNode(true)));
    sectionButton.hidden = !sections.length;
    if (!sections.length && sectionDialog.open) sectionDialog.close();
  }
  map.hidden = !sections.length;
  bindLinks();
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
const days = document.querySelector('.briefing-letter .week-picker');
if (days && innerWidth <= 700) days.scrollLeft = days.scrollWidth;
