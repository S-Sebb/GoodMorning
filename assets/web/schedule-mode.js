// Before the week paints: phones always open Schedule on Day (today); wider screens reopen the view
// used last, Week the first time.
const schedulePhone = matchMedia('(max-width: 700px)').matches;
const scheduleViewKey = 'goodmorning-schedule-view-desktop';
try {
  if (!location.search && (schedulePhone || localStorage.getItem(scheduleViewKey) === 'day')) location.replace('/schedule?view=day');
} catch {}
