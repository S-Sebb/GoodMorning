// Credentials remain in form fields only, never storage, query strings or logs.
document.querySelectorAll('[data-password-target]').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.passwordTarget);
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.textContent = visible ? 'Hide' : 'Show';
    button.setAttribute('aria-pressed', String(visible));
    button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${button.dataset.passwordLabel}`);
  });
});
const form = document.querySelector('#account-form');
if (form) form.addEventListener('submit', async event => {
  event.preventDefault();
  const error = document.querySelector('#account-error');
  error.textContent = '';
  const values = Object.fromEntries(new FormData(form));
  if (form.dataset.action === 'login') values.remember = form.elements.remember.checked;
  if (form.dataset.action === 'password' && values.replacement !== values.repeat) {
    error.textContent = 'The new passwords do not match.';
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
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Sign-in unavailable.');
    form.reset();
    location.replace(result.next);
  } catch (failure) { error.textContent = failure.message; }
  finally { button.disabled = false; }
});
const logout = document.querySelector('#sign-out');
if (logout) logout.addEventListener('click', async () => {
  logout.disabled = true;
  try {
    const response = await fetch('/api/auth/logout', {
      method:'POST',headers:{'Content-Type':'application/json','X-Briefing-CSRF':logout.dataset.csrf},
      body:'{}',cache:'no-store',credentials:'same-origin'
    });
    if (response.ok) location.replace('/login');
    else logout.disabled = false;
  } catch { logout.disabled = false; }
});
