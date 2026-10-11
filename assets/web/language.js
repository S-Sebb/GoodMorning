// Only the non-secret interface language is shared between sibling domains.
const languageConfig = JSON.parse(document.querySelector('#language-config').dataset.config);
let goodmorningLanguage = languageConfig.language;
let languageRevision = 0;
const languagePatterns = Object.entries(goodmorningCatalog).filter(([key]) => key.includes('{')).map(([key, value]) => {
  const names = [];
  const pattern = key.split(/(\{[a-z]+\})/).map(part => {
    if (/^\{[a-z]+\}$/.test(part)) { names.push(part.slice(1, -1)); return '(.+?)'; }
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }).join('');
  return { pattern: new RegExp('^' + pattern + '$'), names, value };
});
function goodmorningT(key, values = {}) {
  let result = goodmorningLanguage === 'zh-CN' && Object.hasOwn(goodmorningCatalog,key) ? goodmorningCatalog[key] : key;
  if (goodmorningLanguage === 'zh-CN' && !Object.hasOwn(goodmorningCatalog, key)) {
    for (const entry of languagePatterns) {
      const match = key.match(entry.pattern);
      if (match) { result = entry.value; values = Object.fromEntries(entry.names.map((name, index) => [name, match[index + 1]])); break; }
    }
  }
  return result.replace(/\{([a-z]+)\}/g, (token, name) => values[name] ?? token);
}
function applyWebsiteLanguage(language) {
  if (!['en', 'zh-CN'].includes(language)) return;
  goodmorningLanguage = language;
  document.documentElement.lang = language;
  document.querySelectorAll('[data-ui-language]').forEach(node => { node.lang=language; });
  document.querySelectorAll('[data-ui-section-title]').forEach(node => {
    node.setAttribute('aria-label',node.dataset.uiSectionNumber+': '+goodmorningT(node.dataset.uiSectionTitle));
  });
  const title = document.querySelector('title[data-ui-title]');
  if (title) document.title = goodmorningT(title.dataset.uiTitle);
  document.querySelectorAll('[data-ui-text]').forEach(node => { node.textContent = goodmorningT(node.dataset.uiText); node.lang=language; });
  for (const attribute of ['aria-label', 'title', 'placeholder', 'alt']) {
    document.querySelectorAll(`[data-ui-${attribute}]`).forEach(node => node.setAttribute(attribute, goodmorningT(node.getAttribute(`data-ui-${attribute}`))));
  }
  document.querySelectorAll('[data-ui-date]').forEach(node => {
    node.textContent = new Intl.DateTimeFormat(language, {weekday:'short',month:'short',day:'2-digit',timeZone:'UTC'}).format(new Date(node.dataset.uiDate + 'T12:00:00Z'));
  });
  document.querySelectorAll('[data-ui-full-date]').forEach(node => {
    node.lang = language;
    node.textContent = new Intl.DateTimeFormat(language, {weekday:'long',month:'long',day:'2-digit',year:'numeric',timeZone:'UTC'}).format(new Date(node.dataset.uiFullDate + 'T12:00:00Z'));
  });
  document.querySelector('#website-language').value = language;
  document.dispatchEvent(new Event('website:language'));
}
const languageForm = document.querySelector('#language-form');
async function saveWebsiteLanguage(event) {
  event?.preventDefault();
  const feedback = document.querySelector('#language-feedback');
  const selected = document.querySelector('#website-language');
  languageRevision++;
  selected.disabled = true;
  try {
    const response = await fetch('/api/language', {method:'POST',headers:{'Content-Type':'application/json','X-Briefing-CSRF':languageConfig.csrf},
      body:JSON.stringify({language:selected.value}),credentials:'same-origin',cache:'no-store'});
    const result = await response.json().catch(() => ({error:goodmorningT('Language could not be saved. Try again.')}));
    if (!response.ok) throw new Error(result.error || goodmorningT('Language could not be saved. Try again.'));
    if (!['en','zh-CN'].includes(result.language)) throw new Error(goodmorningT('Language could not be saved. Try again.'));
    applyWebsiteLanguage(result.language); feedback.textContent = goodmorningT('Language saved.');
  } catch (error) { selected.value = goodmorningLanguage; feedback.textContent = error.message; }
  finally { selected.disabled = false; }
}
languageForm.addEventListener('submit', saveWebsiteLanguage);
document.addEventListener('website:before-refresh', event => {
  if (document.querySelector('#website-language').disabled) event.preventDefault();
});
document.querySelector('#website-language').addEventListener('change', saveWebsiteLanguage);
let languageSyncing = false;
async function syncWebsiteLanguage() {
  if (document.hidden || languageSyncing || document.querySelector('#website-language').disabled) return;
  languageSyncing = true;
  const version = languageRevision;
  try {
    const response = await fetch('/api/language', {credentials:'same-origin',cache:'no-store'});
    if (response.ok) { const result = await response.json(); if (version === languageRevision && result.language !== goodmorningLanguage) applyWebsiteLanguage(result.language); }
  } catch { /* Keep readable content and unsent drafts during an outage. */ }
  finally { languageSyncing = false; }
}
window.addEventListener('focus', syncWebsiteLanguage);
document.addEventListener('visibilitychange', syncWebsiteLanguage);
setInterval(syncWebsiteLanguage, 15000);
