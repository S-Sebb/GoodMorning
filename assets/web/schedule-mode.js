// Reopen the schedule view last used on this kind of screen before the week paints.
// Phones and wider screens remember their views separately.
const scheduleViewKey = 'goodmorning-schedule-view-' + (matchMedia('(max-width: 700px)').matches ? 'phone' : 'desktop');
try {
  if (!location.search && localStorage.getItem(scheduleViewKey) === 'day') location.replace('/schedule?view=day');
} catch {}
