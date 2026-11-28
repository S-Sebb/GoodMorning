"""Account-local events, confirmed TBC appointments and planned task occurrences.

Everything is read-only except one action: ticking a to-do or habit done (or back) on today
or an earlier day, through the task and habit stores. Calendar events are never changed."""

import hashlib
import html
import json
import re
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.calendar import public_holidays
from goodmorning.calendar.calendar_safety import safe_value
from goodmorning.calendar.calendar_store import CalendarStore, endpoints
from goodmorning.records.daily import inspect, read_record, record_path
from goodmorning.records.routing import converted_draft_ids
from goodmorning.runtime_files import profile_fields

from . import language as ui
from . import quick_chat
from .about_me import desk_link
from .briefing_resources import favicon_links
from .chat_theme import clock_theme


def week_offset(query):
    if set(query) - {"week"} or len(query.get("week", ["0"])) != 1:
        raise ValueError("Invalid schedule week")
    value = query.get("week", ["0"])[0]
    if value not in ("-3", "-2", "-1", "0", "1", "2", "3"):
        raise ValueError("Schedule outside the seven-week window")
    return int(value)


DAY_RANGE = 21  # Day steps stay inside the seven-week window.


def schedule_query(query):
    """Return ('week', week offset) or ('day', days from today)."""
    if "view" not in query:
        return "week", week_offset(query)
    if (
        set(query) - {"view", "day"}
        or query["view"] != ["day"]
        or len(query.get("day", ["0"])) != 1
    ):
        raise ValueError("Invalid schedule view")
    value = query.get("day", ["0"])[0]
    if value not in {str(step) for step in range(-DAY_RANGE, DAY_RANGE + 1)}:
        raise ValueError("Schedule outside the seven-week window")
    return "day", int(value)


def saved_day(runtime, zone, now, offset):
    if type(offset) is not int or not -DAY_RANGE <= offset <= DAY_RANGE:
        raise ValueError("Schedule outside the seven-week window")
    today = date.fromisoformat(briefing_day(zone, now))
    target = today + timedelta(days=offset)
    week = (
        target
        - timedelta(days=target.weekday())
        - (today - timedelta(days=today.weekday()))
    ).days // 7
    data = saved_week(runtime, zone, now, week)
    return {
        **data,
        "offset": offset,
        "week": week,
        "days": [data["days"][target.weekday()]],
    }


def saved_week(runtime, zone, now, offset):
    if type(offset) is not int or not -3 <= offset <= 3:
        raise ValueError("Schedule outside the seven-week window")
    local = now.astimezone(ZoneInfo(zone))
    today = date.fromisoformat(briefing_day(zone, now))
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    days = [
        {
            "date": (monday + timedelta(days=i)).isoformat(),
            "events": [],
            "tasks": [],
            "plan_error": False,
        }
        for i in range(7)
    ]
    warnings = []
    converted = set()
    calendar_error = False
    calendar = runtime / "calendar.sqlite"
    try:
        if calendar.is_symlink():
            raise ValueError("Unsafe calendar")
        if calendar.exists():
            store = CalendarStore(str(calendar), readonly=True)
            try:
                store.con.execute("BEGIN")
                start = datetime.combine(monday, time(), local.tzinfo)
                end = datetime.combine(monday + timedelta(days=7), time(), local.tzinfo)
                events = [
                    worded(event, "event")
                    for event in safe_value(
                        store.query(start, end, limit=-1, details=True)
                    )
                ]
                converted = converted_draft_ids(store)
                for event in events:
                    begins, ends = endpoints(event)
                    for day in days:
                        day_start = datetime.combine(
                            date.fromisoformat(day["date"]), time(), local.tzinfo
                        )
                        day_end = datetime.combine(
                            day_start.date() + timedelta(days=1), time(), local.tzinfo
                        )
                        if begins < day_end and ends > day_start:
                            day["events"].append(event)
            finally:
                store.close()
    except (ValueError, OSError, KeyError, sqlite3.Error):
        calendar_error = True
        warnings.append(
            "Calendar records could not be read. Other saved plans are still shown."
        )
    for day in days:
        try:
            text, _ = read_record(record_path(runtime, day["date"]))
            _, _, tasks = inspect(text, day["date"])
            seen = set()
            for task in safe_value(tasks):
                key = task["ref"] or " ".join(task["text"].split())
                if key not in seen:
                    day["tasks"].append(
                        {k: task[k] for k in ("id", "section", "text", "done")}
                    )
                    seen.add(key)
        except (ValueError, OSError, UnicodeError):
            day["plan_error"] = True
    if (runtime / "inbox.sqlite").exists():
        from goodmorning.records.inbox_store import InboxStore
        from goodmorning.records.routing import (
            calendar_day_extras,
            confirmed_drafts,
            planned_day,
        )
        from goodmorning.records.task_store import TaskStore

        inbox = None
        try:
            inbox = InboxStore(runtime)
            if inbox.version == 2:
                store = TaskStore(inbox)
                inbox.db.execute("BEGIN")
                drafts = [
                    worded(draft, "draft")
                    for draft in safe_value(
                        confirmed_drafts(
                            store,
                            monday.isoformat(),
                            (monday + timedelta(days=7)).isoformat(),
                            converted,
                        )
                    )
                ]
                rules = rhythms(store, runtime)
                for day in days:
                    day["plan_error"] = (
                        False  # Legacy history is not a canonical source failure.
                    )
                    rows = planned_day(store, day["date"]) + calendar_day_extras(
                        store, day["date"], today.isoformat()
                    )
                    day["tasks"] = [
                        worded(
                            dict(
                                r,
                                id=r["occurrence_id"] or r["id"] + ":due",
                                task_id=r["id"],
                                text=r["title"],
                                done=r["status"] == "done",
                                section="nice-to-do" if r["optional"] else "flexible",
                                rhythm=rules.get(r["id"]),
                                # Deadline markers, future days and stopped habits stay read-only.
                                tickable=day["date"] <= today.isoformat()
                                and r.get("marker") != "due"
                                and not r.get("closed"),
                            ),
                            "task",
                        )
                        for r in safe_value(rows)
                    ]
                    day["events"].extend(
                        draft for draft in drafts if draft["date"] == day["date"]
                    )
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
            warnings.append(
                "Task records could not be read; no availability is inferred."
            )
            for day in days:
                day["plan_error"] = "tasks"
                day["tasks"] = []
        finally:
            if inbox:
                inbox.close()
    try:
        codes = public_holidays.regions(
            profile_fields(runtime).get("holiday_countries")
        )
    except ValueError:
        codes = []
        warnings.append(
            "Your public holiday choice could not be read, so no holidays are shown."
        )
    listed = public_holidays.days(
        codes, days[0]["date"], (monday + timedelta(days=7)).isoformat(), ui.current()
    )
    for day in days:
        day["holidays"] = [
            {"kind": entry["kind"], "title": entry["title"]}
            for entry in public_holidays.shown(
                listed.get(day["date"], []), codes, ui.current()
            )
        ]
    unlisted = {}
    for code, year in public_holidays.unlisted(
        codes, days[0]["date"], days[-1]["date"]
    ):
        unlisted.setdefault(year, []).append(public_holidays.choice(code, ui.current()))
    return {
        "today": today.isoformat(),
        "start": monday.isoformat(),
        "offset": offset,
        "timezone": zone,
        "days": days,
        "warnings": warnings,
        "calendar_error": calendar_error,
        "unlisted_holidays": [
            [year, ", ".join(names)] for year, names in sorted(unlisted.items())
        ],
    }


def rhythms(store, runtime):
    """Each repeating task's rule and each habit's policy, by ID, for its cadence label."""
    from goodmorning.records.custom_store import CustomStore

    rules = {task["id"]: task["repeat"] for task in store.all() if task["repeat"]}
    try:
        custom = CustomStore(runtime, write=False)
    except ValueError:
        return rules  # No habits saved yet.
    try:
        return rules | {rule["id"]: rule["policy"] for rule in custom.all()}
    finally:
        custom.close()


WEEKDAYS = {
    "en": [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ],
    "zh-CN": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
}


def cadence(rule):
    """Plain words for a repeat rule or habit policy, in the website language."""
    if not rule or "event_subject" in rule:
        return ""
    if rule.get("interval_days"):
        days = rule["interval_days"]
        return ui.text("Every day" if days == 1 else "Every {count} days", count=days)
    if "weekdays" in rule:
        days = sorted(rule["weekdays"])
        named = {
            (0, 1, 2, 3, 4, 5, 6): "Every day",
            (0, 1, 2, 3, 4): "Weekdays",
            (5, 6): "Weekends",
        }
        if tuple(days) in named:
            return ui.text(named[tuple(days)])
        names = WEEKDAYS[ui.current()]
        if len(days) == 1:
            listed = names[days[0]]
        elif ui.current() == "zh-CN":
            listed = "、".join(names[day] for day in days)
        else:
            listed = ", ".join(names[day][:3] for day in days)
        return ui.text("Every {days}", days=listed)
    if "monthdays" in rule:
        months = rule.get("every_months", 1)
        return ui.text(
            "Every month" if months == 1 else "Every {count} months", count=months
        )
    if rule.get("yearly"):
        return ui.text("Every year")
    return ui.text("On set dates")


def checklist_kind(task):
    """'routine' for repeats and habits, 'deadline' for markers that are never ticked, else 'todo'."""
    if task.get("marker") == "due":
        return "deadline"
    if task.get("category") == "habit" or (
        task.get("category") == "routine" and not task.get("prep_for")
    ):
        return "routine"
    return "todo"


def worded(item, kind):
    """The Schedule label and morning line the secretary saved for this item; saved fields when missing or stale."""
    from goodmorning.records.display import wording

    if kind == "task" and item.get("category") == "habit":
        return item
    label = wording(item, kind, "schedule", ui.current())
    if not label:
        return item
    line = wording(item, kind, "morning", ui.current())["detail"]
    if kind == "task":
        return {**item, "text": label, "detail": line}
    if kind == "draft":
        return {**item, "title": label, "subject": label, "detail": line}
    return {**item, "subject": label, "notes": line}


def event_card(event, day, zone):
    if event.get("draft"):
        identifier = html.escape(event["id"], quote=True)
        location = (
            '<span class="event-location" data-content>'
            + html.escape(event["location"])
            + "</span>"
            if event["location"]
            else ""
        )
        notes = (
            '<p class="event-notes" data-content>'
            + html.escape(event["detail"])
            + "</p>"
            if event["detail"]
            else ""
        )
        return (
            '<details class="schedule-event is-tbc" id="event-'
            + day
            + "-"
            + identifier
            + '">'
            '<summary id="summary-'
            + day
            + "-"
            + identifier
            + '"><span class="event-time">'
            + ui.ui("TBC")
            + "</span>"
            '<span class="event-title" data-content>'
            + html.escape(event["title"])
            + "</span>"
            + location
            + "</summary>"
            '<div class="event-detail"><p>'
            + ui.ui("Appointment time not yet confirmed")
            + "</p>"
            + notes
            + '<p class="event-source">'
            + ui.ui("Time zone")
            + " · <span data-content>"
            + html.escape(event["timezone"])
            + "</span></p></div></details>"
        )
    begins, ends = (point.astimezone(ZoneInfo(zone)) for point in endpoints(event))
    label = (
        ui.ui("All day")
        if event["all_day"]
        else html.escape(
            begins.strftime("%H:%M")
            if begins.date().isoformat() == day
            else ui.text("Continues")
        )
    )
    end_label = ends.strftime("%H:%M")
    if begins.date() != ends.date():
        end_label = ui.text(
            "{date} at {time}", date=ends.date().isoformat(), time=end_label
        )
    duration = (
        ""
        if event["all_day"]
        else '<p class="event-end">' + ui.ui("Until {time}", time=end_label) + "</p>"
    )
    location = event.get("location") or event.get("online")
    location_html = (
        '<span class="event-location" data-content>' + html.escape(location) + "</span>"
        if location
        else ""
    )
    notes = (
        '<p class="event-notes" data-content>' + html.escape(event["notes"]) + "</p>"
        if event.get("notes")
        else ""
    )
    source = (
        ""
        if event["source"] == "custom"
        else '<p class="event-source">'
        + ui.ui("Calendar")
        + " · <span data-content>"
        + html.escape(event["source"])
        + "</span></p>"
    )
    return (
        '<details class="schedule-event" id="event-'
        + day
        + "-"
        + html.escape(event["id"], quote=True)
        + '">'
        '<summary id="summary-'
        + day
        + "-"
        + html.escape(event["id"], quote=True)
        + '"><span class="event-time">'
        + label
        + '</span><span class="event-title" data-content>'
        + html.escape(event["subject"])
        + "</span>"
        + location_html
        + "</summary>"
        '<div class="event-detail">' + duration + notes + source + "</div></details>"
    )


def task_card(task, day=None):
    state = task.get("status", "done" if task["done"] else "open")
    metadata = []
    if task.get("marker") == "due":
        metadata.append(
            '<small class="task-marker is-short">' + ui.ui("Deadline") + "</small>"
        )
        metadata.append(
            '<small class="task-marker is-long">'
            + ui.ui("Deadline · no workday assigned")
            + "</small>"
        )
    elif task.get("marker") == "flexible":
        metadata.append(
            '<small class="task-marker is-long">'
            + ui.ui("Flexible habit · moves with what you actually do")
            + "</small>"
        )
    if task.get("project"):
        # A tag; the "Project:" prefix stays for screen readers.
        metadata.append(
            '<small class="task-project"><span class="visually-hidden">'
            + ui.ui("Project:")
            + " </span><span data-content>"
            + html.escape(task["project"])
            + "</span></small>"
        )
    if task["section"] == "nice-to-do":
        metadata.append('<small class="task-kind">' + ui.ui("Optional") + "</small>")
    if state in ("partial", "blocked"):
        metadata.append(
            '<small class="task-progress">' + ui.ui(state.capitalize()) + "</small>"
        )
    if task.get("due_date") and (task.get("marker") != "due" or task.get("due_at")):
        deadline = task.get("due_at") or task["due_date"]
        metadata.append(
            '<small class="task-deadline">'
            + ui.ui(
                "Soft target: {date}" if task.get("due_soft") else "Due: {date}",
                date=ui.human_dates(deadline, day),
            )
            + "</small>"
        )
    if (task.get("when") or {}).get("morning_before"):
        metadata.append(
            '<small class="task-trigger">'
            + ui.ui(
                "Reminder trigger: you start the morning briefing before {time} ({zone})",
                time=task["when"]["morning_before"],
                zone=task["timezone"],
            )
            + "</small>"
        )
    detail = " · ".join(
        value for value in (task.get("detail"), task.get("report_detail")) if value
    )
    if detail:
        metadata.append(
            '<small class="task-detail" data-content>'
            + html.escape(detail)
            + "</small>"
        )
    label = {"done": "Done", "partial": "Partial", "blocked": "Blocked"}.get(
        state, "Not completed"
    )
    mark = "✓" if task["done"] else "○"
    if task.get("tickable"):
        # Enabled by schedule.js; without JavaScript the mark stays read-only.
        action = (
            "Mark “{task}” not done" if task["done"] else "Mark “{task}” done"
        ).format(task=task["text"])
        mark = (
            '<button id="tick-'
            + day
            + "-"
            + html.escape(task["task_id"], quote=True)
            + '" class="task-state task-tick" type="button" disabled aria-label="'
            + html.escape(action, quote=True)
            + '"'
            ' data-tick-id="'
            + html.escape(task["task_id"], quote=True)
            + '" data-tick-date="'
            + day
            + '"'
            ' data-tick-revision="'
            + str(task["revision"])
            + '" data-tick-done="'
            + str(bool(task["done"])).lower()
            + '">'
            + mark
            + "</button>"
        )
    else:
        mark = (
            '<span class="task-state" aria-label="'
            + html.escape(ui.text(label), quote=True)
            + '">'
            + mark
            + "</span>"
        )
    kind, hint = task_kind(task)
    icon = (
        '<span class="task-icon is-'
        + kind
        + '" role="img" title="'
        + html.escape(ui.text(hint), quote=True)
        + '" aria-label="'
        + html.escape(ui.text(hint), quote=True)
        + '"></span>'
    )
    tip = ' title="' + html.escape(detail, quote=True) + '"' if detail else ""
    return (
        '<li class="schedule-task is-'
        + state
        + '"'
        + tip
        + ">"
        + mark
        + "<div>"
        + icon
        + '<span class="task-title" data-content>'
        + html.escape(task["text"])
        + "</span>"
        + "".join(metadata)
        + "</div></li>"
    )


def task_kind(task):
    """The icon that tells to-dos apart, and the tooltip that says what it means."""
    if task.get("category") == "habit":
        return "habit", "Flexible habit · moves with what you actually do"
    if task.get("prep_for"):
        return "prep", "Preparation for an event"
    if task.get("marker") == "due":
        return "deadline", "Deadline · no workday assigned"
    if task.get("project"):
        return "project", "Project step"
    if task.get("category") == "routine":
        return "routine", "Repeats"
    return "oneoff", "One-off to-do"


def date_part(day, part):
    value = date.fromisoformat(day)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    if part == "day":
        label = str(value.day)
    elif part == "weekday":
        label = (
            weekdays[value.weekday()]
            if ui.current() == "zh-CN"
            else value.strftime("%a")
        )
    elif part == "month":
        label = (
            f"{value.year}年{value.month}月"
            if ui.current() == "zh-CN"
            else value.strftime("%B %Y")
        )
    elif part == "range-day":
        label = f"{value.day}日" if ui.current() == "zh-CN" else str(value.day)
    elif part == "dated":
        label = (
            f"{value.year}年{value.month}月{value.day}日"
            if ui.current() == "zh-CN"
            else f"{value:%b} {value.day}, {value.year}"
        )
    elif part == "full":
        label = (
            f"{value.month}月{value.day}日星期" + "一二三四五六日"[value.weekday()]
            if ui.current() == "zh-CN"
            else value.strftime("%A, %B ") + str(value.day)
        )
    elif part == "weekday-date":
        label = (
            f"{value.month}月{value.day}日周" + "一二三四五六日"[value.weekday()]
            if ui.current() == "zh-CN"
            else f"{value:%a}, {value:%b} {value.day}"
        )
    else:
        label = (
            f"{value.month}月{value.day}日"
            if ui.current() == "zh-CN"
            else f"{value:%b} {value.day}"
        )
    return (
        '<span data-content data-schedule-date="'
        + day
        + '" data-schedule-part="'
        + part
        + '">'
        + html.escape(label)
        + "</span>"
    )


# The month is always named so the range reads on its own; years appear only when the week spans two.
def week_range(first, last):
    same_year = first[:4] == last[:4]
    start = date_part(first, "short" if same_year else "dated")
    end = date_part(
        last,
        "range-day" if first[:7] == last[:7] else "short" if same_year else "dated",
    )
    return start + '<span class="range-dash">–</span>' + end


def step_link(link_id, href, label, symbol, enabled):
    if not enabled:
        return (
            '<span class="week-arrow is-disabled" aria-disabled="true" aria-label="'
            + label
            + '">'
            + symbol
            + "</span>"
        )
    return (
        '<a id="'
        + link_id
        + '" class="week-arrow" data-schedule-nav href="'
        + href
        + '" aria-label="'
        + label
        + '">'
        + symbol
        + "</a>"
    )


def mode_switch(mode, week):
    links = (
        ("week", "Week", "/schedule?week=" + str(week)),
        ("day", "Day", "/schedule?view=day"),
    )
    return (
        '<div class="schedule-mode" role="group" aria-label="Schedule view">'
        + "".join(
            '<a class="schedule-mode-link" data-schedule-nav data-schedule-mode="'
            + name
            + '" href="'
            + href
            + '"'
            + (' aria-current="true"' if name == mode else "")
            + ">"
            + ui.ui(label)
            + "</a>"
            for name, label, href in links
        )
        + "</div>"
    )


def tools(data, checked, heading, events, tasks, done):
    refresh = (
        '<button id="schedule-refresh" class="schedule-icon" type="button" aria-label="Refresh saved plans" title="Refresh saved plans">'
        '<svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true"><path d="M16 8a6 6 0 1 0 .2 3M16 3v5h-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
    )
    info = (
        '<details class="schedule-info" id="schedule-info"><summary class="schedule-icon" aria-label="Schedule details" title="Schedule details">'
        '<svg viewBox="0 0 20 20" width="18" height="18" fill="currentColor" aria-hidden="true"><circle cx="4" cy="10" r="1.4"/><circle cx="10" cy="10" r="1.4"/><circle cx="16" cy="10" r="1.4"/></svg>'
        '</summary><div class="schedule-info-panel"><h2>' + ui.ui(heading) + "</h2><dl>"
        "<dt>" + ui.ui("Events") + "</dt><dd>" + str(events) + "</dd>"
        "<dt>"
        + ui.ui("To-dos")
        + "</dt><dd>"
        + str(tasks)
        + " · "
        + ui.ui("{done} completed", done=done)
        + "</dd>"
        "<dt>"
        + ui.ui("Time zone")
        + "</dt><dd data-content>"
        + html.escape(data["timezone"])
        + "</dd>"
        + "".join(
            "<dt>"
            + ui.ui("Public holidays")
            + "</dt><dd>"
            + ui.ui("Not listed yet for {year}: {regions}", year=year, regions=names)
            + "</dd>"
            for year, names in data["unlisted_holidays"]
        )
        + "<dt>"
        + ui.ui("Saved records")
        + '</dt><dd id="schedule-status">'
        + ui.ui("Checked at {time}", time=checked)
        + "</dd></dl>"
    )
    return '<span class="schedule-tools">' + refresh + info + "</div></details></span>"


def holidays(day):
    """Public holidays and make-up workdays head their day; they are not saved events."""
    return "".join(
        '<p class="schedule-holiday is-'
        + entry["kind"]
        + '" data-content>'
        + html.escape(entry["title"])
        + "</p>"
        for entry in day["holidays"]
    )


def notices(data):
    return "".join(
        '<p class="schedule-warning" role="status">' + ui.ui(warning) + "</p>"
        for warning in data["warnings"]
    )


def view(data, checked):
    days, offset = data["days"], data["offset"]
    label = {0: "This week", -1: "Last week", 1: "Next week"}.get(
        offset, "{count} weeks earlier" if offset < 0 else "{count} weeks ahead"
    )
    total_events = len({event["id"] for day in days for event in day["events"]})
    total_tasks = sum(len(day["tasks"]) for day in days)
    done = sum(task["done"] for day in days for task in day["tasks"])
    controls = (
        '<div class="schedule-toolbar"><div class="schedule-date"><h1 id="week-heading">'
        + date_part(days[0]["date"], "month")
        + "</h1>"
        '<p class="schedule-range">'
        + week_range(days[0]["date"], days[-1]["date"])
        + (
            ('<span class="range-dot"> · </span>' + ui.ui(label, count=abs(offset)))
            if offset
            else ""
        )
        + "</p></div>"
        '<nav class="schedule-navigation" aria-label="Week navigation">'
        + mode_switch("week", offset)
        + step_link(
            "week-previous",
            "/schedule?week=" + str(offset - 1),
            "Previous week",
            "‹",
            offset > -3,
        )
        + '<a id="week-current" class="current-week" data-schedule-nav href="/schedule">'
        + ui.ui("This week")
        + "</a>"
        + step_link(
            "week-next",
            "/schedule?week=" + str(offset + 1),
            "Next week",
            "›",
            offset < 3,
        )
        + tools(data, checked, "Week details", total_events, total_tasks, done)
        + "</nav></div>"
    )
    overview = '<nav class="schedule-day-strip" aria-label="Jump to a day">'
    columns = '<div class="schedule-grid">'
    for day in days:
        today = day["date"] == data["today"]
        marker = (
            '<span class="schedule-today">' + ui.ui("Today") + "</span>"
            if today
            else '<span class="schedule-today" aria-hidden="true"></span>'
        )
        overview += (
            '<a href="#day-'
            + day["date"]
            + '"'
            + (' aria-current="date"' if today else "")
            + ">"
            + date_part(day["date"], "weekday")
            + "<strong>"
            + date_part(day["date"], "day")
            + "</strong></a>"
        )
        columns += (
            '<section id="day-'
            + day["date"]
            + '" class="schedule-day'
            + (" is-today" if today else "")
            + '" aria-labelledby="heading-'
            + day["date"]
            + '">'
            '<header class="schedule-day-heading"><h3 id="heading-'
            + day["date"]
            + '"><span class="schedule-weekday">'
            + date_part(day["date"], "weekday")
            + '</span><span class="schedule-day-number">'
            + date_part(day["date"], "day")
            + "</span></h3>"
            + marker
            + holidays(day)
            + "</header>"
            '<div class="schedule-calendar">'
        )
        # Only lists with something to show get a heading; a day with nothing saved says so once.
        # The two cells stay, empty or not, so the week's to-dos line up across days.
        if day["events"]:
            columns += (
                "<h4>"
                + ui.ui("Events")
                + "</h4>"
                + "".join(
                    event_card(event, day["date"], data["timezone"])
                    for event in day["events"]
                )
            )
        elif data.get("calendar_error"):
            columns += (
                "<h4>"
                + ui.ui("Events")
                + '</h4><p class="schedule-empty">'
                + ui.ui("Calendar unavailable")
                + "</p>"
            )
        elif not day["tasks"] and not day["plan_error"]:
            columns += '<p class="schedule-empty">' + ui.ui("Nothing saved") + "</p>"
        columns += '</div><div class="schedule-work">'
        if day["tasks"] or day["plan_error"]:
            columns += "<h4>" + ui.ui("To-dos") + "</h4>"
        if day["tasks"]:
            columns += (
                '<ul class="schedule-tasks">'
                + "".join(
                    task_card(task, day["date"])
                    for task in sorted(
                        day["tasks"], key=lambda task: bool(task["done"])
                    )
                )
                + "</ul>"
            )
        if day["plan_error"]:
            columns += (
                '<p class="schedule-empty">'
                + ui.ui(
                    "Task records unavailable"
                    if day["plan_error"] == "tasks"
                    else "Daily plan unavailable"
                )
                + "</p>"
            )
        columns += "</div></section>"
    notice = notices(data)
    return controls + notice + overview + "</nav>" + columns + "</div>"


def day_event(event, day, zone, now):
    """One event with its times spelled out; on the current day it also says whether it ended."""
    span = None
    if event.get("draft"):
        place, notes = event["location"], event["detail"]
        start, until, state, sort = ui.ui("TBC"), "", "tbc", ""
        source = (
            '<p class="event-source">'
            + ui.ui("Appointment time not yet confirmed")
            + " · "
            + ui.ui("Time zone")
            + " · <span data-content>"
            + html.escape(event["timezone"])
            + "</span></p>"
        )
        title = event["title"]
    else:
        begins, ends = (point.astimezone(ZoneInfo(zone)) for point in endpoints(event))
        local = now.astimezone(ZoneInfo(zone))
        if event["all_day"]:
            start, until, state, sort = ui.ui("All day"), "", "all-day", ""
        else:
            span = begins, ends
            # Untimed and continuing entries come first; the rest follow by start time.
            sort = begins.isoformat() if begins.date().isoformat() == day else ""
            start = (
                html.escape(begins.strftime("%H:%M")) if sort else ui.ui("Continues")
            )
            until = (
                html.escape(ends.strftime("%H:%M"))
                if ends.date().isoformat() == day
                else ui.ui(
                    "Until {time}",
                    time=ui.text(
                        "{date} at {time}",
                        date=ends.date().isoformat(),
                        time=ends.strftime("%H:%M"),
                    ),
                )
            )
            # Before 04:00 the briefing day's events show as ended and the calendar day's as live.
            state = (
                ""
                if day not in (local.date().isoformat(), briefing_day(zone, now))
                else "past"
                if ends <= local
                else "now"
                if begins <= local
                else "next"
            )
        place, notes = event.get("location") or event.get("online"), event.get("notes")
        source = (
            ""
            if event["source"] == "custom"
            else '<p class="event-source">'
            + ui.ui("Calendar")
            + " · <span data-content>"
            + html.escape(event["source"])
            + "</span></p>"
        )
        title = event["subject"]
    return {
        "start": start,
        "until": until,
        "state": state,
        "title": title,
        "place": place,
        "notes": notes,
        "source": source,
        "sort": sort,
        "span": span,
    }


def day_event_card(item, events, upcoming):
    tags = []
    if item["state"] == "now":
        tags.append('<span class="day-tag is-now">' + ui.ui("Now") + "</span>")
    if item is upcoming:
        tags.append('<span class="day-tag is-next">' + ui.ui("Next up") + "</span>")
    if item["span"]:
        begins, ends = item["span"]
        others = [
            other["title"]
            for other in events
            if other is not item
            and other["span"]
            and other["span"][0] < ends
            and begins < other["span"][1]
        ]
        if others:
            tags.append(
                '<span class="day-tag is-overlap">'
                + ui.ui(
                    "Overlaps {events}",
                    events=("、" if ui.current() == "zh-CN" else ", ").join(others),
                )
                + "</span>"
            )
    if item["state"] == "past":
        tags.append('<span class="day-tag">' + ui.ui("Ended") + "</span>")
    return (
        '<li class="day-event'
        + (" is-" + item["state"] if item["state"] else "")
        + '"><div class="day-event-time"><strong>'
        + item["start"]
        + "</strong>"
        + ("<span>" + item["until"] + "</span>" if item["until"] else "")
        + '</div><div class="day-event-body"><div class="day-event-line">'
        '<span class="event-title" data-content>'
        + html.escape(item["title"])
        + "</span>"
        + "".join(tags)
        + "</div>"
        + (
            '<span class="event-location" data-content>'
            + html.escape(item["place"])
            + "</span>"
            if item["place"]
            else ""
        )
        + (
            '<p class="event-notes" data-content>' + html.escape(item["notes"]) + "</p>"
            if item["notes"]
            else ""
        )
        + item["source"]
        + "</div></li>"
    )


def day_schedule(data, day, events, now):
    """The day's events: all-day and deadline chips, then cards with a now line between past and upcoming."""
    chips = [
        '<span class="day-chip"><small>'
        + ui.ui("All day")
        + "</small><span data-content>"
        + html.escape(item["title"])
        + "</span></span>"
        for item in events
        if item["state"] == "all-day"
    ] + [
        '<span class="day-chip is-deadline"><small>'
        + ui.ui("Deadline")
        + "</small><span data-content>"
        + html.escape(task["text"])
        + "</span></span>"
        for task in day["tasks"]
        if checklist_kind(task) == "deadline"
    ]
    cards = [item for item in events if item["state"] != "all-day"]
    live = any(item["state"] in ("past", "now", "next") for item in cards)
    upcoming = next((item for item in cards if item["state"] == "next"), None)
    ended = sum(item["state"] == "past" for item in cards)
    rows, placed = [], not live
    for item in cards:
        if not placed and item["state"] in ("now", "next"):
            rows.append(now_line(data["timezone"], now))
            placed = True
        rows.append(day_event_card(item, cards, upcoming))
    if not placed:
        rows.append(now_line(data["timezone"], now))
    empty = (
        '<p class="schedule-empty">'
        + ui.ui(
            "Calendar unavailable"
            if data.get("calendar_error")
            else "Nothing on the calendar."
        )
        + "</p>"
    )
    return (
        '<section class="focus-panel day-schedule" aria-labelledby="day-schedule-heading">'
        '<header class="day-card-head"><h2 id="day-schedule-heading">'
        + ui.ui("Schedule")
        + "</h2>"
        + (
            '<span class="day-count">'
            + ui.ui(
                "1 event" if len(events) == 1 else "{count} events", count=len(events)
            )
            + "</span>"
            if events
            else ""
        )
        + '<a class="day-jump" href="#day-todos" hidden></a></header>'
        + (
            '<div class="day-chips">' + holidays(day) + "".join(chips) + "</div>"
            if chips or day["holidays"]
            else ""
        )
        + (
            '<button class="day-earlier" type="button" aria-expanded="false">'
            + ui.ui("Earlier today · {count}", count=ended)
            + "</button>"
            if ended
            else ""
        )
        + ('<ol class="day-events">' + "".join(rows) + "</ol>" if cards else "")
        + (empty if not events else "")
        + "</section>"
    )


def now_line(zone, now):
    # schedule.js sets the time from each check; the line moves only when an event's state does.
    return (
        '<li class="day-now">'
        + ui.ui("Now")
        + ' · <span class="day-now-time">'
        + now.astimezone(ZoneInfo(zone)).strftime("%H:%M")
        + "</span></li>"
    )


CHECK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12.5l4 4 8-9" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def checklist_row(task, day, kind):
    meta = []
    lead = cadence(task.get("rhythm")) if kind == "routine" else task.get("project")
    if lead:
        meta.append(
            '<span class="tl-lead" data-content>' + html.escape(lead) + "</span>"
        )
    if task.get("due_date") and task.get("marker") != "due":
        meta.append(
            "<span>"
            + ui.ui(
                "Soft target: {date}" if task.get("due_soft") else "Due: {date}",
                date=ui.human_dates(task.get("due_at") or task["due_date"], day),
            )
            + "</span>"
        )
    state = task.get("status", "done" if task["done"] else "open")
    if state in ("partial", "blocked") and not task["done"]:
        meta.append('<span class="tl-tag">' + ui.ui(state.capitalize()) + "</span>")
    if task["section"] == "nice-to-do":
        meta.append('<span class="tl-tag">' + ui.ui("Optional") + "</span>")
    note = " · ".join(
        value for value in (task.get("detail"), task.get("report_detail")) if value
    )
    icon, hint = task_kind(task)
    text = (
        '<span class="tl-check">'
        + CHECK
        + '</span><span class="tl-text"><span class="tl-title"><span class="task-icon is-'
        + icon
        + '" role="img" title="'
        + html.escape(ui.text(hint), quote=True)
        + '" aria-label="'
        + html.escape(ui.text(hint), quote=True)
        + '"></span><span class="task-title" data-content>'
        + html.escape(task["text"])
        + "</span></span>"
        + ('<span class="tl-meta">' + "".join(meta) + "</span>" if meta else "")
        + (
            '<span class="tl-note" data-content>' + html.escape(note) + "</span>"
            if note
            else ""
        )
        + "</span>"
    )
    classes = "tl-item" + (" is-done" if task["done"] else "")
    classes += " is-optional" if task["section"] == "nice-to-do" else ""
    if not task.get("tickable"):
        return (
            '<li class="'
            + classes
            + ' is-ro"><div class="tl-row">'
            + text
            + "</div></li>"
        )
    action = (
        "Mark “{task}” not done" if task["done"] else "Mark “{task}” done"
    ).format(task=task["text"])
    # Enabled by schedule.js; without JavaScript the row stays read-only.
    return (
        '<li class="'
        + classes
        + '"><button id="tick-'
        + day
        + "-"
        + html.escape(task["task_id"], quote=True)
        + '" class="tl-row task-tick" type="button" disabled aria-label="'
        + html.escape(action, quote=True)
        + '" data-tick-id="'
        + html.escape(task["task_id"], quote=True)
        + '" data-tick-date="'
        + day
        + '" data-tick-revision="'
        + str(task["revision"])
        + '" data-tick-done="'
        + str(bool(task["done"])).lower()
        + '">'
        + text
        + "</button></li>"
    )


def progress(done, total):
    label = ui.ui("{done} of {total} done", done=done, total=total)
    bar = (
        "".join(
            '<i class="is-on"></i>' if i < done else "<i></i>" for i in range(total)
        )
        if total <= 10  # Segments read well up to 10; longer lists get one bar.
        else '<i class="is-on" style="width:' + str(100 * done // total) + '%"></i>'
    )
    return (
        '<div class="tl-bar'
        + ("" if total <= 10 else " is-continuous")
        + '" role="progressbar" aria-valuemin="0" aria-valuemax="'
        + str(total)
        + '" aria-valuenow="'
        + str(done)
        + '" aria-label="'
        + html.escape(
            ui.text("{done} of {total} done", done=done, total=total), quote=True
        )
        + '">'
        + bar
        + "</div>",
        label,
    )


def day_checklist(data, day):
    """Routines, then other to-dos, each in the schedule's order. Events and deadline markers never count."""
    today = day["date"] == data["today"]
    future = day["date"] > data["today"]
    if day["plan_error"]:
        body = (
            '<p class="schedule-empty">'
            + ui.ui(
                "Task records unavailable"
                if day["plan_error"] == "tasks"
                else "Daily plan unavailable"
            )
            + "</p>"
        )
    else:
        rows = [
            (task, checklist_kind(task))
            for task in day["tasks"]
            if checklist_kind(task) != "deadline" and not task.get("closed")
        ]
        rows.sort(key=lambda row: row[1] != "routine")
        counted = [task for task, _ in rows if task["section"] != "nice-to-do"]
        done = sum(bool(task["done"]) for task in counted)
        everything = bool(counted) and done == len(counted)
        open_rows = "".join(
            checklist_row(task, day["date"], kind)
            for task, kind in rows
            if not task["done"]
        )
        done_rows = "".join(
            checklist_row(task, day["date"], kind)
            for task, kind in rows
            if task["done"]
        )
        done_count = sum(bool(task["done"]) for task, _ in rows)
        if not rows:
            head = ""
        elif future:
            head = (
                '<p class="tl-future">'
                + ui.ui("Planned for this day. You can tick these on the day.")
                + "</p>"
            )
        elif counted:
            bar, label = progress(done, len(counted))
            head = (
                '<div class="tl-head'
                + (" is-all" if everything else "")
                + '"><strong class="tl-progress">'
                + (
                    ui.ui("All done for today" if today else "All done")
                    if everything
                    else label
                )
                + "</strong>"
                + bar
                + "</div>"
            )
        else:
            head = ""
        if not rows:
            body = (
                '<div class="tl-empty"><p>'
                + ui.ui("Nothing planned for today." if today else "No to-dos saved")
                + "</p>"
                + (
                    '<a class="tl-add" href="/chat" data-quick-ask="Add a daily routine: " data-quick-ask-prefill>'
                    + ui.ui("Add a routine with your secretary")
                    + "</a>"
                    if not future
                    else ""
                )
                + "</div>"
            )
        else:
            # All done: a calm line, and the ticked rows fold behind a working "Done · N" button.
            fold = not open_rows
            body = (
                head
                + (
                    '<div class="tl-all"><p>'
                    + ui.ui("Routines come back tomorrow.")
                    + "</p></div>"
                    if everything and today
                    else ""
                )
                + ('<ul class="tl-list">' + open_rows + "</ul>" if open_rows else "")
                + (
                    (
                        '<button class="tl-done-head" type="button" aria-expanded="false">'
                        if fold
                        else '<p class="tl-done-head">'
                    )
                    + ui.ui("Done · {count}", count=done_count)
                    + ("</button>" if fold else "</p>")
                    + '<ul class="tl-list tl-done"'
                    + (" hidden" if fold else "")
                    + ">"
                    + done_rows
                    + "</ul>"
                    if done_rows
                    else ""
                )
            )
    return (
        '<section class="focus-panel day-todos" id="day-todos" aria-labelledby="day-todos-heading">'
        '<header class="day-card-head"><h2 id="day-todos-heading">'
        + ui.ui("To-dos")
        + '</h2></header><div class="tl'
        + (" is-today" if today else "")
        + '">'
        + body
        + "</div></section>"
    )


def day_view(data, checked, now):
    day, offset = data["days"][0], data["offset"]
    events = sorted(
        (
            day_event(event, day["date"], data["timezone"], now)
            for event in day["events"]
        ),
        key=lambda item: item["sort"],
    )
    done = sum(task["done"] for task in day["tasks"])
    relative = {-1: ui.ui("Yesterday"), 0: ui.ui("Today"), 1: ui.ui("Tomorrow")}.get(
        offset
    ) or ui.ui(
        "In {count} days" if offset > 0 else "{count} days ago", count=abs(offset)
    )
    controls = (
        '<div class="schedule-toolbar is-day"><div class="schedule-date"><h1 id="week-heading">'
        + date_part(day["date"], "full")
        + "</h1>"
        '<p class="schedule-range">' + relative + "</p></div>"
        '<nav class="schedule-navigation" aria-label="Day navigation">'
        + mode_switch("day", data["week"])
        + step_link(
            "day-previous",
            "/schedule?view=day&day=" + str(offset - 1),
            "Previous day",
            "‹",
            offset > -DAY_RANGE,
        )
        # Phones hide the heading, so the date sits between the day arrows.
        + '<a id="day-current" class="current-week" data-schedule-nav href="/schedule?view=day">'
        + '<span class="day-current-label">'
        + ui.ui("Today")
        + '</span><span class="day-current-date">'
        + relative
        + " · "
        + date_part(day["date"], "weekday-date")
        + "</span></a>"
        + step_link(
            "day-next",
            "/schedule?view=day&day=" + str(offset + 1),
            "Next day",
            "›",
            offset < DAY_RANGE,
        )
        + tools(data, checked, "Day details", len(events), len(day["tasks"]), done)
        + "</nav></div>"
    )
    body = (
        '<div id="day-'
        + day["date"]
        + '" class="day-wrap'
        + (" is-today" if day["date"] == data["today"] else "")
        + '">'
        + day_schedule(data, day, events, now)
        + day_checklist(data, day)
        + "</div>"
    )
    return controls + notices(data) + body, [item["state"] for item in events]


def compact(app):
    """Seven days from today for the Android widgets: plain fields, no markup."""
    zone = app.profile().get("timezone")
    if not zone:
        raise ValueError("Initialize your profile timezone first")
    now = app.now() if app.now else datetime.now(UTC)
    weeks = [saved_week(app.runtime, zone, now, offset) for offset in (0, 1)]
    today = weeks[0]["today"]
    days = [day for week in weeks for day in week["days"] if day["date"] >= today][:7]
    result = []
    for day in days:
        events = []
        for event in day["events"]:
            if event.get("draft"):
                events.append(
                    {
                        "subject": event["title"],
                        "time": "",
                        "end": "",
                        "all_day": False,
                        "tbc": True,
                        "location": event.get("location") or "",
                    }
                )
                continue
            begins, ends = (
                point.astimezone(ZoneInfo(zone)) for point in endpoints(event)
            )
            timed = not event["all_day"]
            events.append(
                {
                    "subject": event["subject"],
                    "all_day": bool(event["all_day"]),
                    "tbc": False,
                    "time": begins.strftime("%H:%M")
                    if timed and begins.date().isoformat() == day["date"]
                    else "",
                    "end": ends.strftime("%H:%M")
                    if timed and ends.date().isoformat() == day["date"]
                    else "",
                    "location": event.get("location") or event.get("online") or "",
                }
            )
        result.append(
            {
                "date": day["date"],
                "events": events,
                "tasks": [
                    {
                        "text": task["text"],
                        "done": bool(task["done"]),
                        "tickable": bool(task.get("tickable")),
                        "kind": checklist_kind(task),
                        "cadence": cadence(task.get("rhythm")),
                        "status": task.get(
                            "status", "done" if task["done"] else "open"
                        ),
                        "project": task.get("project") or "",
                        "optional": task["section"] == "nice-to-do",
                        # Future rows carry them too, so the Today widget can tick its cached next day
                        # once 04:00 passes; deadline markers and stopped habits never get them.
                        **(
                            {"id": task["task_id"], "revision": task["revision"]}
                            if "task_id" in task
                            and task.get("marker") != "due"
                            and not task.get("closed")
                            else {}
                        ),
                    }
                    for task in day["tasks"]
                ],
            }
        )
    return {
        "today": today,
        "timezone": zone,
        "days": result,
        "warnings": list(dict.fromkeys(weeks[0]["warnings"] + weeks[1]["warnings"])),
    }


def tick(app, body):
    """One tap on a Schedule to-do or habit, on today or an earlier day: done, or back again.

    The key is the caller's own random retry key; a retry with the same key and input
    returns the first receipt instead of saving twice."""
    if (
        not isinstance(body, dict)
        or set(body) != {"id", "date", "revision", "done", "key"}
        or not isinstance(body["id"], str)
        or not isinstance(body["date"], str)
        or type(body["revision"]) is not int
        or type(body["done"]) is not bool
        or not isinstance(body["key"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", body["key"])
    ):
        raise ValueError("Invalid schedule tap")
    zone = app.profile().get("timezone")
    if not zone:
        raise ValueError("Initialize your profile timezone first")
    now = (app.now() if app.now else datetime.now(UTC)).astimezone(ZoneInfo(zone))
    day = body["date"]
    if date.fromisoformat(day).isoformat() != day or day > briefing_day(zone, now):
        raise ValueError("invalid_date: only today and earlier days can be ticked")
    arguments = (
        body["id"],
        body["revision"],
        day,
        body["done"],
        "schedule",
        "schedule-tap:" + body["key"],
        now.isoformat(timespec="seconds"),
    )
    if body["id"].startswith("cu_"):
        from goodmorning.records.custom_store import CustomStore

        store = CustomStore(app.runtime, write=True)
        try:
            receipt = store.tick(*arguments)
        finally:
            store.close()
    else:
        from goodmorning.records.inbox_store import InboxStore
        from goodmorning.records.task_store import TaskStore

        inbox = InboxStore(app.runtime, write=True)
        try:
            receipt = TaskStore(inbox).tick(*arguments)
        finally:
            inbox.close()
    return {
        "saved": True,
        "id": body["id"],
        "date": day,
        "done": body["done"],
        "revision": receipt["revision"],
    }


def upcoming(app, hours=3):
    """Timed calendar events that start within the next hours, for reminder notifications."""
    zone = app.profile().get("timezone")
    calendar = app.runtime / "calendar.sqlite"
    if not zone or calendar.is_symlink() or not calendar.exists():
        return {"events": []}
    now = app.now() if app.now else datetime.now(UTC)
    store = CalendarStore(str(calendar), readonly=True)
    try:
        events = safe_value(
            store.query(now, now + timedelta(hours=hours), limit=-1, details=True)
        )
    finally:
        store.close()
    result = []
    for event in events:
        if event.get("all_day") or event.get("draft"):
            continue
        begins = endpoints(event)[0]
        if begins > now:
            result.append(
                {
                    "key": event["id"] + "@" + begins.isoformat(),
                    "subject": event["subject"],
                    "starts": begins.timestamp(),
                    "time": begins.astimezone(ZoneInfo(zone)).strftime("%H:%M"),
                    "location": event.get("location") or event.get("online") or "",
                }
            )
    return {"events": result}


def snapshot(app, offset, mode="week"):
    zone = app.profile().get("timezone")
    if not zone:
        raise ValueError("Initialize your profile timezone first")
    now = app.now() if app.now else datetime.now(UTC)
    data = (saved_day if mode == "day" else saved_week)(app.runtime, zone, now, offset)
    parser = ui.InterfaceHTML()
    checked = now.astimezone(ZoneInfo(zone)).strftime("%H:%M")
    markup, states = (
        day_view(data, checked, now) if mode == "day" else (view(data, checked), [])
    )
    parser.feed(markup)
    parser.close()
    markup = "".join(parser.parts)
    revision = hashlib.sha256(
        json.dumps([data, ui.current(), mode, states], sort_keys=True).encode()
    ).hexdigest()
    return {
        "view": markup,
        "revision": revision,
        "mode": mode,
        "week": data.get("week", offset),
        "today": data["today"],
        "theme": clock_theme(zone, now)["theme"],
        "checked": checked,
    }


def page(app, offset, mode="week"):
    zone = app.profile().get("timezone")
    theme = clock_theme(zone, app.now() if app.now else None)["theme"]
    if zone:
        result = snapshot(app, offset, mode)
        content = result["view"]
    else:
        result = {"revision": None, "checked": None}
        content = (
            '<section class="waiting-room schedule-setup"><h1>Let’s make this yours.</h1><p class="subtitle">Finish setup to see your schedule. Your saved records stay unchanged.</p>'
            '<a class="initialize-button" href="/chat?mode=initialize">Initialize my secretary</a></section>'
        )
    config = html.escape(
        json.dumps(
            {
                "mode": mode,
                "revision": result["revision"],
                "checked": result["checked"],
                "ready": bool(zone),
            }
        ),
        quote=True,
    )
    source = (
        '<!doctype html><html lang="en" data-edition="'
        + theme
        + '"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Schedule — GoodMorning</title>'
        '<script src="/schedule-mode.js"></script>'
        + favicon_links()
        + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/schedule.css">'
        '<link rel="stylesheet" href="/scroll-rails.css"><script src="/scroll-rails.js" defer></script></head><body class="schedule-page">'
        '<a class="skip-link" href="#schedule-view">Skip to schedule</a><header class="masthead"><a class="wordmark" href="/gm">GoodMorning</a>'
        '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm">Morning</a><a class="edition-link" href="/gn">Evening</a>'
        '<a class="edition-link selected" href="/schedule" aria-current="page">Schedule</a><a class="edition-link" href="/letters">Letters</a><a class="edition-link" href="/chat">Secretary</a>'
        + desk_link(app.profile())
        + "</nav></header>"
        '<main><div id="schedule-view">'
        + content
        + '</div><p id="schedule-error" role="alert"></p><div id="schedule-notice" class="schedule-notice" role="status"></div>'
        "<noscript>Navigation and saved plans work without JavaScript. Reload to see updates.</noscript></main>"
        '<div id="schedule-config" hidden data-config="'
        + config
        + '"></div><script src="/schedule.js" defer></script></body></html>'
    )
    return app.resources.rewrite(
        ui.page(
            quick_chat.widget(source, app.csrf), app.csrf, "/schedule", avatars=True
        )
    ).encode()
