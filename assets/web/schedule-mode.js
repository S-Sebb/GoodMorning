// Reopen the schedule view last used in this browser before the week paints.
try {
  if (!location.search && localStorage.getItem('goodmorning-schedule-view') === 'day') location.replace('/schedule?view=day');
} catch {}
