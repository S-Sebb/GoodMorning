// Inside the installed app only, remember this page so the next launch reopens it.
if (matchMedia('(display-mode: standalone)').matches) {
  document.cookie = 'GoodMorningAppPage=' + encodeURIComponent(location.pathname) + '; Path=/; Secure; SameSite=Strict; Max-Age=31536000';
}
