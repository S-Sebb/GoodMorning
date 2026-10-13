// Never expose an upstream HTML error page as a JSON parser exception.
async function goodmorningJSON(response) {
  const t = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  try {
    const value = await response.json();
    if (!value || typeof value !== 'object') throw new Error('Invalid response');
    return value;
  } catch {
    const message = response.status === 429
      ? 'Too many requests. Please wait a moment, then check the page again.'
      : response.status === 401
        ? 'Please sign in again.'
        : response.status >= 500
          ? 'The secretary is temporarily unavailable. Refresh to check status before trying again.'
          : 'The server returned an unreadable response. Refresh to check status before trying again.';
    const error = new Error(t(message));
    error.status = response.status;
    throw error;
  }
}
