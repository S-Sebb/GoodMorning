// Credentials remain in form fields only, never storage, query strings or logs.
const authT = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
document.querySelectorAll('[data-password-target]').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.passwordTarget);
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.dataset.uiText = visible ? 'Hide' : 'Show';
    button.textContent = authT(button.dataset.uiText);
    button.setAttribute('aria-pressed', String(visible));
    button.setAttribute('data-ui-aria-label',`${visible ? 'Hide' : 'Show'} ${button.dataset.passwordLabel}`);
    button.setAttribute('aria-label', authT(button.getAttribute('data-ui-aria-label')));
  });
});
const form = document.querySelector('#account-form');
if (form) form.querySelector('button[type="submit"]').disabled = false;
if (form) form.addEventListener('submit', async event => {
  event.preventDefault();
  const error = document.querySelector('#account-error');
  error.textContent = '';
  const values = Object.fromEntries(new FormData(form));
  if (form.dataset.action === 'login') values.remember = form.elements.remember.checked;
  if (form.dataset.action === 'password' && values.replacement !== values.repeat) {
    error.textContent = authT('The new passwords do not match.');
    return;
  }
  if (form.dataset.action === 'password') {
    const length = [...values.replacement].length;
    if (length < Number(form.dataset.passwordMin) || length > Number(form.dataset.passwordMax)
        || !/\p{L}/u.test(values.replacement) || !/\p{Nd}/u.test(values.replacement)) {
      error.textContent = document.querySelector('#password-rules').textContent;
      return;
    }
  }
  delete values.repeat;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const response = await fetch(`/api/auth/${form.dataset.action}`, {
      method: 'POST', headers: {'Content-Type':'application/json','X-Briefing-CSRF':form.dataset.csrf},
      body: JSON.stringify(values), cache: 'no-store', credentials: 'same-origin'
    });
    const result = await goodmorningJSON(response);
    if (!response.ok) throw new Error(result.error || authT('Sign-in unavailable.'));
    form.reset();
    // The installed app resumes its own last page instead of the website's home.
    const app = result.next === '/' && (matchMedia('(display-mode: standalone)').matches || navigator.userAgent.includes('GoodMorningApp/'));
    location.replace(app ? '/app' : result.next);
  } catch (failure) { error.textContent = failure.message; }
  finally { button.disabled = false; }
});
const logout = document.querySelector('#sign-out');
document.addEventListener('website:before-refresh', event => {
  if ((form && form.querySelector('button[type="submit"]').disabled) || logout?.disabled) event.preventDefault();
});
if (logout) logout.addEventListener('click', async () => {
  logout.disabled = true;
  try {
    // This device stops receiving the account's notifications (app.js).
    if (typeof goodmorningBeforeSignOut === 'function') await goodmorningBeforeSignOut();
    const response = await fetch('/api/auth/logout', {
      method:'POST',headers:{'Content-Type':'application/json','X-Briefing-CSRF':logout.dataset.csrf},
      body:'{}',cache:'no-store',credentials:'same-origin'
    });
    if (response.ok) location.replace('/login');
    else logout.disabled = false;
  } catch { logout.disabled = false; }
});
