# Evening tidy-up

At most once a week, the evening check-in adds an optional tidy-up step about
work that has sat untouched for a while. Code chooses the items
(`stale_tasks` in `src/goodmorning/records/routing.py`); the check-in form shows
them (`tidy_fields` in `src/goodmorning/briefings/briefing_preflight.py`), and
saving applies the answers (`TaskStore.tidy` in
`src/goodmorning/records/task_store.py`).

## Which items

A morning row is stale when nothing about it has changed for 7 days past its
workday or deadline, or for 30 days since an undated item was saved. A later
start day (including "Not this week") or any edit restarts the count. Nudges,
errands and reference notes are never asked about. The tidy-up asks about the
three oldest stale items, except:

- an item answered "Keep it, stop asking", which is never asked about again;
- an item asked about in the last 28 days, whatever the answer, so other stale
  items get a turn.

A tidy-up counts as asked as soon as the check-in shows it, even if the check-in
is closed without saving. The next tidy-up comes at least 7 days later. Preparing
the same evening's check-in again, before it is saved, shows the same items with
their current details.

An item in the tidy-up is not also listed in the check-in's finish list; "It's
done" completes it instead.

## Answers

Every answer is optional. Only the user's answer changes a task:

| Answer | Effect |
|---|---|
| Not this week | Hidden from the morning list for 7 days (`defer_until`). |
| It's done | Completed today. |
| No longer needed | Cancelled; it stays in the history. Nothing is deleted. |
| Keep it, stop asking | No change; the tidy-up never asks about it again. |
| Not sure yet, or no answer | No change; not asked again for 28 days. |

If an item changed elsewhere (for example in chat) after the check-in showed it,
its answer is skipped and the newer change stays. The rest of the check-in still
saves, and the evening briefing's feedback notes the skipped item.

## Records

The tidy-up keeps its history in `task_events`, keyed `tidy:DATE`: a
`tidy-offer` event when the check-in shows it, and a `tidy` event with every
item's answer when the check-in is saved. These records decide which items
are left out later; they never change a task themselves.
