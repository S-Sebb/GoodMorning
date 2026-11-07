// The page bar's highlight slides from the page just left to the one clicked.
// Each page is a full load, so a click remembers which link was highlighted and
// the next page slides a copy of the highlight from there. This script runs
// right after the bar, before the page paints, so the highlight never shows at
// its destination first. Direct visits, reloads and reduced motion never slide.
(() => {
  const bar = document.currentScript.previousElementSibling;
  const key = 'goodmorning-page-bar-slide';
  const links = [...bar.querySelectorAll('a.edition-link')];
  bar.addEventListener('click', event => {
    const link = event.target.closest('a.edition-link'), from = bar.querySelector('a.edition-link.selected');
    if (!link || !from || link === from || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    sessionStorage.setItem(key, JSON.stringify({from: links.indexOf(from), to: links.indexOf(link), at: Date.now()}));
  });

  const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
  sessionStorage.removeItem(key);
  const from = links[saved?.from], to = links[saved?.to];
  // A click that never led here (a cancelled or slow navigation) is stale after a few seconds.
  if (!from || !to?.classList.contains('selected') || Date.now() - saved.at > 10000
      || matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  // The moving highlight is a decorative selected key over the bar, styled by the theme's own
  // selected rules. Inside it, copies of every label in the selected text colour show through
  // only where it is, so it looks like the selected key itself gliding across.
  const selected = getComputedStyle(to);
  const span = className => Object.assign(document.createElement('span'), {className});
  const pill = span('edition-link selected page-bar-pill'), clip = span('page-bar-labels'), track = span('page-bar-track');
  const copies = links.map(link => {
    const copy = span('edition-link page-bar-copy');
    copy.innerHTML = link.innerHTML;
    Object.assign(copy.style, {color: selected.color, textShadow: selected.textShadow, background: 'none', boxShadow: 'none'});
    copy.style.setProperty('--desk-icon', getComputedStyle(link, '::before').backgroundImage);
    return copy;
  });
  pill.setAttribute('aria-hidden', 'true');
  track.append(...copies);
  clip.append(track);
  pill.append(clip);
  bar.classList.add('page-bar-sliding');
  bar.append(pill);
  to.classList.remove('selected');

  const px = values => Object.fromEntries(Object.entries(values).map(([name, value]) => [name, value + 'px']));
  const box = link => {
    const outer = bar.getBoundingClientRect(), inner = link.getBoundingClientRect();
    return {left: inner.left - outer.left, top: inner.top - outer.top, width: inner.width, height: inner.height};
  };
  // The track holds the copies where the links are; it moves against the highlight to keep them there.
  const offset = ({left, top}) => px({left: -left, top: -top});
  const layout = () => {
    links.forEach((link, index) => Object.assign(copies[index].style, px(box(link))));
    Object.assign(track.style, px({width: bar.clientWidth, height: bar.clientHeight}));
    const start = box(from), end = box(to);
    Object.assign(pill.style, px(start));
    Object.assign(track.style, offset(start));
    return [start, end];
  };
  layout();
  const done = () => {
    to.classList.add('selected');
    pill.remove();
    // One frame later, so the link takes the highlight at once instead of fading it in.
    requestAnimationFrame(() => bar.classList.remove('page-bar-sliding'));
  };
  // Measure again once the rest of the page has laid out, so the bar sits where it will stay.
  addEventListener('DOMContentLoaded', () => requestAnimationFrame(() => {
    const [start, end] = layout(), timing = {duration: 420, easing: 'cubic-bezier(.2, .8, .2, 1)', fill: 'forwards'};
    track.animate([offset(start), offset(end)], timing);
    pill.animate([px(start), px(end)], timing).finished.then(done, done);
  }), {once: true});
})();
